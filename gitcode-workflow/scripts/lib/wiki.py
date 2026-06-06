"""Wiki git repository operations — clone, read, write, commit, push.

Provider-agnostic: callers pass in wiki URL and branch derived from
resolve_wiki_provider() which auto-detects gitcode/github from the remote.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import BootstrapError, log_info, run


WIKI_DIR_NAME = "wiki"


# ── provider resolution ──────────────────────────────────────────────────

def resolve_wiki_provider(remote_url: str) -> Dict[str, Any]:
    """Derive wiki provider details from a project remote URL.

    Parses ``git@host:owner/repo.git`` and returns provider metadata.
    Supports gitcode.com and github.com; raises BootstrapError for unknown hosts.
    """
    target = (remote_url or "").strip()
    if not target:
        raise BootstrapError("cannot resolve wiki provider from empty remote URL")

    # SSH form:   git@host:owner/repo.git
    # HTTPS form: https://host/owner/repo.git
    if target.startswith("git@"):
        host_part, _, path_part = target.partition(":")
        host = host_part.split("@", 1)[1]
    elif "://" in target:
        from urllib.parse import urlparse
        parsed = urlparse(target)
        host = parsed.hostname or ""
        path_part = parsed.path.lstrip("/")
    else:
        raise BootstrapError(f"unsupported remote URL format: {target}")

    host = host.lower().strip()
    path_part = path_part.rstrip("/")
    if path_part.endswith(".git"):
        path_part = path_part[:-4]

    parts = path_part.split("/")
    owner = parts[-2] if len(parts) >= 2 else ""
    repo = parts[-1] if len(parts) >= 1 else ""

    # Determine provider and conventions
    if "gitcode.com" in host:
        provider = "gitcode"
        default_branch = "main"
    elif "github.com" in host:
        provider = "github"
        default_branch = "master"
    else:
        raise BootstrapError(
            f"unknown wiki provider for host '{host}'; "
            f"currently supported: gitcode.com, github.com"
        )

    wiki_ssh_url = f"git@{host}:{owner}/{repo}.wiki.git"

    return {
        "provider": provider,
        "host": host,
        "owner": owner,
        "repo": repo,
        "wiki_ssh_url": wiki_ssh_url,
        "default_branch": default_branch,
    }


def build_wiki_url(remote_url: str) -> str:
    """Construct wiki git URL from project remote URL.

    >>> build_wiki_url("git@gitcode.com:owner/repo.git")
    'git@gitcode.com:owner/repo.wiki.git'
    """
    provider = resolve_wiki_provider(remote_url)
    return provider["wiki_ssh_url"]


# ── local clone path ──────────────────────────────────────────────────────

def wiki_clone_path(project: Path) -> Path:
    """Return the local wiki clone path: ``<project>/.git/wiki/``."""
    return project / ".git" / WIKI_DIR_NAME


# ── clone / pull ──────────────────────────────────────────────────────────

def _ssh_env() -> Dict[str, str]:
    """Build an SSH-friendly environment that respects the configured key."""
    env = os.environ.copy()
    # Preserve any existing GIT_SSH_COMMAND so the caller can override.
    return env


def ensure_wiki_cloned(
    wiki_url: str,
    wiki_dir: Path,
    branch: str = "main",
) -> Dict[str, Any]:
    """Clone wiki repo if not already cloned; otherwise pull latest.

    Returns ``{"path": str, "action": "cloned"|"pulled"|"exists"}``.
    """
    git_dir = wiki_dir / ".git"
    if git_dir.exists():
        # Already cloned — pull to get latest
        try:
            pull_wiki(wiki_dir, branch)
            return {"path": str(wiki_dir), "action": "pulled", "branch": branch}
        except BootstrapError:
            log_info("wiki pull failed; continuing with existing clone")
            return {"path": str(wiki_dir), "action": "exists", "branch": branch}

    wiki_dir.parent.mkdir(parents=True, exist_ok=True)
    log_info(f"cloning wiki repo: {wiki_url} -> {wiki_dir}")
    run(
        ["git", "clone", "--branch", branch, wiki_url, str(wiki_dir)],
        cwd=wiki_dir.parent, check=True,
    )
    return {"path": str(wiki_dir), "action": "cloned", "branch": branch}


def pull_wiki(wiki_dir: Path, branch: str = "main") -> Dict[str, Any]:
    """Pull latest changes from wiki remote."""
    log_info(f"pulling wiki in {wiki_dir}")
    # Checkout target branch first, then pull
    run(["git", "checkout", branch], cwd=wiki_dir, check=True)
    result = run(["git", "pull", "origin", branch], cwd=wiki_dir, check=False)
    updated = "Already up to date" not in result.stdout
    return {"action": "pulled", "branch": branch, "updated": updated}


# ── page I/O ──────────────────────────────────────────────────────────────

def list_wiki_pages(wiki_dir: Path) -> List[Dict[str, Any]]:
    """List all .md files in the wiki repo root.

    Returns ``[{"name": "PageName.md", "path": str, "size": int}, ...]``.
    """
    if not wiki_dir.exists():
        return []
    pages: List[Dict[str, Any]] = []
    for fp in sorted(wiki_dir.iterdir()):
        if fp.is_file() and fp.suffix == ".md":
            pages.append({
                "name": fp.name,
                "path": str(fp),
                "size": fp.stat().st_size,
            })
    return pages


def read_wiki_page(wiki_dir: Path, filename: str) -> str:
    """Read content of a single wiki page.  Returns file content as string."""
    page_path = wiki_dir / filename
    if not page_path.exists():
        raise BootstrapError(f"wiki page not found: {filename}")
    return page_path.read_text(encoding="utf-8")


def read_all_wiki_pages(wiki_dir: Path) -> Dict[str, str]:
    """Read all .md files in the wiki root.  Returns ``{filename: content}``."""
    result: Dict[str, str] = {}
    for page in list_wiki_pages(wiki_dir):
        result[page["name"]] = read_wiki_page(wiki_dir, page["name"])
    return result


def write_wiki_page(
    wiki_dir: Path,
    filename: str,
    content: str,
) -> Dict[str, Any]:
    """Write content to a wiki page file.

    Returns ``{"page": str, "bytes_written": int, "action": "created"|"updated"}``.
    """
    if not filename.endswith(".md"):
        filename += ".md"
    page_path = wiki_dir / filename
    existed = page_path.exists()
    wiki_dir.mkdir(parents=True, exist_ok=True)
    page_path.write_text(content, encoding="utf-8")
    return {
        "page": filename,
        "bytes_written": len(content.encode("utf-8")),
        "action": "updated" if existed else "created",
    }


def write_wiki_pages(
    wiki_dir: Path,
    pages: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Write multiple wiki pages at once.  Returns per-page results."""
    results: List[Dict[str, Any]] = []
    for filename, content in pages.items():
        results.append(write_wiki_page(wiki_dir, filename, content))
    return results


