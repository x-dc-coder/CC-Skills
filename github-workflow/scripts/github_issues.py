#!/usr/bin/env python3
"""GitHub Issue management CLI —— 薄封装官方 gh issue 命令。

设计原则：不实现 GitHub API 客户端，直接调用 gh 官方子命令，
本脚本只负责参数拼装、JSON 解析与统一输出。
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Tuple

from lib.common import BootstrapError, run
from lib.gh import gh_json


def _parse_github_repo(url: str) -> Optional[Tuple[str, str]]:
    path = url.strip()
    if path.endswith(".git"):
        path = path[:-4]
    if "@" in path and ":" in path:
        path = path.split(":", 1)[1]
    elif "github.com/" in path:
        path = path.split("github.com/", 1)[1]
    elif "/" in path and "github.com" in path:
        path = path.split("github.com/", 1)[1]
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None


def resolve_repo(owner: Optional[str], repo: Optional[str]) -> Tuple[str, str]:
    if owner and repo:
        return owner, repo
    res = run(["git", "remote", "-v"], check=False)
    best: Optional[str] = None
    for line in res.stdout.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        name, url = line.split("\t", 1)
        url = url.split(" ", 1)[0]
        if "github.com" not in url:
            continue
        if name == "origin":
            best = url
            break
        best = best or url
    if best:
        parsed = _parse_github_repo(best)
        if parsed:
            return parsed
    raise RuntimeError(
        "无法从 git remote 推断 GitHub owner/repo；"
        "请显式指定 --owner 和 --repo，或在含 GitHub remote 的仓库目录下运行"
    )


# ── Issue operations（全部经 gh issue）──────────────────────────────────

def list_issues(owner: str, repo: str, state: str, labels: Optional[str], limit: int = 100) -> List[Dict[str, Any]]:
    cmd = ["issue", "list", "--repo", f"{owner}/{repo}", "--state", state,
           "--limit", str(limit), "--json", "number,title,state,labels,assignees,createdAt"]
    if labels:
        cmd += ["--label", labels]
    return gh_json(cmd) or []


def get_issue(owner: str, repo: str, number: int) -> Dict[str, Any]:
    return (
        gh_json(["issue", "view", str(number), "--repo", f"{owner}/{repo}",
                 "--json", "number,title,state,body,labels,assignees,createdAt,url"])
        or {}
    )


def _unescape_body(text: str) -> str:
    return text.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")


def create_issue(
    owner: str, repo: str, title: str, body: str = "",
    labels: Optional[str] = None, assignee: Optional[str] = None,
) -> Dict[str, Any]:
    cmd = ["issue", "create", "--repo", f"{owner}/{repo}", "--title", title]
    if body:
        cmd += ["--body", _unescape_body(body)]
    if labels:
        cmd += ["--label", labels]
    if assignee:
        cmd += ["--assignee", assignee]
    res = run(["gh", *cmd], check=False)
    if res.returncode != 0:
        raise BootstrapError(f"gh issue create 失败: {res.stderr.strip()}")
    return {"url": res.stdout.strip()}


def update_issue(
    owner: str, repo: str, number: int,
    title: Optional[str] = None, body: Optional[str] = None,
    labels: Optional[str] = None,
) -> Dict[str, Any]:
    cmd = ["issue", "edit", str(number), "--repo", f"{owner}/{repo}"]
    if title is not None:
        cmd += ["--title", title]
    if body is not None:
        cmd += ["--body", _unescape_body(body)]
    if labels is not None:
        # labels 以逗号分隔；gh 的 --add-label 可多次传入
        for label in [l.strip() for l in labels.split(",") if l.strip()]:
            cmd += ["--add-label", label]
    res = run(["gh", *cmd], check=False)
    if res.returncode != 0:
        raise BootstrapError(f"gh issue edit 失败: {res.stderr.strip()}")
    return {"updated": number}


def close_issue(owner: str, repo: str, number: int) -> Dict[str, Any]:
    res = run(["gh", "issue", "close", str(number), "--repo", f"{owner}/{repo}"], check=False)
    if res.returncode != 0:
        raise BootstrapError(f"gh issue close 失败: {res.stderr.strip()}")
    return {"closed": number}


def reopen_issue(owner: str, repo: str, number: int) -> Dict[str, Any]:
    res = run(["gh", "issue", "reopen", str(number), "--repo", f"{owner}/{repo}"], check=False)
    if res.returncode != 0:
        raise BootstrapError(f"gh issue reopen 失败: {res.stderr.strip()}")
    return {"reopened": number}


def list_issue_comments(owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
    data = gh_json(["issue", "view", str(number), "--repo", f"{owner}/{repo}",
                    "--json", "comments"]) or {}
    return data.get("comments") or []


def create_issue_comment(owner: str, repo: str, number: int, body: str) -> Dict[str, Any]:
    res = run(
        ["gh", "issue", "comment", str(number), "--repo", f"{owner}/{repo}", "--body", _unescape_body(body)],
        check=False,
    )
    if res.returncode != 0:
        raise BootstrapError(f"gh issue comment 失败: {res.stderr.strip()}")
    return {"comment": res.stdout.strip()}


# ── CLI ─────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GitHub Issue management (gh issue)")
    parser.add_argument("--owner", default=None, help="Repository owner/namespace")
    parser.add_argument("--repo", default=None, help="Repository name")

    subparsers = parser.add_subparsers(dest="command", required=True)

    lp = subparsers.add_parser("list", help="List issues")
    lp.add_argument("--state", choices=["open", "closed", "all"], default="open")
    lp.add_argument("--labels", default=None)
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
            if isinstance(value, (list, dict)):
                print(f"{key}: {json.dumps(value, ensure_ascii=False)}")
            else:
                print(f"{key}: {value}")
    else:
        print(result)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    owner, repo = resolve_repo(args.owner, args.repo)

    try:
        if args.command == "list":
            result = list_issues(owner, repo, args.state, args.labels)
        elif args.command == "get":
            result = get_issue(owner, repo, args.number)
        elif args.command == "create":
            result = create_issue(owner, repo, args.title, args.body, args.labels, args.assignee)
        elif args.command == "update":
            result = update_issue(owner, repo, args.number, args.title, args.body, args.labels)
        elif args.command == "close":
            result = close_issue(owner, repo, args.number)
        elif args.command == "reopen":
            result = reopen_issue(owner, repo, args.number)
        elif args.command == "comments":
            result = list_issue_comments(owner, repo, args.number)
        elif args.command == "comment-create":
            result = create_issue_comment(owner, repo, args.number, args.body)
        else:
            raise RuntimeError(f"Unknown command: {args.command}")

        emit({"owner": owner, "repo": repo, "command": args.command, "result": result},
             getattr(args, "json", False))
        return 0
    except (RuntimeError, BootstrapError) as exc:
        emit({"error": str(exc)}, args.json)
        return 1


if __name__ == "__main__":
    sys.exit(main())
