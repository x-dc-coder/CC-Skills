#!/usr/bin/env python3
"""Bootstrap local git projects, plan layered commits, and optional GitCode remotes safely.

All business logic lives in the lib/ modules; this file is a thin CLI orchestrator.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

# All heavy-lifting is delegated to the lib/ package.
from lib.adopt import build_adoption_strategy
from lib.common import BootstrapError, expand_path, log_info
from lib.config import DEFAULTS, load_config
from lib.git import (
    detect_stacks,
    ensure_git_available,
    init_repo,
    resolve_commit_rules,
    set_git_identity,
    update_gitignore,
    update_info_exclude,
)
from lib.manifest import (
    commit_and_push,
    verify_review_manifest,
    write_review_manifest,
)
from lib.preview import build_commit_message_candidates, build_publish_preview
from lib.profile import (
    format_emails,
    format_profile,
    format_repo_list,
    get_emails,
    get_my_repos,
    get_profile,
    get_public_profile,
    get_starred,
    update_profile,
)
from lib.remote import ensure_remote_exists
from lib.safety import classify_sensitive_files


# ── CLI override helpers ────────────────────────────────────────────────

def apply_cli_overrides(config: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    for attr, path in [
        ("user_name", ("git", "user_name")),
        ("user_email", ("git", "user_email")),
        ("config_scope", ("git", "config_scope")),
        ("commit_rules_path", ("git", "commit_rules_path")),
        ("remote_name", ("git", "remote_name")),
        ("namespace", ("gitcode", "namespace")),
        ("ssh_title", ("ssh", "title")),
        ("ssh_comment", ("ssh", "comment")),
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


def common_bootstrap(project: Path, config: Dict[str, Any]) -> Dict[str, Any]:
    ensure_git_available()
    project = project.resolve()
    repo_initialized = init_repo(project, config["git"]["default_branch"])
    identity = set_git_identity(
        project,
        config["git"]["config_scope"],
        config["git"]["user_name"],
        config["git"]["user_email"],
    )
    stacks = detect_stacks(project)
    gitignore_state = update_gitignore(
        project, stacks, bool(config["safety"]["auto_update_gitignore"])
    )
    info_exclude_state = update_info_exclude(
        project, bool(config["safety"]["auto_update_info_exclude"])
    )
    commit_rules = resolve_commit_rules(project, config["git"]["commit_rules_path"])
    safety = classify_sensitive_files(project)
    return {
        "project_path": str(project),
        "repo_initialized": repo_initialized,
        "identity": identity,
        "detected_stacks": stacks,
        "gitignore": gitignore_state,
        "info_exclude": info_exclude_state,
        "commit_rules": commit_rules,
        "safety_scan": safety,
    }


# ── CLI arg parser ─────────────────────────────────────────────────────

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

    parser = argparse.ArgumentParser(
        description="Bootstrap Git and GitCode setup for local projects"
    )
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

    # ── profile ──────────────────────────────────────────────────────
    profile_parser = subparsers.add_parser("profile", parents=[parent])
    profile_parser.add_argument(
        "--action", required=True,
        choices=["show", "emails", "starred", "repos", "update"],
        help="操作类型"
    )
    profile_parser.add_argument("--public", default=None, help="查看指定用户的公开信息")
    profile_parser.add_argument("--description", default=None, help="个人简介")
    profile_parser.add_argument("--company", default=None, help="公司")
    profile_parser.add_argument("--location", default=None, help="所在地")
    profile_parser.add_argument("--website", default=None, help="个人网站")
    profile_parser.add_argument("--github-account", default=None, help="GitHub 账号")

    return parser


# ── output ─────────────────────────────────────────────────────────────

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
        print("recommended_order:", ", ".join(
            result["adoption_strategy"].get("recommended_order", [])
        ))
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
        pub = result["publish"]
        print(f"publish: committed={pub.get('committed')} pushed={pub.get('pushed')}")
    if result.get("formatted"):
        print(result["formatted"])
    if result.get("warnings"):
        print("warnings:")
        for warning in result["warnings"]:
            print(f"- {warning}")


# ── main ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config, config_path_used, warnings = load_config(args.config)
    config = apply_cli_overrides(config, args)
    project = Path(args.project).expanduser()

    try:
        log_info(f"start command={args.command} project={project}")

        # ── adopt-existing-project (no bootstrap needed) ──────────────
        if args.command == "adopt-existing-project":
            strategy = build_adoption_strategy(
                project, config, max_layers=max(1, args.max_layers)
            )
            result = {
                "command": args.command,
                "project_path": str(project.resolve()),
                "config_path_used": config_path_used,
                "warnings": warnings,
                "adoption_strategy": strategy,
            }
            emit(result, args.json)
            log_info("adopt-existing-project completed")
            return 0

        # ── profile (no bootstrap needed) ────────────────────────────
        if args.command == "profile":
            if args.action == "show":
                if args.public:
                    data = get_public_profile(config, args.public)
                else:
                    data = get_profile(config)
                result = {"command": "profile show", "profile": data,
                          "formatted": format_profile(data)}
            elif args.action == "emails":
                emails = get_emails(config)
                result = {"command": "profile emails", "emails": emails,
                          "formatted": format_emails(emails)}
            elif args.action == "starred":
                repos = get_starred(config)
                result = {"command": "profile starred", "repos": repos,
                          "formatted": format_repo_list(repos)}
            elif args.action == "repos":
                repos = get_my_repos(config)
                result = {"command": "profile repos", "repos": repos,
                          "formatted": format_repo_list(repos)}
            elif args.action == "update":
                fields = {}
                for key in ["description", "company", "location", "website"]:
                    val = getattr(args, key, None)
                    if val:
                        fields[key] = val
                if hasattr(args, "github_account") and args.github_account:
                    fields["github_account"] = args.github_account
                data = update_profile(config, **fields)
                result = {"command": "profile update", "updated": data,
                          "formatted": format_profile(get_profile(config))}
            else:
                raise BootstrapError(f"unknown profile action: {args.action}")
            result.update({"config_path_used": config_path_used, "warnings": warnings})
            emit(result, args.json)
            log_info(f"profile {args.action} completed")
            return 0

        # ── all other commands share bootstrap ────────────────────────
        result = common_bootstrap(project, config)
        result.update({
            "command": args.command,
            "config_path_used": config_path_used,
            "warnings": warnings,
        })

        if args.command == "local-only":
            emit(result, args.json)
            log_info("local-only completed")
            return 0

        if args.command == "preview":
            result["preview"] = build_publish_preview(project.resolve())
            result["commit_message_candidates"] = build_commit_message_candidates(
                result["preview"], result["commit_rules"], limit=3
            )
            result["review_manifest"] = write_review_manifest(
                project.resolve(), args.review_manifest, result["preview"]
            )
            emit(result, args.json)
            log_info("preview completed and review manifest generated")
            return 0

        if args.command == "create-remote":
            result["remote"] = ensure_remote_exists(
                project.resolve(), config,
                args.repo_name, args.description,
                bool(args.private), args.remote_name,
            )
            emit(result, args.json)
            log_info("create-remote completed")
            return 0

        if args.command == "publish":
            manifest_state = verify_review_manifest(
                project.resolve(), args.review_manifest
            )
            result["preview"] = manifest_state["preview"]
            result["commit_message_candidates"] = build_commit_message_candidates(
                result["preview"], result["commit_rules"], limit=3
            )
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
                    "working tree changed after preview; "
                    "rerun preview and review the new file set before publish"
                )
            high_risk = result["safety_scan"]["high_risk"]
            if high_risk and config["safety"]["abort_on_high_risk"]:
                raise BootstrapError(
                    "refusing to publish because high-risk files are present "
                    "and not ignored: " + ", ".join(high_risk)
                )
            result["remote"] = ensure_remote_exists(
                project.resolve(), config,
                args.repo_name, args.description,
                bool(args.private), args.remote_name,
            )
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
        error_result = {
            "command": args.command,
            "project_path": str(project.resolve()),
            "error": str(exc),
            "config_path_used": config_path_used,
            "warnings": warnings,
        }
        emit(error_result, args.json)
        return 2


if __name__ == "__main__":
    sys.exit(main())
