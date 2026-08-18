"""Configuration loading with file / env / CLI precedence for github-workflow.

设计原则：GitHub 认证统一走官方 gh CLI（不再需要 token/SSH 密钥配置），
本配置只保留 git 身份、默认 remote 名与安全策略等本地偏好。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .common import deep_copy, deep_merge, read_json_file

DEFAULT_CONFIG_PATH = Path("~/.config/github-workflow/config.json").expanduser()

DEFAULTS: Dict[str, Any] = {
    "git": {
        "user_name": "x-dc-coder",
        "user_email": "x.dc0521@gmail.com",
        "config_scope": "local",
        "default_branch": "master",
        "commit_rules_path": "docs/rules/Git-Commit.md",
        "remote_name": "origin",
    },
    "github": {
        "hostname": "github.com",
        "default_private": True,
    },
    "safety": {
        "auto_update_gitignore": True,
        "auto_update_info_exclude": True,
        "abort_on_high_risk": True,
    },
    "remote_validation": {
        "enabled": True,
        "allowed_hosts": ["github.com"],
    },
}

ENV_MAPPING = {
    ("git", "user_name"): "GITHUB_USER_NAME",
    ("git", "user_email"): "GITHUB_USER_EMAIL",
    ("git", "config_scope"): "GITHUB_CONFIG_SCOPE",
    ("git", "default_branch"): "GITHUB_DEFAULT_BRANCH",
    ("git", "commit_rules_path"): "GITHUB_COMMIT_RULES_PATH",
    ("git", "remote_name"): "GITHUB_REMOTE_NAME",
    ("github", "hostname"): "GITHUB_HOSTNAME",
    ("github", "default_private"): "GITHUB_DEFAULT_PRIVATE",
}


def apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    for (section, key), env_name in ENV_MAPPING.items():
        value = os.environ.get(env_name)
        if value in (None, ""):
            continue
        casted: Any = value.lower() == "true" if value.lower() in {"true", "false"} else value
        config.setdefault(section, {})[key] = casted
    allowed_hosts_raw = os.environ.get("GITHUB_ALLOWED_REMOTE_HOSTS")
    if allowed_hosts_raw:
        hosts = [item.strip().lower() for item in allowed_hosts_raw.split(",") if item.strip()]
        if hosts:
            config.setdefault("remote_validation", {})["allowed_hosts"] = hosts
    return config


def load_config(config_path: Optional[str]) -> Tuple[Dict[str, Any], str, List[str]]:
    """Load merged config.  Returns (config, path_used, warnings)."""
    warnings: List[str] = []
    config = deep_copy(DEFAULTS)
    used_path = str(DEFAULT_CONFIG_PATH)
    path = Path(config_path).expanduser() if config_path else DEFAULT_CONFIG_PATH
    if path.exists():
        file_config = read_json_file(path)
        deep_merge(config, file_config)
        used_path = str(path)
        if file_config.get("gitcode"):
            warnings.append(
                "检测到旧版 gitcode 配置段：github-workflow 已不使用 GitCode，"
                "GitHub 认证统一走 gh CLI；可删除 config 中的 gitcode 段"
            )
    apply_env_overrides(config)
    return config, used_path, warnings
