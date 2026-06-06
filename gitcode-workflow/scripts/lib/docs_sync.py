"""Docs-sync orchestration — mapping, diff analysis, rule matching, plan/push.

This module performs deterministic work (diff, rules, wiki I/O) and
returns structured JSON.  Content generation is handled by Claude.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .api import get_repo_info
from .common import (
    BootstrapError, DOC_SUFFIXES, log_info, read_json_file, read_text_safe,
)
from .git import head_commit_or_none, list_remotes, run
from .wiki import (
    build_wiki_url, commit_wiki, ensure_wiki_cloned,
    list_wiki_pages, pull_wiki, push_wiki,
    read_all_wiki_pages, read_wiki_page, resolve_wiki_provider,
    wiki_clone_path, write_wiki_pages,
)

DOCS_MAP_FILENAME = ".gitcode-docs-map.json"


# ── docs-map I/O ─────────────────────────────────────────────────────────

def load_docs_map(project: Path) -> Dict[str, Any]:
    """Load and validate ``.gitcode-docs-map.json`` from project root."""
    map_path = project / DOCS_MAP_FILENAME
    if not map_path.exists():
        raise BootstrapError(
            f"{DOCS_MAP_FILENAME} not found in {project}; "
            f"run 'docs-sync init' to create one"
        )
    docs_map = read_json_file(map_path)
    _validate_docs_map(docs_map, map_path)
    return docs_map


def _validate_docs_map(docs_map: Dict[str, Any], map_path: Path) -> None:
    """Validate required fields in a docs-map."""
    if not isinstance(docs_map, dict):
        raise BootstrapError(f"{map_path}: must be a JSON object")
    rules = docs_map.get("rules")
    if not isinstance(rules, list) or not rules:
        raise BootstrapError(f"{map_path}: 'rules' must be a non-empty array")
    for i, rule in enumerate(rules):
        if not isinstance(rule.get("name"), str) or not rule["name"].strip():
            raise BootstrapError(f"{map_path}: rule[{i}] missing 'name'")
        when = rule.get("when")
        if not isinstance(when, dict):
            raise BootstrapError(f"{map_path}: rule[{i}] missing 'when' object")
        if not isinstance(when.get("paths"), list) or not when["paths"]:
            raise BootstrapError(f"{map_path}: rule[{i}].when.paths must be non-empty array")
        if not isinstance(when.get("types"), list) or not when["types"]:
            raise BootstrapError(f"{map_path}: rule[{i}].when.types must be non-empty array")
        if not isinstance(rule.get("update"), str) or not rule["update"].strip():
            raise BootstrapError(f"{map_path}: rule[{i}] missing 'update' page name")
        if not isinstance(rule.get("prompt"), str) or not rule["prompt"].strip():
            raise BootstrapError(f"{map_path}: rule[{i}] missing 'prompt'")


def create_docs_map_template(
    wiki_repo: str = "",
    branch: str = "main",
) -> Dict[str, Any]:
    """Generate a default ``.gitcode-docs-map.json`` with sensible starter rules."""
    return {
        "wiki_repo": wiki_repo,
        "branch": branch,
        "rules": [
            {
                "name": "源码文档同步",
                "when": {
                    "paths": ["lib/**/*.py", "scripts/**/*.py", "scripts/**/*"],
                    "types": ["feat", "refactor", "fix", "perf"],
                },
                "update": "开发-架构概览.md",
                "prompt": (
                    "分析代码变更，更新对应的开发文档章节。"
                    "关注新增/修改/删除的模块、函数签名和接口变更，"
                    "保留原有文档的结构和风格。只更新受影响的部分，"
                    "不要重写整个页面。"
                ),
            },
            {
                "name": "配置变更记录",
                "when": {
                    "paths": [
                        "pyproject.toml", "setup.py", "requirements*.txt",
                        "*.cfg", "*.ini", "*.toml", ".env.example",
                        "Dockerfile", "docker-compose.*",
                    ],
                    "types": ["*"],
                },
                "update": "环境配置.md",
                "prompt": (
                    "分析依赖和配置变化，更新环境配置文档。"
                    "关注新增/删除/升级的依赖包、新增的环境变量、"
                    "Docker 配置变更等。"
                ),
            },
            {
                "name": "更新日志",
                "when": {
                    "paths": ["*"],
                    "types": ["feat", "fix", "refactor", "perf"],
                },
                "update": "CHANGELOG.md",
                "prompt": (
                    "基于提交信息，在 CHANGELOG 顶部追加一条简明的版本变更记录。"
                    "格式: ## YYYY-MM-DD\n\n- type(scope): 简述变更内容\n"
                    "保留历史记录不变。"
                ),
            },
        ],
    }


def resolve_wiki_repo_from_remote(project: Path, config: Dict[str, Any]) -> str:
    """Determine wiki_repo string from project's git remote URL."""
    remote_name = config["git"]["remote_name"]
    remotes = list_remotes(project)
    remote_url = next(
        (r["url"] for r in remotes if r["name"] == remote_name), None
    )
    if not remote_url:
        raise BootstrapError(f"remote '{remote_name}' not found; run create-remote first")
    return build_wiki_url(remote_url)


