"""Review manifest — snapshot, verify, stage, clear, commit-and-push."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import (
    REVIEW_MANIFEST_FILENAME,
    BootstrapError,
    log_info,
    read_json_file,
    sha256_file,
)
from .git import head_commit_or_none, repo_current_branch, run


def review_manifest_path(project: Path, override: Optional[str]) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    return (project / ".git" / REVIEW_MANIFEST_FILENAME).resolve()


def build_review_manifest(
    project: Path, preview: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    from .preview import build_publish_preview

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
    files = sorted(
        files,
        key=lambda item: (item.get("old_path") or "", item["path"], item["kind"], item["raw"]),
    )
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
    snapshot_hash = hashlib.sha256(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
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


def write_review_manifest(
    project: Path,
    override: Optional[str],
    preview: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    manifest = build_review_manifest(project, preview)
    path = review_manifest_path(project, override)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
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


def verify_review_manifest(
    project: Path, override: Optional[str]
) -> Dict[str, Any]:
    from .preview import build_publish_preview

    project = project.resolve()
    path = review_manifest_path(project, override)
    stored = load_review_manifest(path)
    stored_project = stored.get("project_path")
    if stored_project and Path(stored_project).expanduser().resolve() != project:
        raise BootstrapError(
            f"review manifest belongs to a different project: {stored_project}"
        )
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


def commit_and_push(
    project: Path,
    remote_name: str,
    commit_message: str,
    review_manifest: Dict[str, Any],
    manifest_path: Path,
) -> Dict[str, Any]:
    from .preview import validate_commit_message

    validation = validate_commit_message(commit_message)
    if not validation["valid"]:
        raise BootstrapError(
            "invalid commit message: " + "; ".join(validation["issues"])
        )
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
    commit_hash = run(
        ["git", "rev-parse", "HEAD"], cwd=project, check=True
    ).stdout.strip()
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
