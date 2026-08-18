"""gh CLI wrapper —— 官方 GitHub CLI 作为认证与 API 主干。

设计原则：所有 GitHub 侧能力（认证、仓库、Issue、PR、用户信息）一律调用官方
`gh` 命令，本模块只做参数拼装与 JSON 解析，不重复实现 GitHub REST API 客户端。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .common import BootstrapError, ensure_tool, run


def ensure_gh() -> None:
    ensure_tool("gh", "gh CLI 未安装：请安装 https://cli.github.com（或 sudo apt install gh）")


def require_login() -> str:
    """确保 gh 已登录并返回当前登录用户名。"""
    ensure_gh()
    res = run(["gh", "auth", "status"], check=False)
    if res.returncode != 0:
        raise BootstrapError("gh 未登录：请先运行 `gh auth login` 完成 GitHub 认证")
    res = run(["gh", "api", "user", "--jq", ".login"], check=False)
    if res.returncode != 0:
        raise BootstrapError(f"无法读取 gh 登录用户: {res.stderr.strip()}")
    return res.stdout.strip()


def gh_api(
    method: str,
    endpoint: str,
    fields: Optional[Dict[str, str]] = None,
    paginate: bool = False,
) -> Any:
    """`gh api` 封装：-X method + 可选 -f 字段 + 可选 --paginate。

    返回解析后的 JSON（dict/list），空响应返回 None；任何失败抛 BootstrapError。
    """
    ensure_gh()
    cmd = ["gh", "api", "-X", method]
    if paginate:
        cmd.append("--paginate")
    for key, value in (fields or {}).items():
        cmd.extend(["-f", f"{key}={value}"])
    cmd.append(endpoint)
    res = run(cmd, check=False)
    if res.returncode != 0:
        raise BootstrapError(f"gh api {method} {endpoint} 失败: {res.stderr.strip()}")
    if not res.stdout.strip():
        return None
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return res.stdout


def gh_json(args: List[str], *, cwd: Optional[object] = None) -> Any:
    """执行带 --json 的 gh 子命令并解析 JSON 输出。"""
    ensure_gh()
    res = run(["gh", *args], cwd=cwd, check=False)
    if res.returncode != 0:
        raise BootstrapError(f"gh {' '.join(args)} 失败: {res.stderr.strip()}")
    if not res.stdout.strip():
        return None
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        raise BootstrapError(f"gh {' '.join(args)} 输出不是 JSON: {res.stdout[:200]}")
