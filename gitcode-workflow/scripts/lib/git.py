"""Git operations — init, identity, remotes, ignore rules, status collection."""
from __future__ import annotations

from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Counter as CounterT, Dict, List, Optional, Sequence

from .common import (
    BootstrapError,
    ensure_tool,
    expand_path,
    log_info,
    run,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent.parent
BUNDLED_COMMIT_RULES = SKILL_ROOT / "references" / "commit-rules.md"

# ── ignore-rule constants ──────────────────────────────────────────────
GENERIC_GITIGNORE_PATTERNS = [
    ".DS_Store", "Thumbs.db", ".idea/", ".vscode/", "*.log", "logs/",
]
STACK_GITIGNORE_PATTERNS = {
    "springboot": ["target/", "build/", ".gradle/", "*.class", "out/"],
    "python": [
        "__pycache__/", "*.py[cod]", ".pytest_cache/", ".mypy_cache/",
        ".ruff_cache/", ".venv/", "venv/", ".coverage", "dist/", "*.egg-info/",
    ],
    "go": ["bin/", "coverage.out", "*.coverprofile", "*.test"],
}
LOCAL_EXCLUDE_PATTERNS = [
    ".env", ".env.*", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore",
    "*.pem", "*id_ed25519*", "*id_rsa*",
    "application-local.yml", "application-local.yaml",
    "application-dev.yml", "application-dev.yaml",
    "application-prod.yml", "application-prod.yaml",
    "application-local.properties", "application-dev.properties",
    "application-prod.properties",
    "secrets*.json", "credentials*.json", "service-account*.json",
]
IGNORE_BLOCK_HEADER = "# gitcode-workflow shared ignore rules"
EXCLUDE_BLOCK_HEADER = "# gitcode-workflow local-only exclude rules"


def ensure_git_available() -> None:
    ensure_tool("git", "git is not installed or not available in PATH")


def is_git_repo(project: Path) -> bool:
    return (project / ".git").exists()


def init_repo(project: Path, default_branch: str) -> bool:
    """Initialize git repo if not already one.  Returns True if newly created."""
    if is_git_repo(project):
        return False
    project.mkdir(parents=True, exist_ok=True)
    result = run(["git", "init", "-b", default_branch], cwd=project, check=False)
    if result.returncode != 0:
        run(["git", "init"], cwd=project, check=True)
        run(["git", "checkout", "-b", default_branch], cwd=project, check=False)
    return True


def repo_has_commits(project: Path) -> bool:
    return run(["git", "rev-parse", "--verify", "HEAD"], cwd=project, check=False).returncode == 0


def set_git_identity(
    project: Path, scope: str, user_name: str, user_email: str
) -> Dict[str, str]:
    target = ["git", "config"]
    cwd: Optional[Path] = project
    if scope == "global":
        target.append("--global")
        cwd = None
    run(target + ["user.name", user_name], cwd=cwd, check=True)
    run(target + ["user.email", user_email], cwd=cwd, check=True)
    return {"scope": scope, "user_name": user_name, "user_email": user_email}


def repo_current_branch(project: Path) -> str:
    result = run(["git", "branch", "--show-current"], cwd=project, check=False)
    branch = result.stdout.strip()
    return branch or "master"


def head_commit_or_none(project: Path) -> Optional[str]:
    result = run(["git", "rev-parse", "HEAD"], cwd=project, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


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
            fallback = (
                "gitcode"
                if remote_name != "gitcode" and "gitcode" not in existing_names
                else f"{remote_name}-alt"
            )
            remote_name = fallback
            run(["git", "remote", "add", remote_name, url], cwd=project, check=True)
            action = "added_fallback"
    else:
        run(["git", "remote", "add", remote_name, url], cwd=project, check=True)
    run(["git", "config", "remote.pushDefault", remote_name], cwd=project, check=False)
    return {"remote_name": remote_name, "url": url, "action": action}


# ── stack detection ────────────────────────────────────────────────────

def detect_stacks(project: Path) -> List[str]:
    stacks: List[str] = []
    if any((project / name).exists() for name in ["pom.xml", "build.gradle", "build.gradle.kts"]):
        stacks.append("springboot")
    if any((project / name).exists() for name in ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile"]):
        stacks.append("python")
    if (project / "go.mod").exists():
        stacks.append("go")
    return stacks


# ── ignore-file management ─────────────────────────────────────────────

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


def update_gitignore(
    project: Path, stacks: Sequence[str], enabled: bool
) -> Dict[str, Any]:
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
    return {
        "path": str(path),
        "added": ensure_lines(path, IGNORE_BLOCK_HEADER, lines),
        "enabled": True,
    }


def update_info_exclude(project: Path, enabled: bool) -> Dict[str, Any]:
    path = project / ".git" / "info" / "exclude"
    if not enabled:
        return {"path": str(path), "added": [], "enabled": False}
    return {
        "path": str(path),
        "added": ensure_lines(path, EXCLUDE_BLOCK_HEADER, LOCAL_EXCLUDE_PATTERNS),
        "enabled": True,
    }


def resolve_commit_rules(project: Path, relative_path: str) -> Dict[str, str]:
    candidate = project / relative_path
    if candidate.exists():
        return {"source": "project", "path": str(candidate)}
    return {"source": "bundled", "path": str(BUNDLED_COMMIT_RULES)}


# ── git status helpers ─────────────────────────────────────────────────

def parse_status_line(line: str) -> Dict[str, Any]:
    if line.startswith("?? "):
        return {
            "raw": line, "path": line[3:], "old_path": None,
            "index_status": "?", "worktree_status": "?",
            "kind": "untracked", "staged": False, "unstaged": True,
        }
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
    return {
        "raw": line, "path": path, "old_path": old_path,
        "index_status": index_status, "worktree_status": worktree_status,
        "kind": kind,
        "staged": index_status not in {" ", "?"},
        "unstaged": worktree_status not in {" ", "?"},
    }


def collect_status_entries(project: Path) -> List[Dict[str, Any]]:
    lines = run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=project, check=False,
    ).stdout.splitlines()
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
    grouped: Dict[str, List[str]] = {
        "added": [], "modified": [], "deleted": [], "renamed": [],
        "copied": [], "untracked": [], "changed": [], "unmerged": [],
    }
    for entry in entries:
        display_path = entry["path"]
        if entry.get("old_path"):
            display_path = f"{entry['old_path']} -> {entry['path']}"
        grouped.setdefault(entry["kind"], []).append(display_path)
    return {key: value for key, value in grouped.items() if value}
