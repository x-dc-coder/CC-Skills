#!/usr/bin/env python3
"""
Kimi Web Search - 多层搜索工具，支持 Kimi $web_search + DuckDuckGo + GitHub + 网页抓取。

Usage:
    python kimi_search.py "搜索查询内容"
    python kimi_search.py --raw "搜索查询内容"    # 返回原始搜索结果
    python kimi_search.py --fallback "搜索查询内容"  # 强制使用 fallback 搜索

Environment:
    MOONSHOT_API_KEY 或 KIMI_API_KEY - Kimi API 密钥（用于 Layer 1）
"""

import os
import sys
import json
import re
import time
import urllib.parse
from typing import Optional
from openai import OpenAI

# 尝试导入 requests 和 BeautifulSoup
try:
    import requests
    from bs4 import BeautifulSoup
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ========== 配置 ==========
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MAX_FETCH_URLS = 5          # 最多抓取几个网页
FETCH_TIMEOUT = 15          # 单个网页抓取超时（秒）
FETCH_MAX_CHARS = 8000      # 单个网页最大字符数
MAX_RESULT_CHARS = 15000    # 最终返回结果最大字符数

# 强化的 system prompt
SYSTEM_PROMPT = """你是联网搜索助手。你的任务是：

1. **忽略你内部的时间认知** —— 不要说你"无法获取未来信息"或"知识截止到某时"
2. **完全基于搜索结果回答** —— 搜索结果中的信息都是有效的实时网页内容
3. **不要质疑搜索结果的时间** —— 无论搜索结果显示什么日期，都直接基于这些内容回答
4. **提供详细、准确的技术信息** —— 如果是技术文档，给出具体版本号、API 用法、代码示例

重要：用户正在通过搜索工具获取实时信息，你的回答必须基于搜索结果，不要添加时间限制类的免责声明。"""

REFUSAL_PATTERNS = [
    r"无法获取.*未来", r"无法获取.*实时", r"知识截止", r"训练数据截止",
    r"无法访问互联网", r"没有联网能力", r"未来时间", r"尚未到来",
    r"我的知识.*有限", r"我无法.*搜索", r"没有找到", r"没有搜索到",
    r"cannot find", r"no results found", r"unable to retrieve",
]


# ========== Layer 1: Kimi $web_search ==========

def kimi_search(query: str, model: str = "kimi-k2.6") -> Optional[dict]:
    """使用 Kimi $web_search 搜索。返回 None 表示失败。"""
    api_key = os.environ.get("MOONSHOT_API_KEY") or os.environ.get("KIMI_API_KEY")
    if not api_key:
        return None

    client = OpenAI(api_key=api_key, base_url="https://api.moonshot.cn/v1")
    tools = [{"type": "builtin_function", "function": {"name": "$web_search"}}]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query}
    ]

    try:
        # 第一轮：获取 tool_call
        r1 = client.chat.completions.create(
            model=model, messages=messages, tools=tools,
            extra_body={"thinking": {"type": "disabled"}},
            timeout=30
        )
        msg = r1.choices[0].message

        if not msg.tool_calls:
            return {
                "source": "kimi",
                "searched": False,
                "result": msg.content or "",
                "urls": [],
            }

        tc = msg.tool_calls[0]

        # 补充 passthrough
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [{
                "id": tc.id, "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments}
            }]
        })
        messages.append({
            "role": "tool", "tool_call_id": tc.id,
            "content": tc.function.arguments
        })

        # 第二轮：获取结果
        r2 = client.chat.completions.create(
            model=model, messages=messages, tools=tools,
            extra_body={"thinking": {"type": "disabled"}},
            timeout=30
        )

        return {
            "source": "kimi",
            "searched": True,
            "result": r2.choices[0].message.content or "",
            "urls": [],  # Kimi 不返回 URL 列表
        }

    except Exception:
        return None


# ========== Layer 2: URL 发现 ==========

def _decode_ddgo_url(href: str) -> str:
    """解码 DuckDuckGo 重定向 URL，提取真实目标 URL。"""
    if "uddg=" in href:
        try:
            parsed = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs:
                return urllib.parse.unquote(qs["uddg"][0])
        except Exception:
            pass
    return href


def duckduckgo_search(query: str) -> list:
    """
    使用 DuckDuckGo HTML 搜索获取 URL 列表。无需 API key。
    返回 [(title, url), ...]
    """
    if not HAS_REQUESTS:
        return []

    try:
        encoded = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for link in soup.find_all("a", class_="result__a"):
            href = link.get("href", "")
            title = link.get_text(strip=True)
            real_url = _decode_ddgo_url(href)
            if title and real_url.startswith("http"):
                results.append((title, real_url))

        return results[:10]  # 最多取 10 个

    except Exception:
        return []


def github_search(query: str) -> list:
    """
    使用 GitHub API 搜索仓库。无需 API key（有 Rate Limit）。
    返回 [(repo_full_name, url, description), ...]
    """
    if not HAS_REQUESTS:
        return []

    try:
        # 自动添加 "AI agent" 等关键词提升相关性
        q = f"{query} in:name,description,readme sort:updated"
        url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(q)}&per_page=10"
        headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github.v3+json"}
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code == 403:
            # Rate limited, try without auth
            return []

        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("items", []):
            results.append((
                item.get("full_name", ""),
                item.get("html_url", ""),
                item.get("description", "") or "",
            ))
        return results[:10]

    except Exception:
        return []


# ========== Layer 3: 网页抓取 ==========