# ── repo readiness check ─────────────────────────────────────────────────

def check_repo_wiki_ready(
    config: Dict[str, Any],
    namespace: str,
    repo_name: str,
) -> Dict[str, Any]:
    """Check if the repository can use wiki (public + wiki git repo reachable).

    Returns ``{ready, is_public, has_wiki, message}``.
    Uses ``git ls-remote`` to verify the wiki repo exists, since
    GitCode API does not expose a ``wiki_enabled`` field.
    """
    from .api import get_repo_info

    # Check visibility via API
    is_public = False
    try:
        repo = get_repo_info(config, namespace, repo_name)
        is_public = not repo.get("private", True)
    except BootstrapError:
        return {
            "ready": False, "is_public": False, "has_wiki": False,
            "message": "could not fetch repo info from API",
        }

    if not is_public:
        return {
            "ready": False, "is_public": False, "has_wiki": False,
            "message": "repository is private; GitCode wiki requires a public repository",
        }

    # Check wiki git repo reachable via ls-remote
    from .wiki import resolve_wiki_provider
    from .common import run as common_run

    remotes_result = common_run(
        ["git", "remote", "get-url", config["git"]["remote_name"]],
        cwd=Path("."), check=False,
    )
    remote_url = remotes_result.stdout.strip() if remotes_result.returncode == 0 else ""
    wiki_url = ""
    try:
        if remote_url:
            wiki_url = resolve_wiki_provider(remote_url)["wiki_ssh_url"]
    except BootstrapError:
        pass

    has_wiki = False
    if wiki_url:
        ls_result = common_run(
            ["git", "ls-remote", "--heads", wiki_url], cwd=Path("."), check=False
        )
        has_wiki = ls_result.returncode == 0

    if not has_wiki:
        wiki_web_url = f"https://gitcode.com/{namespace}/{repo_name}/wiki"
        return {
            "ready": False, "is_public": True, "has_wiki": False,
            "message": (
                "wiki git repo not reachable — GitCode does not provide an API to create "
                "the wiki repository. This one-time manual step is required."
            ),
            "action": f"Open {wiki_web_url} in browser → click 'Create the first page' → save",
            "wiki_web_url": wiki_web_url,
        }
    return {
        "ready": True, "is_public": True, "has_wiki": True,
        "message": "wiki is ready",
    }


# ── diff / commit analysis ───────────────────────────────────────────────

