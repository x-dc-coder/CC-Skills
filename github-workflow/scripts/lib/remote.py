"""Remote orchestration —— 经 gh CLI 在 GitHub 上创建并连接远端。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .common import BootstrapError, log_info
from .gh import require_login
from .git import list_remotes, run


def remote_url_is_allowed(url: str) -> bool:
    return "github.com" in url


def _set_push_default(project: Path, remote_name: str) -> None:
    """设置 remote.pushDefault；9p/drvfs 挂载下 config 写锁可能失败，容忍之。"""
    res = run(["git", "config", "remote.pushDefault", remote_name], cwd=project, check=False)
    if res.returncode != 0:
        log_info(
            f"warning: 无法写入 remote.pushDefault "
            f"(9p 挂载 config 写锁受限): {res.stderr.strip()}"
        )


def ensure_remote_exists(
    project: Path,
    config: Dict[str, Any],
    repo_name: Optional[str],
    description: Optional[str],
    private: bool,
    remote_name: Optional[str],
) -> Dict[str, Any]:
    desired_remote = remote_name or config["git"]["remote_name"]
    remotes = list_remotes(project)

    # 1) 已存在同名 remote
    desired = next((r for r in remotes if r["name"] == desired_remote), None)
    if desired:
        if not remote_url_is_allowed(desired["url"]):
            raise BootstrapError(
                f"remote '{desired_remote}' 指向 {desired['url']}，不是 GitHub。"
                "请先用 git remote set-url 切换到 GitHub，或换一个 remote 名。"
            )
        _set_push_default(project, desired_remote)
        return {"remote_name": desired_remote, "url": desired["url"],
                "action": "reused_named_remote", "created": False}

    # 2) 复用任意已存在的 GitHub remote
    existing = next((r for r in remotes if remote_url_is_allowed(r["url"])), None)
    if existing:
        _set_push_default(project, existing["name"])
        return {"remote_name": existing["name"], "url": existing["url"],
                "action": "reused_existing_allowed_remote", "created": False}

    # 3) 经 gh 创建 GitHub 仓库并连接（不推送；推送由 publish 完成）
    owner = require_login()
    name = repo_name or project.name
    visibility = "--private" if private else "--public"
    cmd = ["gh", "repo", "create", f"{owner}/{name}", visibility,
           "--source", str(project), "--remote", desired_remote]
    if description:
        cmd += ["--description", description]
    res = run(cmd, cwd=project, check=False)
    if res.returncode != 0:
        raise BootstrapError(f"gh repo create 失败: {res.stderr.strip()}")
    web_url = res.stdout.strip()
    _set_push_default(project, desired_remote)
    return {
        "remote_name": desired_remote,
        "url": run(["git", "remote", "get-url", desired_remote], cwd=project, check=False).stdout.strip(),
        "action": "created",
        "created": True,
        "web_url": web_url,
    }
