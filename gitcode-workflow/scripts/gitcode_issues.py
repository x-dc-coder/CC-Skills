#!/usr/bin/env python3
"""GitCode Issue management module for gitcode-workflow skill."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib import error, request

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG_PATH = Path("~/.config/gitcode-workflow/config.json").expanduser()


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


def load_config(config_path: Optional[str]) -> Dict[str, Any]:
    defaults = {
        "gitcode": {
            "api_base": "https://api.gitcode.com/api/v5",
            "token_env_name": "GITCODE_TOKEN",
        }
    }
    config = deep_copy(defaults)
    path = Path(config_path).expanduser() if config_path else DEFAULT_CONFIG_PATH
    if path.exists():
        deep_merge(config, read_json_file(path))
    token_env = config.get("gitcode", {}).get("token_env_name", "GITCODE_TOKEN")
    token = os.environ.get(token_env, "")
    if token:
        config.setdefault("gitcode", {})["token"] = token
    return config


def require_token(config: Dict[str, Any]) -> str:
    token = config.get("gitcode", {}).get("token", "")
    if token:
        return token
    token_env = config.get("gitcode", {}).get("token_env_name", "GITCODE_TOKEN")
    token = os.environ.get(token_env, "")
    if token:
        return token
    raise RuntimeError(f"GitCode token not found; set {token_env}")


def api_request(api_base: str, method: str, endpoint: str, token: str, payload: Optional[Dict[str, Any]] = None, query: Optional[Dict[str, str]] = None) -> Any:
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
        raise RuntimeError(f"GitCode API error {exc.code}: {body}") from exc


def resolve_repo(config: Dict[str, Any], owner: Optional[str], repo: Optional[str]) -> tuple[str, str]:
    if owner and repo:
        return owner, repo
    remote_url = os.popen("git remote get-url gitcode 2>/dev/null || git remote get-url origin 2>/dev/null").read().strip()
    if remote_url:
        if ":" in remote_url and "@" in remote_url:
            path = remote_url.split(":", 1)[1].replace(".git", "")
        elif "/" in remote_url:
            path = remote_url.rstrip("/").split("/")[-2:]
            if len(path) == 2:
                return path[0], path[1].replace(".git", "")
        else:
            parts = remote_url.replace(".git", "").split("/")
            if len(parts) >= 2:
                return parts[-2], parts[-1]
    raise RuntimeError("Cannot resolve repository owner/repo; specify --owner and --repo or run in a git repo with gitcode remote")


# ---------------------------------------------------------------------------
# Issue operations
# ---------------------------------------------------------------------------

def list_issues(config: Dict[str, Any], owner: str, repo: str, state: Optional[str] = None, labels: Optional[str] = None, page: int = 1, per_page: int = 20) -> List[Dict[str, Any]]:
    token = require_token(config)
    query: Dict[str, str] = {"access_token": token, "page": str(page), "per_page": str(per_page)}
    if state:
        query["state"] = state
    if labels:
        query["labels"] = labels
    return api_request(config["gitcode"]["api_base"], "GET", f"/repos/{owner}/{repo}/issues", token, query=query) or []


def get_issue(config: Dict[str, Any], owner: str, repo: str, number: int) -> Dict[str, Any]:
    token = require_token(config)
    return api_request(config["gitcode"]["api_base"], "GET", f"/repos/{owner}/{repo}/issues/{number}", token) or {}


def create_issue(config: Dict[str, Any], owner: str, repo: str, title: str, body: str = "", labels: Optional[str] = None, assignee: Optional[str] = None) -> Dict[str, Any]:
    token = require_token(config)
    payload: Dict[str, Any] = {"title": title, "body": body, "repo": repo}
    if labels:
        payload["labels"] = labels
    if assignee:
        payload["assignee"] = assignee
    return api_request(config["gitcode"]["api_base"], "POST", f"/repos/{owner}/{repo}/issues", token, payload=payload) or {}


def update_issue(config: Dict[str, Any], owner: str, repo: str, number: int, title: Optional[str] = None, body: Optional[str] = None, state: Optional[str] = None, labels: Optional[str] = None, state_event: Optional[str] = None) -> Dict[str, Any]:
    token = require_token(config)
    payload: Dict[str, Any] = {"repo": repo}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if state is not None:
        payload["state"] = state
    if labels is not None:
        payload["labels"] = labels
    if state_event is not None:
        payload["state_event"] = state_event
    return api_request(config["gitcode"]["api_base"], "PATCH", f"/repos/{owner}/{repo}/issues/{number}", token, payload=payload) or {}


def close_issue(config: Dict[str, Any], owner: str, repo: str, number: int) -> Dict[str, Any]:
    token = require_token(config)
    # Get current issue to preserve title
    current = get_issue(config, owner, repo, number)
    title = current.get("title", "")
    payload = {"repo": repo, "state_event": "close", "title": title}
    return api_request(config["gitcode"]["api_base"], "PATCH", f"/repos/{owner}/{repo}/issues/{number}", token, payload=payload) or {}


def reopen_issue(config: Dict[str, Any], owner: str, repo: str, number: int) -> Dict[str, Any]:
    token = require_token(config)
    current = get_issue(config, owner, repo, number)
    title = current.get("title", "")
    payload = {"repo": repo, "state_event": "reopen", "title": title}
    return api_request(config["gitcode"]["api_base"], "PATCH", f"/repos/{owner}/{repo}/issues/{number}", token, payload=payload) or {}


# ---------------------------------------------------------------------------
# Issue comments
# ---------------------------------------------------------------------------

def list_issue_comments(config: Dict[str, Any], owner: str, repo: str, number: int, page: int = 1, per_page: int = 20) -> List[Dict[str, Any]]:
    token = require_token(config)
    query = {"access_token": token, "page": str(page), "per_page": str(per_page)}
    return api_request(config["gitcode"]["api_base"], "GET", f"/repos/{owner}/{repo}/issues/{number}/comments", token, query=query) or []


def create_issue_comment(config: Dict[str, Any], owner: str, repo: str, number: int, body: str) -> Dict[str, Any]:
    token = require_token(config)
    return api_request(config["gitcode"]["api_base"], "POST", f"/repos/{owner}/{repo}/issues/{number}/comments", token, payload={"body": body}) or {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GitCode Issue management")
    parser.add_argument("--config", default=None, help="Config file path")
    parser.add_argument("--owner", default=None, help="Repository owner/namespace")
    parser.add_argument("--repo", default=None, help="Repository name")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    list_parser = subparsers.add_parser("list", help="List issues")
    list_parser.add_argument("--state", choices=["open", "closed", "all"], default="open")
    list_parser.add_argument("--labels", default=None)
    list_parser.add_argument("--page", type=int, default=1)
    list_parser.add_argument("--per-page", type=int, default=20)
    list_parser.add_argument("--json", action="store_true", help="Output JSON")

    # get
    get_parser = subparsers.add_parser("get", help="Get a single issue")
    get_parser.add_argument("number", type=int, help="Issue number")
    get_parser.add_argument("--json", action="store_true", help="Output JSON")

    # create
    create_parser = subparsers.add_parser("create", help="Create an issue")
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--body", default="")
    create_parser.add_argument("--labels", default=None)
    create_parser.add_argument("--assignee", default=None)
    create_parser.add_argument("--json", action="store_true", help="Output JSON")

    # update
    update_parser = subparsers.add_parser("update", help="Update an issue")
    update_parser.add_argument("number", type=int)
    update_parser.add_argument("--title", default=None)
    update_parser.add_argument("--body", default=None)
    update_parser.add_argument("--state", choices=["open", "closed"], default=None)
    update_parser.add_argument("--labels", default=None)
    update_parser.add_argument("--json", action="store_true", help="Output JSON")

    # close
    close_parser = subparsers.add_parser("close", help="Close an issue")
    close_parser.add_argument("number", type=int)
    close_parser.add_argument("--json", action="store_true", help="Output JSON")

    # reopen
    reopen_parser = subparsers.add_parser("reopen", help="Reopen an issue")
    reopen_parser.add_argument("number", type=int)
    reopen_parser.add_argument("--json", action="store_true", help="Output JSON")

    # comments
    comments_parser = subparsers.add_parser("comments", help="List issue comments")
    comments_parser.add_argument("number", type=int)
    comments_parser.add_argument("--json", action="store_true", help="Output JSON")

    # comment-create
    comment_create_parser = subparsers.add_parser("comment-create", help="Create an issue comment")
    comment_create_parser.add_argument("number", type=int)
    comment_create_parser.add_argument("--body", required=True)
    comment_create_parser.add_argument("--json", action="store_true", help="Output JSON")

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
    config = load_config(args.config)
    owner, repo = resolve_repo(config, args.owner, args.repo)

    try:
        if args.command == "list":
            result = list_issues(config, owner, repo, state=args.state, labels=args.labels, page=args.page, per_page=args.per_page)
        elif args.command == "get":
            result = get_issue(config, owner, repo, args.number)
        elif args.command == "create":
            result = create_issue(config, owner, repo, title=args.title, body=args.body, labels=args.labels, assignee=args.assignee)
        elif args.command == "update":
            result = update_issue(config, owner, repo, args.number, title=args.title, body=args.body, state=args.state, labels=args.labels)
        elif args.command == "close":
            result = close_issue(config, owner, repo, args.number)
        elif args.command == "reopen":
            result = reopen_issue(config, owner, repo, args.number)
        elif args.command == "comments":
            result = list_issue_comments(config, owner, repo, args.number)
        elif args.command == "comment-create":
            result = create_issue_comment(config, owner, repo, args.number, body=args.body)
        else:
            raise RuntimeError(f"Unknown command: {args.command}")

        emit({"owner": owner, "repo": repo, "command": args.command, "result": result}, getattr(args, 'json', False))
        return 0
    except RuntimeError as exc:
        emit({"error": str(exc)}, args.json)
        return 1


if __name__ == "__main__":
    sys.exit(main())
