"""Review manifest — snapshot, verify, stage, clear, commit-and-push."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import (
    REVIEW_MANIFEST_FILENAME,
    BootstrapError,
    log_info,
    read_json_file,
    sha256_file,
)
from .git import head_commit_or_none, repo_current_branch, run


def review_manifest_path(project: Path, override: Optional[str]) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    return (project / ".git" / REVIEW_MANIFEST_FILENAME).resolve()


def build_review_manifest(
    project: Path, preview: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    from .preview import build_publish_preview

    project = project.resolve()
    preview = preview or build_publish_preview(project)
    files: List[Dict[str, Any]] = []
    for entry in preview["files"]:
        file_path = project / entry["path"]
        files.append({
            "raw": entry["raw"],
            "path": entry["path"],
            "old_path": entry.get("old_path"),
            "kind": entry["kind"],
            "index_status": entry["index_status"],
            "worktree_status": entry["worktree_status"],
            "staged": bool(entry["staged"]),
            "unstaged": bool(entry["unstaged"]),
            "exists": file_path.exists(),
            "sha256": sha256_file(file_path),
        })
    files = sorted(
        files,
        key=lambda item: (item.get("old_path") or "", item["path"], item["kind"], item["raw"]),
    )
    # stage_targets 只含工作区现存路径。
    # rename 的 old_path 已被 git mv 删除，传给 git add 会报 "pathspec did not match"；
    # git add 目标路径 + index 里的 R 记录会让 commit 正确识别 rename。
    # （deleted 条目相反：路径虽不在工作区，但 git add <deleted> 能 stage 删除，必须保留。）
    stage_targets: List[str] = []
    seen_targets = set()
    for item in files:
        candidate = item["path"]
        if candidate and candidate not in seen_targets:
            seen_targets.add(candidate)
            stage_targets.append(candidate)
    hash_payload = {
        "head_commit": head_commit_or_none(project),
        "status_lines": preview["status_lines"],
        "files": files,
    }
    snapshot_hash = hashlib.sha256(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "version": 1,
        "project_path": str(project),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "head_commit": hash_payload["head_commit"],
        "status_lines": preview["status_lines"],
        "counts": preview["counts"],
        "files": files,
        "stage_targets": stage_targets,
        "snapshot_hash": snapshot_hash,
    }


def write_review_manifest(
    project: Path,
    override: Optional[str],
    preview: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    manifest = build_review_manifest(project, preview)
    path = review_manifest_path(project, override)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "path": str(path),
        "snapshot_hash": manifest["snapshot_hash"],
        "created_at": manifest["created_at"],
        "file_count": len(manifest["files"]),
    }


def load_review_manifest(path: Path) -> Dict[str, Any]:
    try:
        data = read_json_file(path)
    except FileNotFoundError as exc:
        raise BootstrapError(f"review manifest not found: {path}; run preview first") from exc
    if not isinstance(data, dict) or "snapshot_hash" not in data or "files" not in data:
        raise BootstrapError(f"review manifest is invalid: {path}")
    return data


def verify_review_manifest(
    project: Path, override: Optional[str]
) -> Dict[str, Any]:
    from .preview import build_publish_preview

    project = project.resolve()
    path = review_manifest_path(project, override)
    stored = load_review_manifest(path)
    stored_project = stored.get("project_path")
    if stored_project and Path(stored_project).expanduser().resolve() != project:
        raise BootstrapError(
            f"review manifest belongs to a different project: {stored_project}"
        )
    current_preview = build_publish_preview(project)
    current_manifest = build_review_manifest(project, current_preview)
    return {
        "path": str(path),
        "stored": stored,
        "current": current_manifest,
        "preview": current_preview,
        "matches": stored.get("snapshot_hash") == current_manifest.get("snapshot_hash"),
    }


def stage_review_manifest(project: Path, manifest: Dict[str, Any]) -> List[str]:
    targets = [item for item in manifest.get("stage_targets", []) if item]
    if not targets:
        return []
    run(["git", "add", "-A", "--", *targets], cwd=project, check=True)
    return targets


def clear_review_manifest(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _push_with_fallback(project: Path, remote_name: str, branch: str) -> bool:
    """推送当前分支；9p/drvfs 挂载下 `git push -u` 写 upstream 配置会因 chmod EPERM
    失败，自动降级为不带 -u 的普通 push（内容已推送成功，仅上游跟踪未设置）。"""
    res = run(["git", "push", "-u", remote_name, branch], cwd=project, check=False)
    if res.returncode == 0:
        return True
    res2 = run(["git", "push", remote_name, branch], cwd=project, check=False)
    if res2.returncode != 0:
        raise BootstrapError(
            f"git push 失败: {res.stderr.strip()}\n"
            f"(fallback push 也失败: {res2.stderr.strip()})"
        )
    log_info("push 成功；但 -u 上游跟踪写入失败（9p 挂载 config 写锁受限），已降级为普通 push")
    return False


def commit_and_push(
    project: Path,
    remote_name: str,
    commit_message: str,
    review_manifest: Dict[str, Any],
    manifest_path: Path,
) -> Dict[str, Any]:
    from .preview import validate_commit_message

    validation = validate_commit_message(commit_message)
    if not validation["valid"]:
        raise BootstrapError(
            "invalid commit message: " + "; ".join(validation["issues"])
        )
    if not review_manifest.get("files"):
        return {
            "committed": False,
            "pushed": False,
            "reason": "working tree is clean",
            "commit_message_validation": validation,
            "review_snapshot_hash": review_manifest.get("snapshot_hash"),
        }
    staged_targets = stage_review_manifest(project, review_manifest)
    # Support single-line and multi-line commit messages.
    # Single-line: use -m; multi-line: use -m per line (git joins them with a blank line).
    lines = commit_message.strip().splitlines()
    if len(lines) == 1:
        run(["git", "commit", "-m", commit_message], cwd=project, check=True)
    else:
        cmd = ["git", "commit"]
        for line in lines:
            cmd.extend(["-m", line])
        run(cmd, cwd=project, check=True)
    branch = repo_current_branch(project)
    _push_with_fallback(project, remote_name, branch)
    commit_hash = run(
        ["git", "rev-parse", "HEAD"], cwd=project, check=True
    ).stdout.strip()
    clear_review_manifest(manifest_path)
    return {
        "committed": True,
        "pushed": True,
        "branch": branch,
        "commit_hash": commit_hash,
        "commit_message_validation": validation,
        "review_manifest_path": str(manifest_path),
        "review_snapshot_hash": review_manifest.get("snapshot_hash"),
        "staged_targets": staged_targets,
        "review_manifest_cleared": True,
    }


def commit_and_push_batches(
    project: Path,
    remote_name: str,
    batches: List[Dict[str, Any]],
    review_manifest: Dict[str, Any],
    manifest_path: Path,
) -> Dict[str, Any]:
    """多批次提交并推送：逐批 `git add <files>` + `git commit`，全部完成后一次 push。

    batches: [{"files": [...], "message": "..."}, ...]

    校验：
    - 每批 message 通过 validate_commit_message
    - 各批 files 并集必须恰好等于 manifest 文件集（防漏提交/多提交）
    - 任一批失败即中止（已提交批次保留，不自动回滚——由用户按错误信息处理）
    """
    from .preview import validate_commit_message

    if not batches:
        raise BootstrapError("--batches 文件为空或缺少 batches 数组")

    manifest_files = {f["path"] for f in (review_manifest.get("files") or [])}
    batch_files = set()
    for b in batches:
        files = b.get("files") or []
        message = b.get("message") or ""
        if not files or not message.strip():
            raise BootstrapError("每批必须同时提供 files（非空）与 message（非空）")
        validation = validate_commit_message(message)
        if not validation["valid"]:
            raise BootstrapError(
                f"invalid commit message {message!r}: " + "; ".join(validation["issues"])
            )
        batch_files.update(files)
    if batch_files != manifest_files:
        missing = sorted(manifest_files - batch_files)
        extra = sorted(batch_files - manifest_files)
        raise BootstrapError(
            "batches 文件集与 review manifest 不一致"
            + (f"；漏提交: {missing}" if missing else "")
            + (f"；多余: {extra}" if extra else "")
        )

    batch_results = []
    for i, b in enumerate(batches, 1):
        files = b["files"]
        message = b["message"].strip()
        run(["git", "add", "--", *files], cwd=project, check=True)
        lines = message.splitlines()
        cmd = ["git", "commit"]
        for line in lines:
            cmd.extend(["-m", line])
        run(cmd, cwd=project, check=True)
        commit_hash = run(
            ["git", "rev-parse", "HEAD"], cwd=project, check=True
        ).stdout.strip()
        batch_results.append({
            "batch": i,
            "files": files,
            "message": lines[0],
            "commit_hash": commit_hash,
        })
        log_info(f"batch {i}/{len(batches)} committed: {lines[0]}")

    branch = repo_current_branch(project)
    _push_with_fallback(project, remote_name, branch)
    clear_review_manifest(manifest_path)
    return {
        "committed": True,
        "pushed": True,
        "branch": branch,
        "batches": batch_results,
        "review_manifest_path": str(manifest_path),
        "review_snapshot_hash": review_manifest.get("snapshot_hash"),
        "review_manifest_cleared": True,
    }
