"""Configuration loading with file / env / CLI precedence."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .common import deep_copy, deep_merge, expand_path, read_json_file

DEFAULT_CONFIG_PATH = Path("~/.config/gitcode-workflow/config.json").expanduser()

DEFAULTS: Dict[str, Any] = {
    "git": {
        "user_name": "x-dc-coder",
        "user_email": "x.dc0521@gmail.com",
        "config_scope": "local",
        "default_branch": "master",
        "commit_rules_path": "docs/rules/Git-Commit.md",
        "remote_name": "gitcode",
    },
    "gitcode": {
        "api_base": "https://api.gitcode.com/api/v5",
        "token_env_name": "GITCODE_TOKEN",
        "namespace": "",
        "default_private": True,
    },
    "ssh": {
        "private_key_path": "~/.ssh/gitcode_wsl_ed25519",
        "public_key_path": "~/.ssh/gitcode_wsl_ed25519.pub",
        "title": "wsl-ubuntu-gitcode",
        "comment": "x.dc0521@gmail.com",
    },
    "safety": {
        "auto_update_gitignore": True,
        "auto_update_info_exclude": True,
        "abort_on_high_risk": True,
    },
    "remote_validation": {
        "enabled": True,
        "allowed_hosts": ["gitcode.com"],
    },
}

ENV_MAPPING = {
    ("git", "user_name"): "GITCODE_USER_NAME",
    ("git", "user_email"): "GITCODE_USER_EMAIL",
    ("git", "config_scope"): "GITCODE_CONFIG_SCOPE",
    ("git", "default_branch"): "GITCODE_DEFAULT_BRANCH",
    ("git", "commit_rules_path"): "GITCODE_COMMIT_RULES_PATH",
    ("git", "remote_name"): "GITCODE_REMOTE_NAME",
    ("gitcode", "token"): "GITCODE_TOKEN",
    ("gitcode", "token_env_name"): "GITCODE_TOKEN_ENV_NAME",
    ("gitcode", "namespace"): "GITCODE_NAMESPACE",
    ("ssh", "private_key_path"): "GITCODE_SSH_PRIVATE_KEY_PATH",
    ("ssh", "public_key_path"): "GITCODE_SSH_PUBLIC_KEY_PATH",
    ("ssh", "title"): "GITCODE_SSH_TITLE",
    ("ssh", "comment"): "GITCODE_SSH_COMMENT",
}


def check_sensitive_config_permissions(path: Path) -> Optional[str]:
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        return None
    if mode & 0o077:
        return f"config file {path} contains secrets or may contain secrets; consider chmod 600"
    return None


def apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    for (section, key), env_name in ENV_MAPPING.items():
        value = os.environ.get(env_name)
        if value in (None, ""):
            continue
        casted: Any = value.lower() == "true" if value.lower() in {"true", "false"} else value
        config.setdefault(section, {})[key] = casted
    token_env_name = config.get("gitcode", {}).get("token_env_name", "GITCODE_TOKEN")
    if token_env_name and token_env_name != "GITCODE_TOKEN":
        token_value = os.environ.get(token_env_name)
        if token_value:
            config.setdefault("gitcode", {})["token"] = token_value
    allowed_hosts_raw = os.environ.get("GITCODE_ALLOWED_REMOTE_HOSTS")
    if allowed_hosts_raw:
        hosts = [item.strip().lower() for item in allowed_hosts_raw.split(",") if item.strip()]
        if hosts:
            config.setdefault("remote_validation", {})["allowed_hosts"] = hosts
    remote_validation_enabled = os.environ.get("GITCODE_REMOTE_VALIDATION_ENABLED")
    if remote_validation_enabled and remote_validation_enabled.lower() in {"true", "false"}:
        config.setdefault("remote_validation", {})["enabled"] = remote_validation_enabled.lower() == "true"
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
        if file_config.get("gitcode", {}).get("token"):
            warnings.append(
                "config file contains deprecated gitcode.token; "
                "prefer environment variables and migrate this secret out of the config file"
            )
            permission_warning = check_sensitive_config_permissions(path)
            if permission_warning:
                warnings.append(permission_warning)
        if file_config.get("ssh", {}).get("private_key"):
            warnings.append("inline ssh.private_key is not supported; use ssh.private_key_path instead")
        if file_config.get("ssh", {}).get("public_key"):
            warnings.append("inline ssh.public_key is not supported; use ssh.public_key_path instead")
    apply_env_overrides(config)
    config["ssh"]["private_key_path"] = expand_path(config["ssh"]["private_key_path"])
    config["ssh"]["public_key_path"] = expand_path(config["ssh"]["public_key_path"])
    return config, used_path, warnings


def require_token(config: Dict[str, Any]) -> str:
    """Extract GitCode token from config dict, falling back to env."""
    token = config.get("gitcode", {}).get("token", "")
    if token:
        return token
    token_env_name = config.get("gitcode", {}).get("token_env_name", "GITCODE_TOKEN")
    token = os.environ.get(token_env_name, "")
    if token:
        return token
    raise RuntimeError(
        f"GitCode token not found; set {token_env_name} or place gitcode.token in the config file"
    )
