"""Shared utilities for diagram-* / db-skill skills."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

#: 环境变量名：显式指定 db-skill 配置文件路径
DEFAULT_CONFIG_ENV = "DB_SKILL_CONFIG"


def resolve_output_path(input_file: Path | None, skill_name: str, default_name: str) -> Path:
    """推断输出路径：<项目目录>/thesis-output/<skill-name>/ 或 ~/.claude/skills-output/<skill-name>/"""
    if input_file and input_file.is_absolute():
        for parent in input_file.resolve().parents:
            if (parent / "thesis-output").exists() or (parent / "docs").exists():
                output_dir = parent / "thesis-output" / skill_name
                output_dir.mkdir(parents=True, exist_ok=True)
                return output_dir / default_name
    out = Path.home() / ".claude" / "skills-output" / skill_name
    out.mkdir(parents=True, exist_ok=True)
    return out / default_name


# ─── db-skill 共享实现（mysql_tool.py / pg_tool.py 原先各自复制一份）───────────
#
# 两个引擎的这三段逻辑逐字节相同，只有「候选配置文件名」不同（mysql.json / pg.json），
# 因此把实现收在 common.py，由各引擎模块传入自己的候选列表。
# 原先 27 + 12 + 8 = 47 行 × 2 份重复，现为 1 份实现 + 各 1 个薄包装。


def resolve_config_path(
    explicit: Optional[str],
    candidate_files: Tuple[str, ...],
    env_var: str = DEFAULT_CONFIG_ENV,
) -> Path:
    """解析 db-skill 配置文件路径。

    优先级：显式 --config 参数 → 环境变量（默认 DB_SKILL_CONFIG）→ 从 cwd 向上逐级
    查找 candidate_files 中的相对路径。
    """
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        return path

    env_path = os.environ.get(env_var)
    if env_path:
        path = Path(env_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Config from {env_var} not found: {path}")
        return path

    cwd = Path.cwd().resolve()
    for base in (cwd, *cwd.parents):
        for rel in candidate_files:
            candidate = base / rel
            if candidate.exists():
                return candidate

    checked = ", ".join(candidate_files)
    raise FileNotFoundError(
        "No config file found. Use --config, set %s, or create one of: %s" % (env_var, checked)
    )


def choose_limit(user_limit: Optional[int], config: Dict[str, Any]) -> Tuple[int, int]:
    """把用户传入的 limit 夹到 [1, config.limits.max_limit]，返回 (chosen, max_limit)。"""
    default_limit = int(config["limits"].get("default_limit", 200))
    max_limit = int(config["limits"].get("max_limit", 1000))

    chosen = default_limit if user_limit is None else int(user_limit)
    if chosen < 1:
        chosen = 1
    if chosen > max_limit:
        chosen = max_limit
    return chosen, max_limit


def shutil_which(name: str) -> Optional[str]:
    """在 PATH 中查找可执行文件（不依赖 shutil.which 的版本差异）。"""
    for p in os.environ.get("PATH", "").split(os.pathsep):
        full = Path(p) / name
        if full.exists() and os.access(full, os.X_OK):
            return str(full)
    return None