def compute_file_changes(
    project: Path,
    since: str = "HEAD~1",
) -> List[Dict[str, Any]]:
    """Get changed files and their diffs from the given commit range.

    Returns ``[{"path": str, "status": str, "diff": str}, ...]``.
    Skips binary files and files that no longer exist.
    """
    head = head_commit_or_none(project)
    if not head:
        return []

    # Get name-status
    ns_result = run(
        ["git", "diff", "--name-status", "--diff-filter=ACMRT", f"{since}..HEAD"],
        cwd=project, check=True,
    )
    lines = [l.strip() for l in ns_result.stdout.split("\n") if l.strip()]
    changes: List[Dict[str, Any]] = []
    for line in lines:
        parts = line.split("\t", 1)
        if len(parts) < 2:
            continue
        status, path = parts[0], parts[1]
        # Only include text files
        full_path = project / path
        if not full_path.exists() and status != "D":
            continue
        diff = _get_file_diff(project, since, path)
        if diff is None:
            continue
        changes.append({"path": path, "status": status, "diff": diff})
    return changes


def _get_file_diff(project: Path, since: str, path: str) -> Optional[str]:
    """Get diff for a single file. Returns None for binary files."""
    result = run(
        ["git", "diff", f"{since}..HEAD", "--", path],
        cwd=project, check=False,
    )
    if result.returncode != 0:
        return None
    output = result.stdout
    # Skip binary file diffs
    if output.startswith("Binary files"):
        return None
    # Truncate to keep output manageable
    if len(output) > 32000:
        output = output[:32000] + "\n... [truncated]"
    return output


def extract_commit_messages(
    project: Path,
    since: str = "HEAD~1",
) -> List[str]:
    """Extract commit messages from the range."""
    result = run(
        ["git", "log", "--format=%s", f"{since}..HEAD"],
        cwd=project, check=True,
    )
    return [m.strip() for m in result.stdout.split("\n") if m.strip()]


def extract_commit_types(messages: List[str]) -> List[str]:
    """Extract unique conventional commit types from messages."""
    types: List[str] = []
    seen: set = set()
    for msg in messages:
        m = re.match(r"^(\w+)(?:\([^)]*\))?:", msg)
        if m:
            t = m.group(1)
            if t not in seen:
                types.append(t)
                seen.add(t)
    return types


# ── rule matching ────────────────────────────────────────────────────────

def _glob_match(path: str, pattern: str) -> bool:
    """Match a file path against a glob pattern, supporting ``**`` for recursive matching.

    Unlike ``fnmatch``, this correctly handles ``**`` across path separators,
    making patterns like ``lib/**/*.py`` work on Python 3.10.

    If the pattern does not start with ``**/``, it is implicitly treated as
    ``**/<pattern>`` so that ``lib/**/*.py`` matches any path ending in that
    suffix regardless of ancestor directories.
    """
    if not pattern.startswith("**/"):
        pattern = "**/" + pattern
    return _glob_re_match(path, pattern)


def _glob_re_match(path: str, pattern: str) -> bool:
    """Internal: convert a (possibly **/-prefixed) glob to regex and test."""
    # Convert glob pattern to regex
    regex_parts: List[str] = ["^"]
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # ** — matches anything including path separators
                if i + 2 < n and pattern[i + 2] == "/":
                    regex_parts.append("(?:.*/)?")  # zero or more dirs
                    i += 3
                    continue
                else:
                    regex_parts.append(".*")
                    i += 2
                    continue
            else:
                # * — matches anything except path separator
                regex_parts.append("[^/]*")
                i += 1
                continue
        elif c == "?":
            regex_parts.append("[^/]")
        elif c in ".+^$()[]{}|\\":
            regex_parts.append("\\" + c)
        else:
            regex_parts.append(c)
        i += 1
    regex_parts.append("$")
    return bool(re.match("".join(regex_parts), path))


def match_rule(
    rule: Dict[str, Any],
    changed_files: List[Dict[str, Any]],
    commit_types: List[str],
) -> Dict[str, Any]:
    """Check if a single rule matches the changes.

    Path matching uses ``fnmatch`` patterns.  Type matching checks
    commit types against ``rule.when.types`` (``"*"`` matches all).
    """
    when = rule["when"]
    path_patterns = when["paths"]
    type_patterns = when.get("types", ["*"])

    matched_files: List[str] = []
    for cf in changed_files:
        if any(_glob_match(cf["path"], p) for p in path_patterns):
            matched_files.append(cf["path"])

    matched_types: List[str] = []
    if "*" in type_patterns:
        matched_types = list(commit_types) if commit_types else ["*"]
    else:
        matched_types = [t for t in commit_types if t in type_patterns]

    matched = bool(matched_files and matched_types)
    return {
        "rule": rule,
        "matched": matched,
        "matched_files": matched_files,
        "matched_types": matched_types,
    }