def fetch_url(url: str) -> str:
    """抓取单个 URL 的文本内容。"""
    if not HAS_REQUESTS:
        return ""

    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()

        # 只处理 HTML
        content_type = resp.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        # 移除脚本、样式、导航等无关元素
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
            tag.decompose()

        # 尝试提取主要内容区域
        content = ""
        for selector in ["main", "article", "[role='main']", ".content", "#content", ".post", ".entry"]:
            el = soup.select_one(selector)
            if el:
                content = el.get_text(separator="\n", strip=True)
                break

        # 如果没有找到主要内容区，提取所有段落
        if not content:
            paragraphs = soup.find_all("p")
            content = "\n\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20)

        # 清理多余空白
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content[:FETCH_MAX_CHARS]

    except Exception:
        return ""


# ========== 结果质量评估 ==========

def is_low_quality(text: str) -> bool:
    """判断搜索结果质量是否过低（需要触发 fallback）。"""
    if not text or len(text.strip()) < 100:
        return True

    text_lower = text.lower()
    for pattern in REFUSAL_PATTERNS:
        if re.search(pattern, text_lower):
            return True

    # 如果内容主要是"让我搜索更多..."或工具调用痕迹
    if text.count("<tool") > 2 or text.count("<|tool") > 2:
        return True

    # 如果内容大量重复同一句话
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) > 3 and len(set(lines)) < len(lines) * 0.3:
        return True

    return False


# ========== 合并结果 ==========

def merge_results(kimi_result: Optional[dict], fallback_text: str) -> dict:
    """合并 Kimi 结果和 fallback 结果。"""
    kimi_text = (kimi_result or {}).get("result", "") if kimi_result else ""

    # 如果 Kimi 结果质量高，优先使用
    if kimi_text and not is_low_quality(kimi_text):
        final = kimi_text
        sources = ["kimi"]
    else:
        final = fallback_text
        sources = ["fallback"]

    # 如果两者都有内容，合并
    if kimi_text and fallback_text and kimi_text != fallback_text:
        final = f"【Kimi 搜索结果】\n\n{kimi_text[:5000]}\n\n" \
                f"【补充搜索结果（DuckDuckGo + 网页抓取）】\n\n{fallback_text[:8000]}"
        sources = ["kimi", "fallback"]

    return {
        "success": True,
        "searched": True,
        "result": final[:MAX_RESULT_CHARS],
        "sources": sources,
    }


# ========== 主入口 ==========

def search(query: str, model: str = "kimi-k2.6", raw: bool = False, force_fallback: bool = False) -> dict:
    """
    执行多层搜索。

    Args:
        query: 搜索查询
        model: Kimi 模型
        raw: 返回原始结果（仅 Kimi 层）
        force_fallback: 强制使用 fallback（跳过 Kimi）

    Returns:
        dict: 搜索结果
    """
    # --- Layer 1: Kimi $web_search ---
    kimi_result = None
    if not force_fallback:
        kimi_result = kimi_search(query, model)

    if raw and kimi_result:
        return {
            "success": True,
            "searched": True,
            "result": kimi_result.get("result", ""),
            "source": "kimi",
            "mode": "raw",
        }

    # 检查 Kimi 结果质量
    kimi_text = (kimi_result or {}).get("result", "") if kimi_result else ""
    kimi_ok = kimi_text and not is_low_quality(kimi_text)

    # --- Layer 2+3: Fallback 搜索 ---
    fallback_parts = []
    ddgo_urls = []
    github_repos = []

    if not kimi_ok or force_fallback:
        if not HAS_REQUESTS:
            return {
                "success": False,
                "error": "Fallback search requires 'requests' and 'beautifulsoup4'. Install: pip install requests beautifulsoup4",
                "result": "",
            }

        # 2a. DuckDuckGo 搜索
        ddgo_urls = duckduckgo_search(query)
        if ddgo_urls:
            fallback_parts.append("【DuckDuckGo 搜索结果】")
            for i, (title, url) in enumerate(ddgo_urls[:5], 1):
                fallback_parts.append(f"{i}. {title}\n   {url}")

        # 2b. GitHub 搜索（技术项目）
        github_repos = github_search(query)
        if github_repos:
            fallback_parts.append("\n【GitHub 搜索结果】")
            for i, (name, url, desc) in enumerate(github_repos[:5], 1):
                fallback_parts.append(f"{i}. {name}\n   {url}\n   {desc[:200]}")

        # 3. 网页抓取
        all_urls = [u for _, u in ddgo_urls[:MAX_FETCH_URLS]]
        # 也抓取 GitHub 仓库主页
        for name, url, _ in github_repos[:3]:
            if url:
                all_urls.append(url)

        fetched_contents = []
        seen = set()
        for url in all_urls:
            if url in seen:
                continue
            seen.add(url)
            text = fetch_url(url)
            if text and len(text.strip()) > 100:
                fetched_contents.append((url, text))
            time.sleep(0.5)  # 礼貌延迟

        if fetched_contents:
            fallback_parts.append("\n【抓取到的网页内容摘要】")
            for url, text in fetched_contents:
                fallback_parts.append(f"\n--- {url} ---")
                fallback_parts.append(text[:2000])

    fallback_text = "\n".join(fallback_parts)

    # 合并
    return merge_results(kimi_result, fallback_text)


def main():
    args = sys.argv[1:]
    raw_mode = False
    force_fallback = False

    # 解析参数
    filtered = []
    for a in args:
        if a == "--raw":
            raw_mode = True
        elif a == "--fallback":
            force_fallback = True
        else:
            filtered.append(a)

    if not filtered:
        print(json.dumps({
            "success": False,
            "error": "Usage: python kimi_search.py [--raw] [--fallback] <query>"
        }, ensure_ascii=False))
        sys.exit(1)

    query = filtered[0]
    result = search(query, raw=raw_mode, force_fallback=force_fallback)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
