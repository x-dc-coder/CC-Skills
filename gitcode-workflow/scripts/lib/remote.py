"""Remote repository orchestration — create, validate, connect."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .api import (
    create_remote_repo,
    remote_url_is_allowed,
    validate_remote_url,
)
from .git import configure_remote, list_remotes, run
from .ssh_key import ensure_ssh_available, ensure_ssh_key


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
    # 1. already have named remote
    desired = next(
        (item for item in remotes if item["name"] == desired_remote), None
    )
    if desired:
        validate_remote_url(desired["url"], config, f"remote '{desired_remote}'")
        run(
            ["git", "config", "remote.pushDefault", desired_remote],
            cwd=project, check=False,
        )
        return {
            "remote_name": desired_remote,
            "url": desired["url"],
            "action": "reused_named_remote",
            "created": False,
        }
    # 2. reuse any existing allowed remote
    existing_allowed = next(
        (item for item in remotes if remote_url_is_allowed(item["url"], config)),
        None,
    )
    if existing_allowed:
        validate_remote_url(
            existing_allowed["url"], config, f"remote '{existing_allowed['name']}'"
        )
        run(
            ["git", "config", "remote.pushDefault", existing_allowed["name"]],
            cwd=project, check=False,
        )
        return {
            "remote_name": existing_allowed["name"],
            "url": existing_allowed["url"],
            "action": "reused_existing_allowed_remote",
            "created": False,
        }
    # 3. create new remote on GitCode
    ensure_ssh_available()
    ssh_state = ensure_ssh_key(config)
    repo_state = create_remote_repo(project, config, repo_name, description, private)
    validate_remote_url(repo_state["ssh_url"], config, "newly created remote")
    remote_state = configure_remote(project, desired_remote, repo_state["ssh_url"])
    remote_state.update({
        "created": True,
        "web_url": repo_state["web_url"],
        "ssh": ssh_state,
        "repo": repo_state,
    })
    return remote_state
