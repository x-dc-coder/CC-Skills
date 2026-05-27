#!/usr/bin/env python3
"""Bootstrap local git projects, plan layered commits, and optional GitCode remotes safely."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from collections import Counter, defaultdict
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib import error, request
from urllib.parse import urlparse
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
BUNDLED_COMMIT_RULES = SKILL_ROOT / "references" / "commit-rules.md"
DEFAULT_CONFIG_PATH = Path("~/.config/gitcode-workflow/config.json").expanduser()
PREVIEW_MAX_DIFF_LINES = 220
PREVIEW_MAX_DIFF_CHARS = 16000
PREVIEW_MAX_NEW_FILE_BYTES = 32768
PREVIEW_MAX_NEW_FILE_LINES = 80
VALID_COMMIT_TYPES = {"feat", "fix", "docs", "style", "refactor", "perf", "test", "chore", "revert"}
DOC_SUFFIXES = {".md", ".rst", ".txt", ".adoc"}
SOURCE_SUFFIXES = {".java", ".kt", ".py", ".go", ".js", ".jsx", ".ts", ".tsx", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs"}
SCOPE_SKIP_PARTS = {
    "src", "main", "test", "tests", "java", "kotlin", "python", "go", "pkg", "cmd", "internal", "app", "apps",
    "service", "services", "module", "modules", "backend", "frontend", "server", "client", "web", "resources", "static",
    "templates", "docs", "doc", "com", "org", "net", "io", "github", "gitlab",
}
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

GENERIC_GITIGNORE_PATTERNS = [".DS_Store", "Thumbs.db", ".idea/", ".vscode/", "*.log", "logs/"]
STACK_GITIGNORE_PATTERNS = {
    "springboot": ["target/", "build/", ".gradle/", "*.class", "out/"],
    "python": ["__pycache__/", "*.py[cod]", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/", ".venv/", "venv/", ".coverage", "dist/", "*.egg-info/"],
    "go": ["bin/", "coverage.out", "*.coverprofile", "*.test"],
}
LOCAL_EXCLUDE_PATTERNS = [
    ".env", ".env.*", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.pem", "*id_ed25519*", "*id_rsa*",
    "application-local.yml", "application-local.yaml", "application-dev.yml", "application-dev.yaml", "application-prod.yml", "application-prod.yaml",
    "application-local.properties", "application-dev.properties", "application-prod.properties", "secrets*.json", "credentials*.json", "service-account*.json",
]
HIGH_RISK_PATTERNS = [".env", ".env.*", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.pem", "*id_ed25519*", "*id_rsa*", "secrets*.json", "credentials*.json", "service-account*.json"]
WARNING_PATTERNS = [
    "application-local.yml", "application-local.yaml", "application-dev.yml", "application-dev.yaml", "application-prod.yml", "application-prod.yaml",
    "application-local.properties", "application-dev.properties", "application-prod.properties",
]
IGNORE_BLOCK_HEADER = "# gitcode-workflow shared ignore rules"
EXCLUDE_BLOCK_HEADER = "# gitcode-workflow local-only exclude rules"
COMMIT_MESSAGE_RE = re.compile(r"^(feat|fix|docs|style|refactor|perf|test|chore|revert)(\([^)]+\))?: (.+)$")
REVIEW_MANIFEST_FILENAME = "gitcode-workflow-review.json"


class BootstrapError(RuntimeError):
    pass


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


def deep_copy(obj: Any) -> Any:
    return json.loads(json.dumps(obj))


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def read_json_file(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


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


def expand_path(value: str) -> str:
    return str(Path(value).expanduser())


def load_config(config_path: Optional[str]) -> Tuple[Dict[str, Any], str, List[str]]:
    warnings: List[str] = []
    config = deep_copy(DEFAULTS)
    used_path = str(DEFAULT_CONFIG_PATH)
    path = Path(config_path).expanduser() if config_path else DEFAULT_CONFIG_PATH
    if path.exists():
        file_config = read_json_file(path)
        deep_merge(config, file_config)
        used_path = str(path)
        if file_config.get("gitcode", {}).get("token"):
            warnings.append("config file contains deprecated gitcode.token; prefer environment variables and migrate this secret out of the config file")
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


def run(cmd: Sequence[str], cwd: Optional[Path] = None, check: bool = True) -> CommandResult:
    proc = subprocess.run(list(cmd), cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)
    result = CommandResult(proc.stdout.rstrip("\n"), proc.stderr.rstrip("\n"), proc.returncode)
    if check and proc.returncode != 0:
        raise BootstrapError(f"command failed ({proc.returncode}): {' '.join(cmd)}\nstdout: {result.stdout}\nstderr: {result.stderr}")
    return result


def log_info(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[gitcode-workflow][{timestamp}] {message}", file=sys.stderr)


def ensure_git_available() -> None:
    if shutil.which("git") is None:
        raise BootstrapError("git is not installed or not available in PATH")


def ensure_ssh_available() -> None:
    if shutil.which("ssh") is None:
        raise BootstrapError("ssh must be available in PATH for ssh-based git pushes")


def generate_ed25519_keypair(private_key: Path, public_key: Path, comment: str) -> None:
    private = ed25519.Ed25519PrivateKey.generate()
    private_bytes = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    private_key.parent.mkdir(parents=True, exist_ok=True)
    private_key.write_bytes(private_bytes)
    public_key.write_text(public_bytes.decode("utf-8") + f" {comment}\n", encoding="utf-8")
    os.chmod(private_key, 0o600)
    os.chmod(public_key, 0o644)


def is_git_repo(project: Path) -> bool:
    return (project / ".git").exists()


def init_repo(project: Path, default_branch: str) -> bool:
    if is_git_repo(project):
        return False
    project.mkdir(parents=True, exist_ok=True)
    init_with_branch = run(["git", "init", "-b", default_branch], cwd=project, check=False)
    if init_with_branch.returncode != 0:
        run(["git", "init"], cwd=project, check=True)
        run(["git", "checkout", "-b", default_branch], cwd=project, check=False)
    return True


def repo_has_commits(project: Path) -> bool:
    return run(["git", "rev-parse", "--verify", "HEAD"], cwd=project, check=False).returncode == 0


def set_git_identity(project: Path, scope: str, user_name: str, user_email: str) -> Dict[str, str]:
    target = ["git", "config"]
    cwd: Optional[Path] = project
    if scope == "global":
        target.append("--global")
        cwd = None
    run(target + ["user.name", user_name], cwd=cwd, check=True)
    run(target + ["user.email", user_email], cwd=cwd, check=True)
    return {"scope": scope, "user_name": user_name, "user_email": user_email}


def detect_stacks(project: Path) -> List[str]:
    stacks: List[str] = []
    if any((project / name).exists() for name in ["pom.xml", "build.gradle", "build.gradle.kts"]):
        stacks.append("springboot")
    if any((project / name).exists() for name in ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile"]):
        stacks.append("python")
    if (project / "go.mod").exists():
        stacks.append("go")
    return stacks


def ensure_lines(path: Path, header: str, lines: Sequence[str]) -> List[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    added: List[str] = []
    new_content = existing.rstrip("\n")
    existing_lines = existing.splitlines()
    if header not in existing:
        if new_content:
            new_content += "\n\n"
        new_content += header + "\n"
    for line in lines:
        if line not in existing_lines:
            new_content += line + "\n"
            added.append(line)
    if added or (header not in existing and not added):
        path.write_text(new_content.rstrip("\n") + "\n", encoding="utf-8")
    return added


def update_gitignore(project: Path, stacks: Sequence[str], enabled: bool) -> Dict[str, Any]:
    path = project / ".gitignore"
    if not enabled:
        return {"path": str(path), "added": [], "enabled": False}
    lines: List[str] = []
    for pattern in GENERIC_GITIGNORE_PATTERNS:
        if pattern not in lines:
            lines.append(pattern)
    for stack in stacks:
        for pattern in STACK_GITIGNORE_PATTERNS.get(stack, []):
            if pattern not in lines:
                lines.append(pattern)
    return {"path": str(path), "added": ensure_lines(path, IGNORE_BLOCK_HEADER, lines), "enabled": True}


def update_info_exclude(project: Path, enabled: bool) -> Dict[str, Any]:
    path = project / ".git" / "info" / "exclude"
    if not enabled:
        return {"path": str(path), "added": [], "enabled": False}
    return {"path": str(path), "added": ensure_lines(path, EXCLUDE_BLOCK_HEADER, LOCAL_EXCLUDE_PATTERNS), "enabled": True}


def resolve_commit_rules(project: Path, relative_path: str) -> Dict[str, str]:
    candidate = project / relative_path
    if candidate.exists():
        return {"source": "project", "path": str(candidate)}
    return {"source": "bundled", "path": str(BUNDLED_COMMIT_RULES)}


def gitignore_match(project: Path, path: Path) -> bool:
    rel = str(path.relative_to(project))
    return run(["git", "check-ignore", rel], cwd=project, check=False).returncode == 0


def walk_project_files(project: Path) -> Iterable[Path]:
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d != ".git"]
        root_path = Path(root)
        for name in files:
            yield root_path / name


def classify_sensitive_files(project: Path) -> Dict[str, List[str]]:
    high_risk: List[str] = []
    warnings: List[str] = []
    for file_path in walk_project_files(project):
        rel = str(file_path.relative_to(project))
        for pattern in HIGH_RISK_PATTERNS:
            if fnmatch(rel, pattern) or fnmatch(file_path.name, pattern):
                if is_git_repo(project):
                    if not gitignore_match(project, file_path):
                        high_risk.append(rel)
                else:
                    high_risk.append(rel)
                break
        for pattern in WARNING_PATTERNS:
            if fnmatch(rel, pattern) or fnmatch(file_path.name, pattern):
                if is_git_repo(project):
                    if not gitignore_match(project, file_path):
                        warnings.append(rel)
                else:
                    warnings.append(rel)
                break
    return {"high_risk": sorted(set(high_risk)), "warnings": sorted(set(warnings))}


def repo_current_branch(project: Path) -> str:
    result = run(["git", "branch", "--show-current"], cwd=project, check=False)
    branch = result.stdout.strip()
    return branch or DEFAULTS["git"]["default_branch"]


def api_request(api_base: str, method: str, endpoint: str, token: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    url = api_base.rstrip("/") + endpoint
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


def require_token(config: Dict[str, Any]) -> str:
    token = config.get("gitcode", {}).get("token", "")
    if token:
        return token
    token_env_name = config.get("gitcode", {}).get("token_env_name", "GITCODE_TOKEN")
    token = os.environ.get(token_env_name, "")
    if token:
        return token
    raise BootstrapError(f"GitCode token not found; set {token_env_name} or place gitcode.token in the config file")


def gitcode_profile(config: Dict[str, Any]) -> Dict[str, Any]:
    return api_request(config["gitcode"]["api_base"], "GET", "/user", require_token(config))


def gitcode_keys(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = api_request(config["gitcode"]["api_base"], "GET", "/user/keys", require_token(config))
    return result or []


def ensure_ssh_key(config: Dict[str, Any]) -> Dict[str, Any]:
    private_key = Path(config["ssh"]["private_key_path"]).expanduser()
    public_key = Path(config["ssh"]["public_key_path"]).expanduser()
    title = config["ssh"]["title"]
    comment = config["ssh"]["comment"]
    created = False
    generation_method = "existing"
    if not private_key.exists() or not public_key.exists():
        if shutil.which("ssh-keygen"):
            private_key.parent.mkdir(parents=True, exist_ok=True)
            run(["ssh-keygen", "-t", "ed25519", "-C", comment, "-f", str(private_key), "-N", ""], check=True)
            os.chmod(private_key, 0o600)
            if public_key.exists():
                os.chmod(public_key, 0o644)
            generation_method = "ssh-keygen"
        else:
            generate_ed25519_keypair(private_key, public_key, comment)
            generation_method = "python-cryptography"
        created = True
    public_value = public_key.read_text(encoding="utf-8").strip()
    existing = next((item for item in gitcode_keys(config) if item.get("key", "").strip() == public_value), None)
    uploaded = False
    key_id = existing.get("id") if existing else None
    if existing is None:
        created_key = api_request(config["gitcode"]["api_base"], "POST", "/user/keys", require_token(config), {"key": public_value, "title": title})
        key_id = created_key.get("id")
        uploaded = True
    return {"private_key_path": str(private_key), "public_key_path": str(public_key), "title": title, "created_locally": created, "generation_method": generation_method, "uploaded_to_gitcode": uploaded, "public_key_id": key_id}


def sanitize_repo_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-")
    if not cleaned:
        raise BootstrapError("repository name cannot be empty")
    return cleaned


def create_remote_repo(project: Path, config: Dict[str, Any], repo_name: Optional[str], description: Optional[str], private: bool) -> Dict[str, Any]:
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
        # GitCode /user/repos currently rejects payloads containing `public`.
        # Visibility is controlled by `private` only.
        "auto_init": False,
        "default_branch": config["git"]["default_branch"],
        "has_issues": True,
        "has_wiki": True,
    }
    repo = api_request(config["gitcode"]["api_base"], "POST", "/user/repos", require_token(config), payload)
    ssh_url = repo.get("ssh_url_to_repo") or f"git@gitcode.com:{namespace}/{name}.git"
    web_url = repo.get("web_url") or f"https://gitcode.com/{namespace}/{name}"
    return {"namespace": namespace, "repo_name": name, "private": private, "ssh_url": ssh_url, "web_url": web_url, "response": repo}


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
            f"remote URL host '{host}' is not allowed for {context}; allowed hosts: {', '.join(allowed_hosts)}"
        )
    log_info(f"validated remote host '{host}' for {context}")


def list_remotes(project: Path) -> List[Dict[str, str]]:
    result = run(["git", "remote"], cwd=project, check=False)
    remotes: List[Dict[str, str]] = []
    for name in [line.strip() for line in result.stdout.splitlines() if line.strip()]:
        url = run(["git", "remote", "get-url", name], cwd=project, check=False).stdout.strip()
        remotes.append({"name": name, "url": url})
    return remotes


def configure_remote(project: Path, desired_name: str, url: str) -> Dict[str, Any]:
    remotes = list_remotes(project)
    existing_names = [item["name"] for item in remotes]
    remote_name = desired_name
    action = "added"
    if remote_name in existing_names:
        current_url = next(item["url"] for item in remotes if item["name"] == remote_name)
        if current_url == url:
            action = "unchanged"
        else:
            fallback = "gitcode" if remote_name != "gitcode" and "gitcode" not in existing_names else f"{remote_name}-alt"
            remote_name = fallback
            run(["git", "remote", "add", remote_name, url], cwd=project, check=True)
            action = "added_fallback"
    else:
        run(["git", "remote", "add", remote_name, url], cwd=project, check=True)
    run(["git", "config", "remote.pushDefault", remote_name], cwd=project, check=False)
    return {"remote_name": remote_name, "url": url, "action": action}


def ensure_remote_exists(project: Path, config: Dict[str, Any], repo_name: Optional[str], description: Optional[str], private: bool, remote_name: Optional[str]) -> Dict[str, Any]:
    desired_remote = remote_name or config["git"]["remote_name"]
    remotes = list_remotes(project)
    desired = next((item for item in remotes if item["name"] == desired_remote), None)
    if desired:
        validate_remote_url(desired["url"], config, f"remote '{desired_remote}'")
        run(["git", "config", "remote.pushDefault", desired_remote], cwd=project, check=False)
        return {"remote_name": desired_remote, "url": desired["url"], "action": "reused_named_remote", "created": False}
    existing_allowed = next((item for item in remotes if remote_url_is_allowed(item["url"], config)), None)
    if existing_allowed:
        validate_remote_url(existing_allowed["url"], config, f"remote '{existing_allowed['name']}'")
        run(["git", "config", "remote.pushDefault", existing_allowed["name"]], cwd=project, check=False)
        return {"remote_name": existing_allowed["name"], "url": existing_allowed["url"], "action": "reused_existing_allowed_remote", "created": False}
    ensure_ssh_available()
    ssh_state = ensure_ssh_key(config)
    repo_state = create_remote_repo(project, config, repo_name, description, private)
    validate_remote_url(repo_state["ssh_url"], config, "newly created remote")
    remote_state = configure_remote(project, desired_remote, repo_state["ssh_url"])
    remote_state.update({"created": True, "web_url": repo_state["web_url"], "ssh": ssh_state, "repo": repo_state})
    return remote_state


def parse_status_line(line: str) -> Dict[str, Any]:
    if line.startswith("?? "):
        return {"raw": line, "path": line[3:], "old_path": None, "index_status": "?", "worktree_status": "?", "kind": "untracked", "staged": False, "unstaged": True}
    index_status, worktree_status = line[0], line[1]
    path_blob = line[3:]
    old_path = None
    path = path_blob
    if " -> " in path_blob:
        old_path, path = path_blob.split(" -> ", 1)
    if "R" in {index_status, worktree_status}:
        kind = "renamed"
    elif "D" in {index_status, worktree_status}:
        kind = "deleted"
    elif "A" in {index_status, worktree_status}:
        kind = "added"
    elif "C" in {index_status, worktree_status}:
        kind = "copied"
    elif "U" in {index_status, worktree_status}:
        kind = "unmerged"
    elif "M" in {index_status, worktree_status}:
        kind = "modified"
    else:
        kind = "changed"
    return {"raw": line, "path": path, "old_path": old_path, "index_status": index_status, "worktree_status": worktree_status, "kind": kind, "staged": index_status not in {" ", "?"}, "unstaged": worktree_status not in {" ", "?"}}


def collect_status_entries(project: Path) -> List[Dict[str, Any]]:
    lines = run(["git", "status", "--short", "--untracked-files=all"], cwd=project, check=False).stdout.splitlines()
    return [parse_status_line(line) for line in lines if line.strip()]


def build_status_counts(entries: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for entry in entries:
        counts[entry["kind"]] += 1
        if entry["staged"]:
            counts["staged"] += 1
        if entry["unstaged"]:
            counts["unstaged"] += 1
    counts["total"] = len(entries)
    return dict(counts)


def group_paths_by_kind(entries: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {"added": [], "modified": [], "deleted": [], "renamed": [], "copied": [], "untracked": [], "changed": [], "unmerged": []}
    for entry in entries:
        display_path = entry["path"]
        if entry.get("old_path"):
            display_path = f"{entry['old_path']} -> {entry['path']}"
        grouped.setdefault(entry["kind"], []).append(display_path)
    return {key: value for key, value in grouped.items() if value}


def file_is_text(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
    except (FileNotFoundError, OSError):
        return False
    return b"\x00" not in chunk


def truncate_text(text: str, max_lines: int = PREVIEW_MAX_DIFF_LINES, max_chars: int = PREVIEW_MAX_DIFF_CHARS) -> Tuple[str, bool]:
    lines = text.splitlines()
    truncated = False
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    joined = "\n".join(lines)
    if len(joined) > max_chars:
        joined = joined[:max_chars]
        if "\n" in joined:
            joined = joined.rsplit("\n", 1)[0]
        truncated = True
    if truncated:
        joined = joined.rstrip("\n") + "\n...[truncated]"
    return joined, truncated


def preview_new_file(project: Path, relative_path: str) -> str:
    path = project / relative_path
    lower_rel = relative_path.replace(chr(92), "/").lower()
    if lower_rel.endswith("docs/rules/git-commit.md") or lower_rel.endswith("git-commit.md"):
        return f"### untracked file: {relative_path}\npreview omitted because commit-rule files are summarized separately"
    if not path.exists():
        return f"### missing path: {relative_path}"
    if path.stat().st_size > PREVIEW_MAX_NEW_FILE_BYTES:
        return f"### untracked file: {relative_path}\npreview omitted because the file is larger than {PREVIEW_MAX_NEW_FILE_BYTES} bytes"
    if not file_is_text(path):
        return f"### untracked file: {relative_path}\npreview omitted because the file looks binary"
    diff = run(["git", "diff", "--no-index", "--no-color", "--unified=1", "--", "/dev/null", relative_path], cwd=project, check=False).stdout
    if diff.strip():
        diff, _ = truncate_text(diff.strip(), max_lines=60, max_chars=4000)
        return diff.strip()
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()[:PREVIEW_MAX_NEW_FILE_LINES]
    return f"### untracked file: {relative_path}\n" + "\n".join(lines)


def infer_scope_from_path(path: str) -> str:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    if name in {"pom.xml", "build.gradle", "build.gradle.kts", "requirements.txt", "pyproject.toml", "setup.py", "poetry.lock", "go.mod", "go.sum", "package.json", "package-lock.json", "pnpm-lock.yaml"}:
        return "deps"
    if name in {"dockerfile", "makefile", ".gitignore", ".gitattributes"}:
        return "repo"
    parts = []
    for part in pure.parts[:-1]:
        lower = part.lower()
        if lower in SCOPE_SKIP_PARTS or lower.startswith("."):
            continue
        parts.append(lower)
    if parts:
        scope = re.sub(r"[^a-z0-9-]+", "-", parts[-1]).strip("-")
        if scope:
            return scope
    stem = re.sub(r"[^a-z0-9-]+", "-", pure.stem.lower()).strip("-")
    if stem in {"readme", "license", "git-commit", "main", "index"}:
        return "global"
    return stem or "global"


def infer_scope_hints(entries: Sequence[Dict[str, Any]]) -> List[str]:
    counter: Counter[str] = Counter()
    for entry in entries:
        counter[infer_scope_from_path(entry["path"])] += 1
    return [scope for scope, _ in counter.most_common(3)] or ["global"]


def is_doc_path(path: str) -> bool:
    pure = PurePosixPath(path)
    return pure.suffix.lower() in DOC_SUFFIXES or pure.name.lower().startswith("readme") or "docs" in {part.lower() for part in pure.parts}


def is_test_path(path: str) -> bool:
    lower = path.lower()
    name = PurePosixPath(path).name.lower()
    if any(token in lower.split("/") for token in ["test", "tests", "__tests__"]):
        return True
    return name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.go") or name.endswith(".spec.ts") or name.endswith(".spec.js")


def is_build_or_config_path(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    if name in {"pom.xml", "build.gradle", "build.gradle.kts", "requirements.txt", "pyproject.toml", "setup.py", "poetry.lock", "go.mod", "go.sum", "dockerfile", "docker-compose.yml", "docker-compose.yaml", "makefile", ".gitignore", ".gitattributes"}:
        return True
    return (pure.parts[0].lower() if pure.parts else "") in {".github", "ci", "scripts", "deploy", "ops"}


def is_source_path(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in SOURCE_SUFFIXES


def infer_type_hints(entries: Sequence[Dict[str, Any]]) -> List[str]:
    paths = [entry["path"] for entry in entries]
    if not paths:
        return []
    docs_only = all(is_doc_path(path) for path in paths)
    tests_only = all(is_test_path(path) for path in paths)
    build_only = all(is_build_or_config_path(path) for path in paths)
    added_source = any(entry["kind"] in {"added", "untracked"} and is_source_path(entry["path"]) for entry in entries)
    removed_or_renamed = any(entry["kind"] in {"deleted", "renamed"} for entry in entries)
    hints: List[str] = []
    if docs_only:
        hints.extend(["docs", "chore"])
    elif tests_only:
        hints.extend(["test", "fix"])
    elif build_only:
        hints.extend(["chore", "refactor"])
    else:
        if added_source:
            hints.append("feat")
        if removed_or_renamed:
            hints.append("refactor")
        hints.extend(["fix", "refactor", "chore"])
    deduped: List[str] = []
    for hint in hints:
        if hint not in deduped:
            deduped.append(hint)
    return deduped[:4]


def build_diff_excerpt(project: Path, entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    sections: List[str] = []
    if repo_has_commits(project):
        tracked_diff = run(["git", "diff", "--no-color", "--unified=1", "--find-renames", "HEAD"], cwd=project, check=False).stdout
        if tracked_diff.strip():
            sections.append(tracked_diff.strip())
    untracked_entries = [entry for entry in entries if entry["kind"] == "untracked"]
    for entry in untracked_entries:
        sections.append(preview_new_file(project, entry["path"]))
    if not repo_has_commits(project) and not untracked_entries:
        for entry in entries:
            if entry["kind"] == "deleted":
                sections.append(f"### deleted file: {entry['path']}")
            else:
                absolute = project / entry["path"]
                if absolute.exists():
                    sections.append(preview_new_file(project, entry["path"]))
    if not sections:
        return {"text": "", "truncated": False}
    excerpt, truncated = truncate_text("\n\n".join(sections))
    return {"text": excerpt, "truncated": truncated}


def build_publish_preview(project: Path) -> Dict[str, Any]:
    entries = collect_status_entries(project)
    excerpt_state = build_diff_excerpt(project, entries)
    return {
        "has_changes": bool(entries),
        "status_lines": [entry["raw"] for entry in entries],
        "files": entries,
        "files_by_kind": group_paths_by_kind(entries),
        "counts": build_status_counts(entries),
        "scope_hints": infer_scope_hints(entries),
        "type_hints": infer_type_hints(entries),
        "diff_excerpt": excerpt_state["text"],
        "diff_excerpt_truncated": excerpt_state["truncated"],
    }


def head_commit_or_none(project: Path) -> Optional[str]:
    result = run(["git", "rev-parse", "HEAD"], cwd=project, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def review_manifest_path(project: Path, override: Optional[str]) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    return (project / ".git" / REVIEW_MANIFEST_FILENAME).resolve()


def sha256_file(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_review_manifest(project: Path, preview: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
    files = sorted(files, key=lambda item: (item.get("old_path") or "", item["path"], item["kind"], item["raw"]))
    stage_targets: List[str] = []
    seen_targets = set()
    for item in files:
        for candidate in [item.get("old_path"), item["path"]]:
            if candidate and candidate not in seen_targets:
                seen_targets.add(candidate)
                stage_targets.append(candidate)
    hash_payload = {
        "head_commit": head_commit_or_none(project),
        "status_lines": preview["status_lines"],
        "files": files,
    }
    snapshot_hash = hashlib.sha256(json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
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


def write_review_manifest(project: Path, override: Optional[str], preview: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    manifest = build_review_manifest(project, preview)
    path = review_manifest_path(project, override)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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


def verify_review_manifest(project: Path, override: Optional[str]) -> Dict[str, Any]:
    project = project.resolve()
    path = review_manifest_path(project, override)
    stored = load_review_manifest(path)
    stored_project = stored.get("project_path")
    if stored_project and Path(stored_project).expanduser().resolve() != project:
        raise BootstrapError(f"review manifest belongs to a different project: {stored_project}")
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


def validate_commit_message(message: str) -> Dict[str, Any]:
    issues: List[str] = []
    warnings: List[str] = []
    trimmed = message.strip()
    if not trimmed:
        return {"valid": False, "issues": ["commit message must not be empty"], "warnings": warnings}
    match = COMMIT_MESSAGE_RE.match(trimmed)
    if not match:
        return {"valid": False, "issues": ["commit message must match '<type>(<scope>): <subject>' and use an allowed conventional type"], "warnings": warnings}
    commit_type = match.group(1)
    subject = match.group(3).strip()
    if commit_type not in VALID_COMMIT_TYPES:
        issues.append(f"unsupported commit type: {commit_type}")
    if subject.endswith(".") or subject.endswith("。"):
        issues.append("subject must not end with punctuation")
    if len(subject) > 50:
        warnings.append("subject is longer than 50 characters")
    return {"valid": not issues, "issues": issues, "warnings": warnings}


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def preview_subject_by_type(commit_type: str, preview: Dict[str, Any], prefer_chinese: bool) -> str:
    files_by_kind = preview.get("files_by_kind", {})
    added = len(files_by_kind.get("added", [])) + len(files_by_kind.get("untracked", []))
    modified = len(files_by_kind.get("modified", []))
    deleted = len(files_by_kind.get("deleted", []))
    renamed = len(files_by_kind.get("renamed", []))
    if prefer_chinese:
        by_type = {
            "feat": "新增核心能力并完善关键流程",
            "fix": "修复关键流程中的已知问题",
            "docs": "更新文档与使用说明",
            "style": "统一代码格式与细节样式",
            "refactor": "重构代码结构并提升可维护性",
            "perf": "优化性能并减少不必要开销",
            "test": "补充测试覆盖并完善校验",
            "chore": "整理工程配置与仓库基础设置",
            "revert": "回滚存在风险的历史改动",
        }
        if commit_type == "refactor" and (deleted > 0 or renamed > 0):
            return "重构目录结构并清理历史实现"
        if commit_type == "feat" and added > 0 and modified > 0:
            return "新增功能并联动更新相关实现"
        return by_type.get(commit_type, "整理本次改动并保持仓库一致性")
    by_type_en = {
        "feat": "add core capability and align flow",
        "fix": "fix known issue in main flow",
        "docs": "update docs and usage notes",
        "style": "align formatting and style details",
        "refactor": "refactor structure for maintainability",
        "perf": "optimize runtime performance",
        "test": "add tests and validation coverage",
        "chore": "tidy repository and build config",
        "revert": "revert risky historical changes",
    }
    return by_type_en.get(commit_type, "align current repository changes")


def build_commit_message_candidates(preview: Dict[str, Any], commit_rules: Dict[str, str], limit: int = 3) -> List[str]:
    commit_rule_text = read_text_safe(Path(commit_rules.get("path", "")))
    prefer_chinese = "中文" in commit_rule_text
    hinted_types = list(preview.get("type_hints", []))
    fallback_types = ["feat", "fix", "refactor", "chore", "docs", "test"]
    ordered_types: List[str] = []
    for item in hinted_types + fallback_types:
        if item in VALID_COMMIT_TYPES and item not in ordered_types:
            ordered_types.append(item)
    scope_hints = preview.get("scope_hints", []) or ["global"]
    scope = str(scope_hints[0]).strip() if scope_hints else "global"
    if not scope:
        scope = "global"
    scope = re.sub(r"[^a-z0-9-]+", "-", scope.lower()).strip("-") or "global"

    candidates: List[str] = []
    for commit_type in ordered_types:
        subject = preview_subject_by_type(commit_type, preview, prefer_chinese=prefer_chinese)
        candidate = f"{commit_type}({scope}): {subject}"
        if candidate not in candidates:
            candidates.append(candidate)
        if len(candidates) >= limit:
            break
    while len(candidates) < limit:
        subject = "整理本次改动并保持仓库一致性" if prefer_chinese else "align current repository changes"
        fallback = f"chore({scope}): {subject}"
        if fallback not in candidates:
            candidates.append(fallback)
        else:
            candidates.append(f"refactor({scope}): {subject}")
    return candidates[:limit]


def commit_and_push(project: Path, remote_name: str, commit_message: str, review_manifest: Dict[str, Any], manifest_path: Path) -> Dict[str, Any]:
    validation = validate_commit_message(commit_message)
    if not validation["valid"]:
        raise BootstrapError("invalid commit message: " + "; ".join(validation["issues"]))
    if not review_manifest.get("files"):
        return {
            "committed": False,
            "pushed": False,
            "reason": "working tree is clean",
            "commit_message_validation": validation,
            "review_snapshot_hash": review_manifest.get("snapshot_hash"),
        }
    staged_targets = stage_review_manifest(project, review_manifest)
    run(["git", "commit", "-m", commit_message], cwd=project, check=True)
    branch = repo_current_branch(project)
    run(["git", "push", "-u", remote_name, branch], cwd=project, check=True)
    commit_hash = run(["git", "rev-parse", "HEAD"], cwd=project, check=True).stdout.strip()
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


def common_bootstrap(project: Path, config: Dict[str, Any]) -> Dict[str, Any]:
    ensure_git_available()
    project = project.resolve()
    repo_initialized = init_repo(project, config["git"]["default_branch"])
    identity = set_git_identity(project, config["git"]["config_scope"], config["git"]["user_name"], config["git"]["user_email"])
    stacks = detect_stacks(project)
    gitignore_state = update_gitignore(project, stacks, bool(config["safety"]["auto_update_gitignore"]))
    info_exclude_state = update_info_exclude(project, bool(config["safety"]["auto_update_info_exclude"]))
    commit_rules = resolve_commit_rules(project, config["git"]["commit_rules_path"])
    safety = classify_sensitive_files(project)
    return {"project_path": str(project), "repo_initialized": repo_initialized, "identity": identity, "detected_stacks": stacks, "gitignore": gitignore_state, "info_exclude": info_exclude_state, "commit_rules": commit_rules, "safety_scan": safety}


def sample_project_paths(project: Path, limit: int = 2000) -> List[str]:
    paths: List[str] = []
    for path in walk_project_files(project):
        rel = str(path.relative_to(project))
        paths.append(rel)
        if len(paths) >= limit:
            break
    return sorted(paths)


def top_level_summary(paths: Sequence[str]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for rel in paths:
        first = PurePosixPath(rel).parts[0] if PurePosixPath(rel).parts else rel
        counts[first] += 1
    return dict(counts)


def classify_path_bucket(path: str) -> str:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    first = pure.parts[0].lower() if pure.parts else ""
    if name in {"pom.xml", "build.gradle", "build.gradle.kts", "requirements.txt", "pyproject.toml", "setup.py", "go.mod", "go.sum", ".gitignore", "dockerfile", "makefile"}:
        return "bootstrap"
    if is_doc_path(path):
        return "docs"
    if is_test_path(path):
        return "tests"
    if first in {".github", "ci", "scripts", "deploy", "ops"}:
        return "ops"
    if first in {"config", "configs"} or name.startswith("application") or pure.suffix.lower() in {".yml", ".yaml", ".properties", ".toml", ".ini"}:
        return "config"
    if first in {"src", "cmd", "pkg", "internal", "app", "apps"} or is_source_path(path):
        return "source"
    return "assets"


def choose_primary_scope(paths: Sequence[str]) -> str:
    counter: Counter[str] = Counter(infer_scope_from_path(path) for path in paths)
    return counter.most_common(1)[0][0] if counter else "core"


def strategy_message(commit_type: str, scope: str, subject: str) -> str:
    return f"{commit_type}({scope}): {subject}"


def build_adoption_strategy(project: Path, config: Dict[str, Any], max_layers: int = 6) -> Dict[str, Any]:
    project = project.resolve()
    paths = sample_project_paths(project)
    stacks = detect_stacks(project)
    commit_rules = resolve_commit_rules(project, config["git"]["commit_rules_path"])
    safety = classify_sensitive_files(project)
    bucket_map: Dict[str, List[str]] = defaultdict(list)
    for rel in paths:
        bucket_map[classify_path_bucket(rel)].append(rel)
    layers: List[Dict[str, Any]] = []

    def add_layer(name: str, goal: str, include_paths: List[str], exclude_patterns: List[str], commit_type: str, subject: str) -> None:
        if not include_paths or len(layers) >= max_layers:
            return
        sample = include_paths[:12]
        scope = choose_primary_scope(include_paths)
        layers.append({
            "name": name,
            "goal": goal,
            "include_samples": sample,
            "include_count": len(include_paths),
            "exclude_patterns": exclude_patterns,
            "confidence": "medium",
            "classification_method": "heuristic path-and-filename grouping",
            "commit_candidates": [
                strategy_message(commit_type, scope, subject),
                strategy_message("chore" if commit_type != "docs" else "docs", "repo" if scope == "global" else scope, "整理现有项目并准备分层提交" if commit_type != "docs" else "完善项目文档与提交说明"),
            ],
            "manual_checks": [
                "确认本层不混入敏感配置或本地产物",
                "确认本层只覆盖一个明确主题",
                "若 scripts、ops、config 被误分层，按实际业务边界手工调整",
            ],
        })

    add_layer("bootstrap", "先提交构建声明、仓库基础文件和忽略规则", bucket_map["bootstrap"], ["业务源码", "测试代码", "本地敏感配置"], "chore", "初始化项目构建与仓库基础配置")
    add_layer("docs", "单独提交 README、接口说明和设计文档", bucket_map["docs"], ["源码实现", "测试修复"], "docs", "补充项目文档与使用说明")
    add_layer("config", "单独审查可提交的非敏感配置模板", bucket_map["config"], HIGH_RISK_PATTERNS + WARNING_PATTERNS, "chore", "整理可提交的配置模板与环境说明")
    add_layer("source", "按核心业务或公共基础设施逐层纳入源码", bucket_map["source"], ["docs/", "tests/", "*.env", "*.pem"], "feat", "纳入核心源码与基础能力实现")
    add_layer("tests", "最后补充测试与验证代码", bucket_map["tests"], ["业务重构", "本地测试数据"], "test", "补充测试用例与验证脚本")
    add_layer("ops", "最后处理部署、脚本和 CI 相关内容", bucket_map["ops"], ["业务逻辑改动"], "chore", "整理脚本与自动化配置")
    add_layer("assets", "将资源文件作为最后一层纳入，避免首提过重", bucket_map["assets"], ["大型二进制", "导出文件", "本地缓存"], "chore", "整理资源文件与辅助素材")

    recommended_order = [layer["name"] for layer in layers]
    return {
        "project_path": str(project),
        "strategy_type": "heuristic",
        "manual_review_required": True,
        "detected_stacks": stacks,
        "commit_rules": commit_rules,
        "top_level_summary": top_level_summary(paths),
        "safety_candidates": safety,
        "recommend_ignore_first": sorted(set(safety["high_risk"] + safety["warnings"]))[:30],
        "recommended_layers": layers,
        "recommended_order": recommended_order,
        "heuristic_caveats": [
            "目录名、扩展名和常见工程约定只用于提供初稿，不等同于真实业务边界",
            "scripts、ops、config、resources 等目录最容易出现误分层，提交前必须人工复核",
            "若同一目录同时包含源码、配置和部署脚本，应按真实意图继续拆层",
        ],
        "notes": [
            "该模式只输出分层提交建议，不会初始化仓库、配置远程、预览、提交或推送",
            "建议先人工确认 .gitignore 和 .git/info/exclude，再按层次逐次提交",
            "若某层包含过多目录，建议继续按模块或业务域再拆分",
        ],
    }


def apply_cli_overrides(config: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    for attr, path in [
        ("user_name", ("git", "user_name")), ("user_email", ("git", "user_email")), ("config_scope", ("git", "config_scope")),
        ("commit_rules_path", ("git", "commit_rules_path")), ("remote_name", ("git", "remote_name")), ("namespace", ("gitcode", "namespace")),
        ("ssh_title", ("ssh", "title")), ("ssh_comment", ("ssh", "comment")),
    ]:
        value = getattr(args, attr, None)
        if value:
            config[path[0]][path[1]] = value
    if getattr(args, "token", None):
        config.setdefault("gitcode", {})["token"] = args.token
    if getattr(args, "ssh_private_key_path", None):
        config["ssh"]["private_key_path"] = expand_path(args.ssh_private_key_path)
    if getattr(args, "ssh_public_key_path", None):
        config["ssh"]["public_key_path"] = expand_path(args.ssh_public_key_path)
    if getattr(args, "no_auto_gitignore", False):
        config["safety"]["auto_update_gitignore"] = False
    if getattr(args, "no_auto_info_exclude", False):
        config["safety"]["auto_update_info_exclude"] = False
    return config


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--project", default=".")
    parent.add_argument("--config", default=None)
    parent.add_argument("--json", action="store_true")
    parent.add_argument("--user-name", default=None)
    parent.add_argument("--user-email", default=None)
    parent.add_argument("--config-scope", choices=["local", "global"], default=None)
    parent.add_argument("--commit-rules-path", default=None)
    parent.add_argument("--remote-name", default=None)
    parent.add_argument("--token", default=None)
    parent.add_argument("--namespace", default=None)
    parent.add_argument("--ssh-private-key-path", default=None)
    parent.add_argument("--ssh-public-key-path", default=None)
    parent.add_argument("--ssh-title", default=None)
    parent.add_argument("--ssh-comment", default=None)
    parent.add_argument("--no-auto-gitignore", action="store_true")
    parent.add_argument("--no-auto-info-exclude", action="store_true")
    parent.add_argument("--review-manifest", default=None)

    parser = argparse.ArgumentParser(description="Bootstrap Git and GitCode setup for local projects")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("local-only", parents=[parent])
    subparsers.add_parser("preview", parents=[parent])
    adopt = subparsers.add_parser("adopt-existing-project", parents=[parent])
    adopt.add_argument("--max-layers", type=int, default=6)

    create_remote = subparsers.add_parser("create-remote", parents=[parent])
    create_remote.add_argument("--repo-name", default=None)
    create_remote.add_argument("--description", default=None)
    create_remote.add_argument("--private", dest="private", action="store_true", default=True)
    create_remote.add_argument("--public", dest="private", action="store_false")

    publish = subparsers.add_parser("publish", parents=[parent])
    publish.add_argument("--repo-name", default=None)
    publish.add_argument("--description", default=None)
    publish.add_argument("--private", dest="private", action="store_true", default=True)
    publish.add_argument("--public", dest="private", action="store_false")
    publish.add_argument("--commit-message", required=True)
    return parser


def emit(result: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"project: {result.get('project_path')}")
    if "repo_initialized" in result:
        print(f"repo_initialized: {result['repo_initialized']}")
    if result.get("identity"):
        i = result["identity"]
        print(f"identity: {i['scope']} {i['user_name']} <{i['user_email']}>")
    if result.get("detected_stacks") is not None:
        print("detected_stacks:", ", ".join(result.get("detected_stacks") or ["none"]))
    if result.get("commit_rules"):
        print(f"commit_rules: {result['commit_rules']['source']} -> {result['commit_rules']['path']}")
    if result.get("preview"):
        preview = result["preview"]
        print(f"pending_total: {preview['counts'].get('total', 0)}")
        for kind, paths in preview.get("files_by_kind", {}).items():
            print(f"{kind}:")
            for path in paths:
                print(f"- {path}")
    if result.get("adoption_strategy"):
        print("recommended_order:", ", ".join(result["adoption_strategy"].get("recommended_order", [])))
    if result.get("remote"):
        remote = result["remote"]
        print(f"remote: {remote.get('remote_name')} -> {remote.get('url')}")
    if result.get("review_manifest"):
        manifest = result["review_manifest"]
        print(f"review_manifest: {manifest.get('path')} [{manifest.get('snapshot_hash')}]")
    if result.get("commit_message_candidates"):
        print("commit_message_candidates:")
        for index, item in enumerate(result["commit_message_candidates"], start=1):
            print(f"{index}. {item}")
    if result.get("publish"):
        publish = result["publish"]
        print(f"publish: committed={publish.get('committed')} pushed={publish.get('pushed')}")
    if result.get("warnings"):
        print("warnings:")
        for warning in result["warnings"]:
            print(f"- {warning}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config, config_path_used, warnings = load_config(args.config)
    config = apply_cli_overrides(config, args)
    project = Path(args.project).expanduser()
    try:
        log_info(f"start command={args.command} project={project}")
        if args.command == "adopt-existing-project":
            strategy = build_adoption_strategy(project, config, max_layers=max(1, args.max_layers))
            result = {"command": args.command, "project_path": str(project.resolve()), "config_path_used": config_path_used, "warnings": warnings, "adoption_strategy": strategy}
            emit(result, args.json)
            log_info("adopt-existing-project completed")
            return 0

        result = common_bootstrap(project, config)
        result.update({"command": args.command, "config_path_used": config_path_used, "warnings": warnings})

        if args.command == "local-only":
            emit(result, args.json)
            log_info("local-only completed")
            return 0
        if args.command == "preview":
            result["preview"] = build_publish_preview(project.resolve())
            result["commit_message_candidates"] = build_commit_message_candidates(result["preview"], result["commit_rules"], limit=3)
            result["review_manifest"] = write_review_manifest(project.resolve(), args.review_manifest, result["preview"])
            emit(result, args.json)
            log_info("preview completed and review manifest generated")
            return 0
        if args.command == "create-remote":
            result["remote"] = ensure_remote_exists(project.resolve(), config, args.repo_name, args.description, bool(args.private), args.remote_name)
            emit(result, args.json)
            log_info("create-remote completed")
            return 0
        if args.command == "publish":
            manifest_state = verify_review_manifest(project.resolve(), args.review_manifest)
            result["preview"] = manifest_state["preview"]
            result["commit_message_candidates"] = build_commit_message_candidates(result["preview"], result["commit_rules"], limit=3)
            result["review_manifest"] = {
                "path": manifest_state["path"],
                "snapshot_hash": manifest_state["stored"].get("snapshot_hash"),
                "created_at": manifest_state["stored"].get("created_at"),
                "verified": manifest_state["matches"],
            }
            if not result["preview"]["has_changes"]:
                result["publish"] = {
                    "committed": False,
                    "pushed": False,
                    "reason": "working tree is clean",
                    "review_snapshot_hash": manifest_state["stored"].get("snapshot_hash"),
                }
                emit(result, args.json)
                return 0
            if not manifest_state["matches"]:
                raise BootstrapError(
                    "working tree changed after preview; rerun preview and review the new file set before publish"
                )
            high_risk = result["safety_scan"]["high_risk"]
            if high_risk and config["safety"]["abort_on_high_risk"]:
                raise BootstrapError("refusing to publish because high-risk files are present and not ignored: " + ", ".join(high_risk))
            result["remote"] = ensure_remote_exists(project.resolve(), config, args.repo_name, args.description, bool(args.private), args.remote_name)
            result["publish"] = commit_and_push(
                project.resolve(),
                result["remote"]["remote_name"],
                args.commit_message,
                manifest_state["stored"],
                Path(manifest_state["path"]),
            )
            emit(result, args.json)
            log_info("publish completed")
            return 0
        raise BootstrapError(f"unsupported command: {args.command}")
    except BootstrapError as exc:
        log_info(f"command failed: {exc}")
        error_result = {"command": args.command, "project_path": str(project.resolve()), "error": str(exc), "config_path_used": config_path_used, "warnings": warnings}
        emit(error_result, args.json)
        return 2


if __name__ == "__main__":
    sys.exit(main())
