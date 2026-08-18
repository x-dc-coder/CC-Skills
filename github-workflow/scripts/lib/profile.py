"""GitHub 用户信息管理 —— 全部经由官方 gh CLI（gh api / gh repo list）。"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .common import BootstrapError, run
from .gh import gh_api, require_login


def get_profile(config: Dict[str, Any]) -> Dict[str, Any]:
    """GET /user —— 当前认证用户完整信息。"""
    return gh_api("GET", "user")


def get_public_profile(config: Dict[str, Any], username: str) -> Dict[str, Any]:
    """GET /users/{username} —— 指定用户公开信息。"""
    return gh_api("GET", f"users/{username}")


def get_emails(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """GET /user/emails —— 邮箱列表及验证状态（需 gh 有 user 权限）。"""
    return gh_api("GET", "user/emails") or []


def get_starred(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """GET /user/starred —— 收藏的仓库列表。"""
    return gh_api("GET", "user/starred", paginate=True) or []


def get_my_repos(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """gh repo list —— 当前用户的全部仓库。"""
    login = require_login()
    res = run(
        ["gh", "repo", "list", login, "--limit", "200",
         "--json", "name,isPrivate,description,primaryLanguage"],
        check=False,
    )
    if res.returncode != 0:
        raise BootstrapError(f"gh repo list 失败: {res.stderr.strip()}")
    try:
        raw = json.loads(res.stdout)
    except json.JSONDecodeError:
        raw = []
    return [
        {
            "full_name": f"{login}/{item.get('name', '')}",
            "name": item.get("name", ""),
            "private": bool(item.get("isPrivate")),
            "description": item.get("description") or "",
            "language": (item.get("primaryLanguage") or {}).get("name") or "",
        }
        for item in raw
    ]


# ── write operations (PATCH /user) ────────────────────────────────────

UPDATEABLE_FIELDS = {
    "name": "昵称",
    "bio": "个人简介",
    "company": "公司",
    "location": "所在地",
    "blog": "个人网站",
}
FIELD_ALIASES = {"description": "bio", "website": "blog"}


def update_profile(config: Dict[str, Any], **fields: str) -> Dict[str, Any]:
    """PATCH /user —— 更新 GitHub 个人资料（gh api -X PATCH user -f ...）。

    可用字段见 UPDATEABLE_FIELDS；description→bio、website→blog 为兼容别名。
    """
    payload: Dict[str, str] = {}
    for key, value in fields.items():
        target = FIELD_ALIASES.get(key, key)
        if target in UPDATEABLE_FIELDS and value:
            payload[target] = value
    if not payload:
        raise BootstrapError(
            "no valid fields to update; allowed: " + ", ".join(UPDATEABLE_FIELDS)
        )
    return gh_api("PATCH", "user", fields=payload)


# ── formatting helpers ─────────────────────────────────────────────────

PROFILE_DISPLAY_FIELDS = [
    ("login", "用户名"),
    ("name", "昵称"),
    ("email", "邮箱"),
    ("bio", "简介"),
    ("company", "公司"),
    ("location", "所在地"),
    ("blog", "网站"),
    ("followers", "关注者"),
    ("following", "正在关注"),
    ("public_repos", "公开仓库"),
    ("created_at", "注册时间"),
    ("html_url", "主页"),
]


def format_profile(profile: Dict[str, Any]) -> str:
    lines: List[str] = []
    for key, label in PROFILE_DISPLAY_FIELDS:
        value = profile.get(key)
        if value is None or value == "" or (isinstance(value, list) and not value):
            continue
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        lines.append(f"  {label:　<6}  {value}")
    return "\n".join(lines)


def format_emails(emails: List[Dict[str, Any]]) -> str:
    if not emails:
        return "  （无邮箱记录）"
    lines: List[str] = []
    for item in emails:
        verified = bool(item.get("verified"))
        primary = bool(item.get("primary"))
        icon = "✅" if verified else "⚠️"
        tag = " [primary]" if primary else ""
        lines.append(f"  {icon} {item.get('email')}  (verified={verified}){tag}")
    return "\n".join(lines)


def format_repo_list(repos: List[Dict[str, Any]], max_show: int = 20) -> str:
    if not repos:
        return "  （无仓库）"
    lines: List[str] = []
    for repo in repos[:max_show]:
        name = repo.get("full_name") or repo.get("name", "?")
        desc = repo.get("description", "") or ""
        if len(desc) > 50:
            desc = desc[:47] + "..."
        private = "🔒" if repo.get("private") else "🌐"
        lang = repo.get("language") or ""
        lines.append(f"  {private} {name}")
        if desc:
            lines.append(f"      {lang}  {desc}" if lang else f"      {desc}")
    if len(repos) > max_show:
        lines.append(f"  ... 及其他 {len(repos) - max_show} 个仓库")
    return "\n".join(lines)
