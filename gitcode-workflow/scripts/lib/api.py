"""GitCode API v5 client — authentication, user profile, keys, repository creation."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib import error, request
from urllib.parse import urlparse

from .common import BootstrapError, log_info
from .config import require_token


def api_request(
    api_base: str,
    method: str,
    endpoint: str,
    token: str,
    payload: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, str]] = None,
) -> Any:
    url = api_base.rstrip("/") + endpoint
    if query:
        query_str = "&".join(f"{k}={v}" for k, v in query.items() if v is not None)
        if query_str:
            url += "?" + query_str
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json;charset=UTF-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["PRIVATE-TOKEN"] = token
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise BootstrapError(f"GitCode API error {exc.code}: {body}") from exc


def gitcode_profile(config: Dict[str, Any]) -> Dict[str, Any]:
    return api_request(
        config["gitcode"]["api_base"], "GET", "/user", require_token(config)
    )


def gitcode_keys(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = api_request(
        config["gitcode"]["api_base"], "GET", "/user/keys", require_token(config)
    )
    return result or []


def sanitize_repo_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-")
    if not cleaned:
        raise BootstrapError("repository name cannot be empty")
    return cleaned


def create_remote_repo(
    project: Path,
    config: Dict[str, Any],
    repo_name: Optional[str],
    description: Optional[str],
    private: bool,
) -> Dict[str, Any]:
    profile = gitcode_profile(config)
    namespace = config["gitcode"].get("namespace") or profile.get("login")
    if not namespace:
        raise BootstrapError("could not determine gitcode namespace from config or /user profile")
    name = sanitize_repo_name(repo_name or project.name)
    payload = {
        "name": name,
        "path": name,
        "description": description or "",
        "private": private,
        "auto_init": False,
        "default_branch": config["git"]["default_branch"],
        "has_issues": True,
        "has_wiki": True,
    }
    repo = api_request(
        config["gitcode"]["api_base"], "POST", "/user/repos",
        require_token(config), payload=payload,
    )
    ssh_url = repo.get("ssh_url_to_repo") or f"git@gitcode.com:{namespace}/{name}.git"
    web_url = repo.get("web_url") or f"https://gitcode.com/{namespace}/{name}"
    return {
        "namespace": namespace,
        "repo_name": name,
        "private": private,
        "ssh_url": ssh_url,
        "web_url": web_url,
        "response": repo,
    }


# ── remote URL validation ──────────────────────────────────────────────

def normalize_allowed_hosts(config: Dict[str, Any]) -> List[str]:
    hosts = config.get("remote_validation", {}).get("allowed_hosts", [])
    if isinstance(hosts, str):
        hosts = [hosts]
    normalized = [str(host).strip().lower() for host in hosts if str(host).strip()]
    return normalized or ["gitcode.com"]


def parse_remote_host(url: str) -> Optional[str]:
    target = (url or "").strip()
    if not target:
        return None
    if "://" in target:
        parsed = urlparse(target)
        if parsed.hostname:
            return parsed.hostname.lower()
    if "@" in target and ":" in target:
        right = target.split("@", 1)[1]
        host = right.split(":", 1)[0].split("/", 1)[0].strip()
        return host.lower() if host else None
    if ":" in target and "/" in target:
        host = target.split(":", 1)[0].strip()
        if "." in host:
            return host.lower()
    return None


def host_matches_allowed(host: str, allowed_hosts: Sequence[str]) -> bool:
    host = host.lower().strip()
    for allowed in allowed_hosts:
        normalized = allowed.lower().strip()
        if host == normalized or host.endswith("." + normalized):
            return True
    return False


def remote_url_is_allowed(url: str, config: Dict[str, Any]) -> bool:
    host = parse_remote_host(url)
    if not host:
        return False
    return host_matches_allowed(host, normalize_allowed_hosts(config))


def validate_remote_url(url: str, config: Dict[str, Any], context: str) -> None:
    validation = config.get("remote_validation", {})
    if not bool(validation.get("enabled", True)):
        log_info(f"remote validation disabled; skip validation for {context}")
        return
    allowed_hosts = normalize_allowed_hosts(config)
    host = parse_remote_host(url)
    if not host:
        raise BootstrapError(f"cannot parse remote host in {context}: {url}")
    if not host_matches_allowed(host, allowed_hosts):
        raise BootstrapError(
            f"remote URL host '{host}' is not allowed for {context}; "
            f"allowed hosts: {', '.join(allowed_hosts)}"
        )
    log_info(f"validated remote host '{host}' for {context}")


# ── repository info ────────────────────────────────────────────────────

def get_repo_info(
    config: Dict[str, Any], namespace: str, repo_name: str
) -> Dict[str, Any]:
    """GET /repos/{owner}/{repo} — repository metadata including visibility and wiki status."""
    return api_request(
        config["gitcode"]["api_base"], "GET",
        f"/repos/{namespace}/{repo_name}",
        require_token(config),
    )
