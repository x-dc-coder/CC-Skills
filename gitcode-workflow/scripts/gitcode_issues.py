#!/usr/bin/env python3
"""GitCode Issue management CLI — thin wrapper over shared lib modules."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Reuse shared lib modules — no code duplication.
from lib.api import api_request
from lib.config import load_config, require_token


def resolve_repo(
    config: Dict[str, Any], owner: Optional[str], repo: Optional[str]
) -> tuple[str, str]:
    if owner and repo:
        return owner, repo
    remote_url = os.popen(
        "git remote get-url gitcode 2>/dev/null || git remote get-url origin 2>/dev/null"
    ).read().strip()
    if remote_url:
        if ":" in remote_url and "@" in remote_url:
            path = remote_url.split(":", 1)[1].replace(".git", "")
            if "/" in path:
                parts = path.split("/")
                if len(parts) >= 2:
                    return parts[0], parts[1]
        elif "/" in remote_url:
            path = remote_url.rstrip("/").split("/")[-2:]
            if len(path) == 2:
                return path[0], path[1].replace(".git", "")
        else:
            parts = remote_url.replace(".git", "").split("/")
            if len(parts) >= 2:
                return parts[-2], parts[-1]
    raise RuntimeError(
        "Cannot resolve repository owner/repo; "
        "specify --owner and --repo or run in a git repo with gitcode remote"
    )


# ── Issue operations ────────────────────────────────────────────────────

def list_issues(
    config: Dict[str, Any], owner: str, repo: str,
    state: Optional[str] = None, labels: Optional[str] = None,
    page: int = 1, per_page: int = 20,
) -> list:
    token = require_token(config)
    query = {"access_token": token, "page": str(page), "per_page": str(per_page)}
    if state:
        query["state"] = state
    if labels:
        query["labels"] = labels
    return (
        api_request(
            config["gitcode"]["api_base"], "GET",
            f"/repos/{owner}/{repo}/issues", token, query=query,
        )
        or []
    )


def get_issue(config: Dict[str, Any], owner: str, repo: str, number: int) -> dict:
    token = require_token(config)
    return (
        api_request(
            config["gitcode"]["api_base"], "GET",
            f"/repos/{owner}/{repo}/issues/{number}", token,
        )
        or {}
    )


def _unescape_body(text: str) -> str:
    return text.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")


def create_issue(
    config: Dict[str, Any], owner: str, repo: str,
    title: str, body: str = "", labels: Optional[str] = None,
    assignee: Optional[str] = None,
) -> dict:
    token = require_token(config)
    payload: Dict[str, Any] = {"title": title, "body": _unescape_body(body), "repo": repo}
    if labels:
        payload["labels"] = labels
    if assignee:
        payload["assignee"] = assignee
    return (
        api_request(
            config["gitcode"]["api_base"], "POST",
            f"/repos/{owner}/issues", token, payload=payload,
        )
        or {}
    )


def update_issue(
    config: Dict[str, Any], owner: str, repo: str, number: int,
    title: Optional[str] = None, body: Optional[str] = None,
    state: Optional[str] = None, labels: Optional[str] = None,
) -> dict:
    token = require_token(config)
    payload: Dict[str, Any] = {"repo": repo}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = _unescape_body(body)
    if state is not None:
        payload["state"] = {"closed": "close", "open": "reopen"}.get(state, state)
    if labels is not None:
        payload["labels"] = labels
    return (
        api_request(
            config["gitcode"]["api_base"], "PATCH",
            f"/repos/{owner}/issues/{number}", token, payload=payload,
        )
        or {}
    )


def close_issue(config: Dict[str, Any], owner: str, repo: str, number: int) -> dict:
    token = require_token(config)
    return (
        api_request(
            config["gitcode"]["api_base"], "PATCH",
            f"/repos/{owner}/issues/{number}", token,
            payload={"repo": repo, "state": "close"},
        )
        or {}
    )


def reopen_issue(config: Dict[str, Any], owner: str, repo: str, number: int) -> dict:
    token = require_token(config)
    return (
        api_request(
            config["gitcode"]["api_base"], "PATCH",
            f"/repos/{owner}/issues/{number}", token,
            payload={"repo": repo, "state": "reopen"},
        )
        or {}
    )


def list_issue_comments(
    config: Dict[str, Any], owner: str, repo: str,
    number: int, page: int = 1, per_page: int = 20,
) -> list:
    token = require_token(config)
    query = {"access_token": token, "page": str(page), "per_page": str(per_page)}
    return (
        api_request(
            config["gitcode"]["api_base"], "GET",
            f"/repos/{owner}/{repo}/issues/{number}/comments", token, query=query,
        )
        or []
    )


def create_issue_comment(
    config: Dict[str, Any], owner: str, repo: str,
    number: int, body: str,
) -> dict:
    token = require_token(config)
    return (
        api_request(
            config["gitcode"]["api_base"], "POST",
            f"/repos/{owner}/{repo}/issues/{number}/comments", token,
            payload={"body": _unescape_body(body)},
        )
        or {}
    )


# ── CLI ─────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GitCode Issue management")
    parser.add_argument("--config", default=None, help="Config file path")
    parser.add_argument("--owner", default=None, help="Repository owner/namespace")
    parser.add_argument("--repo", default=None, help="Repository name")

    subparsers = parser.add_subparsers(dest="command", required=True)

    lp = subparsers.add_parser("list", help="List issues")
    lp.add_argument("--state", choices=["open", "closed", "all"], default="open")
    lp.add_argument("--labels", default=None)
    lp.add_argument("--page", type=int, default=1)
    lp.add_argument("--per-page", type=int, default=20)
    lp.add_argument("--json", action="store_true")

    gp = subparsers.add_parser("get", help="Get a single issue")
    gp.add_argument("number", type=int)
    gp.add_argument("--json", action="store_true")

    cp = subparsers.add_parser("create", help="Create an issue")
    cp.add_argument("--title", required=True)
    cp.add_argument("--body", default="")
    cp.add_argument("--labels", default=None)
    cp.add_argument("--assignee", default=None)
    cp.add_argument("--json", action="store_true")

    up = subparsers.add_parser("update", help="Update an issue")
    up.add_argument("number", type=int)
    up.add_argument("--title", default=None)
    up.add_argument("--body", default=None)
    up.add_argument("--state", choices=["open", "closed"], default=None)
    up.add_argument("--labels", default=None)
    up.add_argument("--json", action="store_true")

    clp = subparsers.add_parser("close", help="Close an issue")
    clp.add_argument("number", type=int)
    clp.add_argument("--json", action="store_true")

    rp = subparsers.add_parser("reopen", help="Reopen an issue")
    rp.add_argument("number", type=int)
    rp.add_argument("--json", action="store_true")

    cop = subparsers.add_parser("comments", help="List issue comments")
    cop.add_argument("number", type=int)
    cop.add_argument("--json", action="store_true")

    ccp = subparsers.add_parser("comment-create", help="Create an issue comment")
    ccp.add_argument("number", type=int)
    ccp.add_argument("--body", required=True)
    ccp.add_argument("--json", action="store_true")

    return parser


def emit(result: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if isinstance(result, list):
        for item in result:
            num = item.get("number", "?")
            title = item.get("title", "")
            state = item.get("state", "")
            print(f"#{num} [{state}] {title}")
    elif isinstance(result, dict):
        for key, value in result.items():
            print(f"{key}: {value}")
    else:
        print(result)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config, _, _ = load_config(args.config)
    owner, repo = resolve_repo(config, args.owner, args.repo)

    try:
        if args.command == "list":
            result = list_issues(config, owner, repo, args.state, args.labels, args.page, args.per_page)
        elif args.command == "get":
            result = get_issue(config, owner, repo, args.number)
        elif args.command == "create":
            result = create_issue(config, owner, repo, args.title, args.body, args.labels, args.assignee)
        elif args.command == "update":
            result = update_issue(config, owner, repo, args.number, args.title, args.body, args.state, args.labels)
        elif args.command == "close":
            result = close_issue(config, owner, repo, args.number)
        elif args.command == "reopen":
            result = reopen_issue(config, owner, repo, args.number)
        elif args.command == "comments":
            result = list_issue_comments(config, owner, repo, args.number)
        elif args.command == "comment-create":
            result = create_issue_comment(config, owner, repo, args.number, args.body)
        else:
            raise RuntimeError(f"Unknown command: {args.command}")

        emit({"owner": owner, "repo": repo, "command": args.command, "result": result}, getattr(args, "json", False))
        return 0
    except RuntimeError as exc:
        emit({"error": str(exc)}, args.json)
        return 1


if __name__ == "__main__":
    sys.exit(main())