# ── commit / push ─────────────────────────────────────────────────────────

def commit_wiki(
    wiki_dir: Path,
    message: str,
    user_name: str = "docs-sync",
    user_email: str = "docs-sync@bot",
) -> Dict[str, Any]:
    """Stage all changes and commit to wiki repo (repo-local identity).

    Returns ``{"commit_hash": str, "files_changed": int, "message": str}``.
    """
    log_info("staging wiki changes")
    run(["git", "add", "."], cwd=wiki_dir, check=True)

    # Count changed files
    diff_result = run(
        ["git", "diff", "--cached", "--name-only"], cwd=wiki_dir, check=True
    )
    files = [f for f in diff_result.stdout.strip().split("\n") if f]
    if not files:
        return {"commit_hash": "", "files_changed": 0, "message": "nothing to commit"}

    log_info(f"committing {len(files)} wiki file(s): {message}")
    run(
        ["git", "-c", f"user.name={user_name}",
         "-c", f"user.email={user_email}",
         "commit", "-m", message],
        cwd=wiki_dir, check=True,
    )
    hash_result = run(
        ["git", "rev-parse", "HEAD"], cwd=wiki_dir, check=True
    )
    return {
        "commit_hash": hash_result.stdout.strip(),
        "files_changed": len(files),
        "message": message,
    }


def push_wiki(
    wiki_dir: Path,
    branch: str = "main",
) -> Dict[str, Any]:
    """Push wiki changes to remote.

    Returns ``{"pushed": bool, "branch": str, "remote": str}``.
    """
    log_info(f"pushing wiki to origin/{branch}")
    result = run(
        ["git", "push", "origin", branch],
        cwd=wiki_dir, check=False,
    )
    pushed = result.returncode == 0
    if not pushed:
        log_info(f"wiki push failed: {result.stderr}")
        # Try to pull and rebase if push was rejected
        if "rejected" in result.stderr or "non-fast-forward" in result.stderr:
            log_info("wiki push rejected; attempting pull --rebase")
            run(["git", "pull", "--rebase", "origin", branch], cwd=wiki_dir, check=True)
            run(["git", "push", "origin", branch], cwd=wiki_dir, check=True)
            pushed = True
    return {"pushed": pushed, "branch": branch, "remote": "origin"}