def match_all_rules(
    docs_map: Dict[str, Any],
    changed_files: List[Dict[str, Any]],
    commit_types: List[str],
    pages_filter: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Match all rules in docs_map against changes.  Returns only matched rules."""
    results: List[Dict[str, Any]] = []
    for rule in docs_map["rules"]:
        if pages_filter and rule["update"] not in pages_filter:
            continue
        m = match_rule(rule, changed_files, commit_types)
        if m["matched"]:
            results.append(m)
    return results


# ── plan / init / push ───────────────────────────────────────────────────

def build_sync_plan(
    project: Path,
    config: Dict[str, Any],
    since: str = "HEAD~1",
    pages_filter: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a complete sync plan for incremental updates.

    Steps: load map → compute diff → extract types → match rules →
           clone wiki → read existing pages → assemble plan.
    """
    docs_map = load_docs_map(project)

    # Resolve wiki URL
    wiki_repo = docs_map.get("wiki_repo") or resolve_wiki_repo_from_remote(project, config)
    wiki_branch = docs_map.get("branch", "main")
    wiki_dir = wiki_clone_path(project)

    # Compute changes
    changed_files = compute_file_changes(project, since)
    commit_messages = extract_commit_messages(project, since)
    commit_types = extract_commit_types(commit_messages)

    # Match rules
    matched = match_all_rules(docs_map, changed_files, commit_types, pages_filter)

    # Clone wiki and read existing pages (best-effort)
    existing_pages: Dict[str, str] = {}
    wiki_error: Optional[str] = None
    try:
        ensure_wiki_cloned(wiki_repo, wiki_dir, wiki_branch)
        existing_pages = read_all_wiki_pages(wiki_dir)
    except BootstrapError as exc:
        wiki_error = str(exc)
        log_info(f"wiki clone skipped (plan): {wiki_error}")

    # Collect pages_to_update
    pages_to_update: List[str] = []
    for m in matched:
        page = m["rule"]["update"]
        if page not in pages_to_update:
            pages_to_update.append(page)

    # Collect relevant file diffs for matched rules
    relevant_diffs: Dict[str, str] = {}
    for cf in changed_files:
        relevant_diffs[cf["path"]] = cf["diff"]

    return {
        "wiki_url": wiki_repo,
        "wiki_branch": wiki_branch,
        "since": since,
        "commit_messages": commit_messages,
        "commit_types": commit_types,
        "changed_files": [
            {"path": cf["path"], "status": cf["status"]} for cf in changed_files
        ],
        "file_diffs": relevant_diffs,
        "matched_rules": [
            {
                "name": m["rule"]["name"],
                "update": m["rule"]["update"],
                "prompt": m["rule"]["prompt"],
                "matched_files": m["matched_files"],
                "matched_types": m["matched_types"],
            }
            for m in matched
        ],
        "existing_wiki_pages": {
            page: existing_pages.get(page, "")
            for page in pages_to_update
        },
        "pages_to_update": pages_to_update,
        "docs_map_path": str(project / DOCS_MAP_FILENAME),
        "wiki_dir": str(wiki_dir),
        "wiki_error": wiki_error,
    }


def build_init_plan(
    project: Path,
    config: Dict[str, Any],
    docs_dir: str = "docs",
) -> Dict[str, Any]:
    """Build a plan for initial full docs sync.

    Scans the project's docs_dir for .md files and maps each to a wiki page.
    Also generates a suggested ``.gitcode-docs-map.json``.
    """
    # Resolve wiki URL
    wiki_repo = resolve_wiki_repo_from_remote(project, config)
    provider = resolve_wiki_provider(wiki_repo)
    wiki_branch = provider["default_branch"]
    wiki_dir = wiki_clone_path(project)

    # Scan docs directory
    source_dir = project / docs_dir
    source_docs: List[Dict[str, Any]] = []
    if source_dir.is_dir():
        for fp in sorted(source_dir.rglob("*.md")):
            rel = fp.relative_to(source_dir)
            content = read_text_safe(fp)
            source_docs.append({
                "path": str(rel),
                "absolute_path": str(fp),
                "content": content,
                "size": len(content),
            })

    # Clone wiki and read existing pages (best-effort)
    existing_pages: Dict[str, str] = {}
    wiki_error_init: Optional[str] = None
    try:
        ensure_wiki_cloned(wiki_repo, wiki_dir, wiki_branch)
        existing_pages = read_all_wiki_pages(wiki_dir)
    except BootstrapError as exc:
        wiki_error_init = str(exc)
        log_info(f"wiki clone skipped (init): {wiki_error_init}")

    # Suggest mapping: docs/xxx.md -> Xxx.md (title-case)
    suggested: Dict[str, str] = {}
    for sd in source_docs:
        stem = Path(sd["path"]).stem
        # Convert kebab/snake to title-case
        words = re.split(r"[-_]", stem)
        title = "-".join(w.capitalize() for w in words)
        suggested[sd["path"]] = f"{title}.md"

    # Generate template docs-map
    template = create_docs_map_template(wiki_repo, wiki_branch)

    return {
        "wiki_url": wiki_repo,
        "wiki_branch": wiki_branch,
        "source_docs": source_docs,
        "existing_wiki_pages": existing_pages,
        "suggested_mapping": suggested,
        "suggested_docs_map": template,
        "docs_map_template_path": str(project / DOCS_MAP_FILENAME),
        "wiki_dir": str(wiki_dir),
        "wiki_error": wiki_error_init,
    }


def execute_sync(
    project: Path,
    config: Dict[str, Any],
    pages_content: Dict[str, str],
    commit_message: str = "docs: sync wiki pages via docs-sync",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Apply pre-generated wiki page content.

    Steps: load map → clone/pull wiki → write pages → commit → push.
    If dry_run, show what would change without committing.
    """
    docs_map = load_docs_map(project)
    wiki_repo = docs_map.get("wiki_repo") or resolve_wiki_repo_from_remote(project, config)
    wiki_branch = docs_map.get("branch", "main")
    wiki_dir = wiki_clone_path(project)

    # Dry-run: skip all wiki operations
    pages_to_update = list(pages_content.keys())
    if dry_run:
        return {
            "pushed": False,
            "dry_run": True,
            "pages_to_update": pages_to_update,
            "pages_content_preview": {
                page: content[:200] + ("..." if len(content) > 200 else "")
                for page, content in pages_content.items()
            },
            "wiki_dir": str(wiki_dir),
            "wiki_branch": wiki_branch,
            "wiki_url": wiki_repo,
        }

    # Ensure wiki is up to date
    ensure_wiki_cloned(wiki_repo, wiki_dir, wiki_branch)
    pull_wiki(wiki_dir, wiki_branch)

    # Write pages
    write_results = write_wiki_pages(wiki_dir, pages_content)

    # Commit
    commit_result = commit_wiki(wiki_dir, commit_message)
    if commit_result["files_changed"] == 0:
        return {
            "pushed": False,
            "dry_run": False,
            "pages_updated": [],
            "commit_hash": None,
            "reason": "no changes to commit",
            "wiki_dir": str(wiki_dir),
        }

    # Push
    push_result = push_wiki(wiki_dir, wiki_branch)

    return {
        "pushed": push_result["pushed"],
        "dry_run": False,
        "pages_updated": [r["page"] for r in write_results],
        "commit_hash": commit_result["commit_hash"],
        "wiki_dir": str(wiki_dir),
        "wiki_branch": wiki_branch,
    }
