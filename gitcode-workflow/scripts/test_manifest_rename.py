"""test_manifest_rename.py — 修复 gitcode-workflow publish 对 rename 的处理 bug.

Bug 复现：
  当工作区有 rename（git mv）时，build_review_manifest 把 old_path（源路径，
  已被 git mv 删除）也加入 stage_targets。publish 时 git add <源路径> 会报
  "pathspec did not match any files"，整个 publish 失败。

修复目标：
  - rename 条目的 stage_targets 只含目标路径（新路径，已存在）
  - 源路径不进 stage_targets（git add 目标路径会自动识别 rename）
  - 普通 modified/added/untracked 行为不变（无回归）

测试设计：
  在 tmp 目录构造真实 git repo + git mv 操作，调用 build_review_manifest，
  断言 stage_targets 不含已删除路径。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# 让测试能 import gitcode-workflow 的 lib 模块
SKILL_ROOT = Path.home() / ".claude" / "skills" / "gitcode-workflow" / "scripts"
sys.path.insert(0, str(SKILL_ROOT))
from lib.manifest import build_review_manifest  # noqa: E402
from lib.common import run  # noqa: E402


def _git(cwd: Path, *args: str) -> str:
    """跑 git 命令并返回 stdout。"""
    return run(["git", *args], cwd=cwd, check=True).stdout.strip()


@pytest.fixture
def rename_repo(tmp_path: Path) -> Path:
    """构造一个 tmp git repo，含 1 个 rename + 1 个 modified + 1 个 untracked.

    模拟真实的"改 skill 文件夹名"场景：
    - 创建 old_dir/file.py 并 commit
    - git mv old_dir/file.py → new_dir/file.py
    - 修改 new_dir/file.py 内容（rename + modify）
    - 新增 untracked.py
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")

    # 创建旧文件并 commit
    (repo / "old_dir").mkdir()
    (repo / "old_dir" / "file.py").write_text("# original\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")

    # rename + 微改（保持高相似度让 git log --follow 能追溯历史；真实改名场景相似度 98%+）
    (repo / "new_dir").mkdir(exist_ok=True)
    _git(repo, "mv", "old_dir/file.py", "new_dir/file.py")
    target = repo / "new_dir" / "file.py"
    assert target.exists(), "git mv should have moved the file"
    target.write_text("# original\n# tiny edit after rename\n", encoding="utf-8")

    # 加一个 untracked 文件
    (repo / "untracked.py").write_text("# new\n", encoding="utf-8")

    return repo


# ──────────────────────────────────────────────────────────────────────────
# 1. 核心修复验证：rename 的 stage_targets 不含已删除的源路径
# ──────────────────────────────────────────────────────────────────────────
def test_rename_source_path_not_in_stage_targets(rename_repo: Path):
    """rename 的源路径（已删除）不应出现在 stage_targets 里。

    Bug 修复前：stage_targets = ['old_dir/file.py', 'new_dir/file.py', 'untracked.py']
    Bug 修复后：stage_targets = ['new_dir/file.py', 'untracked.py']
    """
    manifest = build_review_manifest(rename_repo)
    targets = manifest["stage_targets"]

    print(f"\nstage_targets = {targets}")
    print(f"files = {[(f['path'], f.get('old_path'), f['kind']) for f in manifest['files']]}")

    # 关键断言：源路径不在 targets
    assert "old_dir/file.py" not in targets, (
        f"已删除的源路径不应进入 stage_targets，否则 git add 会报 pathspec 错误。"
        f" 当前 targets = {targets}"
    )
    # 目标路径应在
    assert "new_dir/file.py" in targets


# ──────────────────────────────────────────────────────────────────────────
# 2. 目标路径仍能正确 stage（git add 不再报 pathspec 错误）
# ──────────────────────────────────────────────────────────────────────────
def test_rename_target_path_stages_successfully(rename_repo: Path):
    """用 manifest 给的 targets 实际跑 git add + commit，验证不报错且工作区干净。

    修复前：git add 含已删除源路径 → rc=128 pathspec 错误，publish 中断
    修复后：git add 只含现存路径 → rc=0，commit 成功，工作区干净

    注：rename+modify 场景下，git 可能识别为 R rename 或 A+D，两种都是合法的
    提交结果（取决于相似度阈值）。本测试不依赖具体识别方式，只验证核心契约：
    stage 不报错 + commit 成功 + 工作区干净。
    """
    manifest = build_review_manifest(rename_repo)
    targets = manifest["stage_targets"]

    add_result = subprocess.run(
        ["git", "add", "-A", "--", *targets],
        cwd=rename_repo, capture_output=True, text=True,
    )
    assert add_result.returncode == 0, (
        f"git add 失败（rc={add_result.returncode}）：\n"
        f"  targets: {targets}\n  stderr: {add_result.stderr}"
    )

    _git(rename_repo, "commit", "-q", "-m", "test rename")

    # commit 后工作区应干净（所有变化都已提交）
    status = _git(rename_repo, "status", "--short")
    assert status == "", f"commit 后工作区应干净，但仍有：\n{status}"


# ──────────────────────────────────────────────────────────────────────────
# 3. 无回归：普通 modified/untracked 场景行为不变
# ──────────────────────────────────────────────────────────────────────────
def test_no_regression_pure_modified(tmp_path: Path):
    """无 rename 时，stage_targets 行为不变。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "a.py").write_text("original\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    (repo / "a.py").write_text("modified\n")

    manifest = build_review_manifest(repo)
    assert manifest["stage_targets"] == ["a.py"]


def test_no_regression_untracked(tmp_path: Path):
    """新增 untracked 文件时，stage_targets 含 untracked 路径。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    (repo / "new.py").write_text("new\n")

    manifest = build_review_manifest(repo)
    assert manifest["stage_targets"] == ["new.py"]
