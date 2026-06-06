"""GitCode user profile management — read profile, emails, starred repos."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .api import api_request
from .common import BootstrapError
from .config import require_token


def get_profile(config: Dict[str, Any]) -> Dict[str, Any]:
    """GET /user — 获取当前认证用户的完整个人信息."""
    return api_request(
        config["gitcode"]["api_base"], "GET", "/user", require_token(config)
    )


def get_public_profile(config: Dict[str, Any], username: str) -> Dict[str, Any]:
    """GET /users/{username} — 获取指定用户的公开信息."""
    return api_request(
        config["gitcode"]["api_base"], "GET", f"/users/{username}",
        require_token(config),
    )


def get_emails(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """GET /emails — 获取当前用户的邮箱列表及验证状态."""
    result = api_request(
        config["gitcode"]["api_base"], "GET", "/emails", require_token(config)
    )
    return result or []


def get_starred(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """GET /user/starred — 获取当前用户收藏的仓库列表."""
    result = api_request(
        config["gitcode"]["api_base"], "GET", "/user/starred", require_token(config)
    )
    return result or []


def get_my_repos(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """GET /user/repos — 获取当前用户的所有仓库."""
    result = api_request(
        config["gitcode"]["api_base"], "GET", "/user/repos", require_token(config),
        query={"type": "all", "sort": "updated", "per_page": "50"},
    )
    return result or []


# ── write operations (PATCH /user) ────────────────────────────────────

UPDATEABLE_FIELDS = {
    "description": "个人简介",
    "company": "公司",
    "location": "所在地",
    "website": "个人网站",
    "github_account": "GitHub 账号",
}


def update_profile(config: Dict[str, Any], **fields: str) -> Dict[str, Any]:
    """PATCH /user — 更新个人信息。

    当前 GitCode API 可能返回「维护期」错误，此函数会透传上游错误。
    可用字段见 UPDATEABLE_FIELDS。
    """
    payload = {k: v for k, v in fields.items() if k in UPDATEABLE_FIELDS and v}
    if not payload:
        raise BootstrapError("no valid fields to update; allowed: " + ", ".join(UPDATEABLE_FIELDS))
    return api_request(
        config["gitcode"]["api_base"], "PATCH", "/user",
        require_token(config), payload=payload,
    )


# ── formatting helpers ─────────────────────────────────────────────────

PROFILE_DISPLAY_FIELDS = [
    ("login", "用户名"),
    ("name", "昵称"),
    ("email", "邮箱"),
    ("description", "简介"),
    ("company", "公司"),
    ("location", "所在地"),
    ("website", "网站"),
    ("github_account", "GitHub"),
    ("blog", "博客"),
    ("top_languages", "主要语言"),
    ("followers", "关注者"),
    ("following", "正在关注"),
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
        state = item.get("state", "unknown")
        icon = "✅" if state == "confirmed" else "⚠️"
        lines.append(f"  {icon} {item['email']}  [{state}]")
    return "\n".join(lines)


def format_repo_list(repos: List[Dict[str, Any]], max_show: int = 20) -> str:
    if not repos:
        return "  （无仓库）"
    lines: List[str] = []
    for repo in repos[:max_show]:
        name = repo.get("full_name") or repo.get("path") or repo.get("name", "?")
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
