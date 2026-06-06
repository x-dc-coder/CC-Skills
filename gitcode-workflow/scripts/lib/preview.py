"""Preview pipeline — diff excerpt, commit-message candidates, scope/type inference."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Counter as CounterT, Dict, List, Sequence

from .common import (
    COMMIT_MESSAGE_RE,
    DOC_SUFFIXES,
    SOURCE_SUFFIXES,
    VALID_COMMIT_TYPES,
    file_is_text,
    infer_scope_from_path,
    is_build_or_config_path,
    is_doc_path,
    is_source_path,
    is_test_path,
    read_text_safe,
    truncate_text,
)
from .git import (
    collect_status_entries,
    group_paths_by_kind,
    build_status_counts,
    repo_has_commits,
    run,
)

# ── preview size caps ──────────────────────────────────────────────────
PREVIEW_MAX_DIFF_LINES = 220
PREVIEW_MAX_DIFF_CHARS = 16000
PREVIEW_MAX_NEW_FILE_BYTES = 32768
PREVIEW_MAX_NEW_FILE_LINES = 80


# ── diff / file preview ────────────────────────────────────────────────

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
    diff = run(
        ["git", "diff", "--no-index", "--no-color", "--unified=1", "--", "/dev/null", relative_path],
        cwd=project, check=False,
    ).stdout
    if diff.strip():
        diff, _ = truncate_text(diff.strip(), max_lines=60, max_chars=4000)
        return diff.strip()
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()[:PREVIEW_MAX_NEW_FILE_LINES]
    return f"### untracked file: {relative_path}\n" + "\n".join(lines)


def build_diff_excerpt(
    project: Path, entries: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    sections: List[str] = []
    if repo_has_commits(project):
        tracked_diff = run(
            ["git", "diff", "--no-color", "--unified=1", "--find-renames", "HEAD"],
            cwd=project, check=False,
        ).stdout
        if tracked_diff.strip():
            sections.append(tracked_diff.strip())
    untracked_entries = [e for e in entries if e["kind"] == "untracked"]
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
    excerpt, truncated = truncate_text(
        "\n\n".join(sections),
        max_lines=PREVIEW_MAX_DIFF_LINES,
        max_chars=PREVIEW_MAX_DIFF_CHARS,
    )
    return {"text": excerpt, "truncated": truncated}


# ── scope / type inference ─────────────────────────────────────────────

def infer_scope_hints(entries: Sequence[Dict[str, Any]]) -> List[str]:
    counter: Counter[str] = Counter()
    for entry in entries:
        counter[infer_scope_from_path(entry["path"])] += 1
    return [scope for scope, _ in counter.most_common(3)] or ["global"]


def infer_type_hints(entries: Sequence[Dict[str, Any]]) -> List[str]:
    paths = [entry["path"] for entry in entries]
    if not paths:
        return []
    docs_only = all(is_doc_path(path) for path in paths)
    tests_only = all(is_test_path(path) for path in paths)
    build_only = all(is_build_or_config_path(path) for path in paths)
    added_source = any(
        entry["kind"] in {"added", "untracked"} and is_source_path(entry["path"])
        for entry in entries
    )
    removed_or_renamed = any(
        entry["kind"] in {"deleted", "renamed"} for entry in entries
    )
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


# ── publish preview aggregate ──────────────────────────────────────────

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


# ── commit-message generation ──────────────────────────────────────────

def _extract_diff_keywords(preview: Dict[str, Any]) -> List[str]:
    """Pull meaningful keywords from the diff excerpt for subject generation."""
    diff_text = preview.get("diff_excerpt", "")
    keywords: List[str] = []

    # new section headers in markdown (## Title)
    new_sections = re.findall(r"^\+##\s+(.+)$", diff_text, re.MULTILINE)
    for sec in new_sections:
        cleaned = sec.strip().rstrip(".")
        if len(cleaned) > 2 and len(cleaned) < 40:
            keywords.append(cleaned)

    # new file stems (meaningful names from untracked/added files)
    files_by_kind = preview.get("files_by_kind", {})
    new_files = files_by_kind.get("added", []) + files_by_kind.get("untracked", [])
    for path in new_files:
        pure = PurePosixPath(path)
        stem = pure.stem
        if (
            stem and not stem.startswith(".") and not stem.startswith("_")
            and len(stem) > 2 and len(stem) < 25
        ):
            if stem.lower() not in {"readme", "index", "main", "config", "setup"}:
                keywords.append(stem)

    # module/skill directory names from paths
    all_paths = [f["path"] for f in preview.get("files", [])]
    dirs: Counter[str] = Counter()
    for p in all_paths:
        parts = PurePosixPath(p).parts
        if len(parts) >= 2:
            top = parts[0]
            if not top.startswith("."):
                dirs[top] += 1
    for d, _ in dirs.most_common(2):
        if d not in keywords:
            keywords.append(d)

    return keywords[:4]


def _contextual_subject(
    commit_type: str,
    preview: Dict[str, Any],
    prefer_chinese: bool,
) -> str:
    """Generate a subject that reflects actual diff content."""
    files_by_kind = preview.get("files_by_kind", {})
    added = len(files_by_kind.get("added", [])) + len(files_by_kind.get("untracked", []))
    modified = len(files_by_kind.get("modified", []))
    deleted = len(files_by_kind.get("deleted", []))
    keywords = _extract_diff_keywords(preview)

    if prefer_chinese:
        return _chinese_subject(commit_type, added, modified, deleted, keywords)
    else:
        return _english_subject(commit_type, added, modified, deleted, keywords)


def _chinese_subject(
    commit_type: str, added: int, modified: int, deleted: int, keywords: List[str]
) -> str:
    kw = "、".join(keywords[:2]) if keywords else ""

    by_type: Dict[str, str] = {
        "feat": f"新增 {kw} 功能" if kw else "新增核心功能",
        "fix": f"修复 {kw} 相关问题" if kw else "修复已知问题",
        "docs": f"更新 {kw} 文档与使用说明" if kw else "更新文档与使用说明",
        "style": f"统一 {kw} 代码格式" if kw else "统一代码格式与细节样式",
        "refactor": f"重构 {kw} 代码结构并提升可维护性" if kw else "重构代码结构并提升可维护性",
        "perf": f"优化 {kw} 性能" if kw else "优化性能并减少不必要开销",
        "test": f"补充 {kw} 测试覆盖" if kw else "补充测试覆盖并完善校验",
        "chore": f"整理 {kw} 工程配置" if kw else "整理工程配置与仓库基础设置",
        "revert": f"回滚 {kw} 相关改动" if kw else "回滚存在风险的历史改动",
    }

    # special cases based on file counts
    if commit_type == "refactor" and (deleted > 0):
        if deleted > 0 and added > 0 and modified > 0:
            return "重构目录结构并更新相关实现"
        return "重构目录结构并清理历史实现"
    if commit_type == "feat" and added > 0 and modified > 0:
        return f"新增 {kw} 并联动更新相关实现" if kw else "新增功能并联动更新相关实现"
    if commit_type == "docs" and added > 0 and modified > 0:
        return f"新增 {kw} 文档并统一格式规范" if kw else "新增项目文档并统一格式规范"
    if commit_type == "docs" and added > 0:
        return f"新增 {kw} 项目文档与使用指南" if kw else "新增项目文档与使用指南"

    return by_type.get(commit_type, "整理本次改动并保持仓库一致性")


def _english_subject(
    commit_type: str, added: int, modified: int, deleted: int, keywords: List[str]
) -> str:
    kw = ", ".join(keywords[:2]) if keywords else ""

    if commit_type == "feat" and kw:
        return f"add {kw}"
    if commit_type == "refactor" and kw:
        return f"refactor {kw} for maintainability"
    if commit_type == "docs" and kw:
        return f"update {kw} documentation"

    by_type = {
        "feat": "add core capability",
        "fix": "fix known issue",
        "docs": "update documentation",
        "style": "align formatting",
        "refactor": "refactor structure",
        "perf": "optimize performance",
        "test": "add test coverage",
        "chore": "tidy repository config",
        "revert": "revert risky changes",
    }
    return by_type.get(commit_type, "align current changes")


def build_commit_message_candidates(
    preview: Dict[str, Any],
    commit_rules: Dict[str, str],
    limit: int = 3,
) -> List[str]:
    """Generate commit-message candidates based on actual diff content."""
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
        subject = _contextual_subject(commit_type, preview, prefer_chinese)
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


# ── commit-message validation ──────────────────────────────────────────

def validate_commit_message(message: str) -> Dict[str, Any]:
    issues: List[str] = []
    warnings: List[str] = []
    trimmed = message.strip()
    if not trimmed:
        return {"valid": False, "issues": ["commit message must not be empty"], "warnings": warnings}
    match = COMMIT_MESSAGE_RE.match(trimmed)
    if not match:
        return {
            "valid": False,
            "issues": [
                "commit message must match '<type>(<scope>): <subject>' "
                "and use an allowed conventional type"
            ],
            "warnings": warnings,
        }
    commit_type = match.group(1)
    subject = match.group(3).strip()
    if commit_type not in VALID_COMMIT_TYPES:
        issues.append(f"unsupported commit type: {commit_type}")
    if subject.endswith(".") or subject.endswith("。"):
        issues.append("subject must not end with punctuation")
    if len(subject) > 50:
        warnings.append("subject is longer than 50 characters")
    return {"valid": not issues, "issues": issues, "warnings": warnings}
