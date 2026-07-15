#!/usr/bin/env python3
"""
unified_search.py — Unified web + academic search aggregator.

Modes:
  general  : 2-source parallel (keenable + tavily), arbitration by firecrawl if divergence
  academic : 3-source parallel (arxiv + dblp + semantic_scholar), paper links recorded
  fetch    : single-URL content extraction (firecrawl markdown / keenable / tavily extract)
  history  : query past search cache

Usage:
  uv run python unified-search/scripts/unified_search.py "query" [--mode general|academic|auto]
  uv run python unified-search/scripts/unified_search.py "query" --mode academic --top 10
  uv run python unified-search/scripts/unified_search.py --fetch <url> [--strategy markdown_body|fast_summary|ai_extract]
  uv run python unified-search/scripts/unified_search.py --history "query"
  uv run python unified-search/scripts/unified_search.py --quota
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import yaml
from feedparser import parse as feedparse

# ─── Paths ──────────────────────────────────────────────────────────────────
SKILL_DIR = Path(__file__).resolve().parent.parent          # ~/.claude/skills/unified-search
SCRIPT_DIR = Path(__file__).resolve().parent                # .../scripts
CONFIG_PATH = SKILL_DIR / "config.json"
DATA_DIR = SKILL_DIR / "data"
CACHE_DIR = SKILL_DIR / "cache"
DB_PATH = DATA_DIR / "history.db"
QUOTA_PATH = DATA_DIR / "quota.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ─── Config ─────────────────────────────────────────────────────────────────
def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_api_key(cfg: dict, name: str) -> str | None:
    ak = cfg["api_keys"].get(name, {})
    env_var = ak.get("env_var")
    val = os.environ.get(env_var) if env_var else None
    if not val:
        val = ak.get("value")
    return val


# ─── Quota management ───────────────────────────────────────────────────────
def load_quota() -> dict:
    if QUOTA_PATH.exists():
        with open(QUOTA_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_quota(quota: dict) -> None:
    QUOTA_PATH.write_text(json.dumps(quota, indent=2, ensure_ascii=False), encoding="utf-8")


def current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def quota_available(cfg: dict, source: str) -> bool:
    """Return True if source still has monthly quota (for metered sources)."""
    qcfg = cfg.get("quota", {}).get(source)
    if not qcfg:
        return True
    quota = load_quota()
    month = current_month_key()
    used = quota.get(source, {}).get(month, 0)
    return used < qcfg["monthly_limit"]


def quota_consume(source: str, n: int = 1) -> None:
    """Record n calls against source's monthly quota."""
    quota = load_quota()
    month = current_month_key()
    entry = quota.setdefault(source, {})
    entry[month] = entry.get(month, 0) + n
    save_quota(quota)


def quota_remaining(cfg: dict, source: str) -> int | None:
    qcfg = cfg.get("quota", {}).get(source)
    if not qcfg:
        return None
    quota = load_quota()
    used = quota.get(source, {}).get(current_month_key(), 0)
    return max(0, qcfg["monthly_limit"] - used)


# ─── Result schema ──────────────────────────────────────────────────────────
def make_result(title: str, url: str, snippet: str = "", source: str = "",
                score: float = 0.0, **extra) -> dict:
    r = {
        "title": title,
        "url": url,
        "snippet": snippet,
        "source": source,
        "score": float(score),
    }
    r.update(extra)
    return r


# ─── URL normalization for dedup ────────────────────────────────────────────
def normalize_url(url: str) -> str:
    if not url:
        return ""
    p = urlparse(url.strip())
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = re.sub(r"/+$", "", p.path or "")
    # drop fragment, lowercase scheme
    return urlunparse((p.scheme.lower() or "https", netloc, path, "", "", ""))


# ─── Source adapters ────────────────────────────────────────────────────────
def search_keenable(query: str, cfg: dict, timeout: int | None = None) -> list[dict]:
    src = cfg["sources"]["keenable"]
    to = timeout or src["timeout_sec"]
    try:
        proc = subprocess.run(
            [src["command"], "search", query, "--site", ""],
            capture_output=True, text=True, timeout=to
        )
        # keenable search prints YAML to stdout
        out = proc.stdout
        if not out.strip():
            return []
        docs = yaml.safe_load(out)
        if not isinstance(docs, list):
            docs = [docs] if docs else []
        results = []
        for d in docs:
            results.append(make_result(
                title=d.get("title", ""),
                url=d.get("url", ""),
                snippet=d.get("snippet") or d.get("description", ""),
                source="keenable",
                score=0.6,
                published_at=d.get("published_at"),
            ))
        return results
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        return [make_result("", "", f"[keenable error: {type(e).__name__}: {e}]", "keenable", 0.0, error=str(e))]


def search_tavily(query: str, cfg: dict, advanced: bool = False, topic: str | None = None,
                  time_range: str | None = None) -> list[dict]:
    if not quota_available(cfg, "tavily"):
        return [make_result("", "", "[tavily quota exhausted this month]", "tavily", 0.0, error="quota_exhausted")]
    key = get_api_key(cfg, "tavily")
    if not key:
        return [make_result("", "", "[tavily: no API key]", "tavily", 0.0, error="no_key")]
    src = cfg["sources"]["tavily"]
    params = dict(src["advanced_params" if advanced else "default_params"])
    params["query"] = query
    if topic:
        params["topic"] = topic
    if time_range:
        params["time_range"] = time_range
    try:
        with httpx.Client(timeout=src["timeout_sec"]) as client:
            resp = client.post(src["endpoint"], json=params,
                               headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            quota_consume("tavily")
        data = resp.json()
        answer = data.get("answer")
        results = []
        for r in data.get("results", []):
            results.append(make_result(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
                source="tavily",
                score=float(r.get("score", 0.7)),
                published_date=r.get("published_date"),
                domain=r.get("domain"),
            ))
        if answer:
            results.insert(0, make_result(
                "[AI Answer]", "", answer, "tavily", 1.0, kind="ai_answer"
            ))
        return results
    except Exception as e:
        return [make_result("", "", f"[tavily error: {type(e).__name__}: {e}]", "tavily", 0.0, error=str(e))]


def search_firecrawl(query: str, cfg: dict, limit: int | None = None) -> list[dict]:
    if not quota_available(cfg, "firecrawl"):
        return [make_result("", "", "[firecrawl quota exhausted this month]", "firecrawl", 0.0, error="quota_exhausted")]
    key = get_api_key(cfg, "firecrawl")
    if not key:
        return [make_result("", "", "[firecrawl: no API key]", "firecrawl", 0.0, error="no_key")]
    src = cfg["sources"]["firecrawl"]
    body = dict(src["default_params"])
    body["query"] = query
    if limit:
        body["limit"] = limit
    try:
        with httpx.Client(timeout=src["timeout_sec"]) as client:
            resp = client.post(src["endpoint"], json=body,
                               headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            quota_consume("firecrawl")
        data = resp.json()
        if not data.get("success", True):
            return [make_result("", "", f"[firecrawl: {data.get('error','')}]",
                                "firecrawl", 0.0, error=str(data.get("error")))]
        results = []
        web = (data.get("data") or {}).get("web", []) or data.get("web", [])
        for r in web:
            results.append(make_result(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("description", ""),
                source="firecrawl",
                score=0.65,
                markdown=r.get("markdown", "")[:2000],
            ))
        return results
    except Exception as e:
        return [make_result("", "", f"[firecrawl error: {type(e).__name__}: {e}]", "firecrawl", 0.0, error=str(e))]


def search_arxiv(query: str, cfg: dict, max_results: int = 15) -> list[dict]:
    src = cfg["sources"]["arxiv"]
    params = dict(src["default_params"])
    params["search_query"] = f"all:{query}"
    params["max_results"] = max_results
    # arxiv is strict on rate limits: use httpx directly so we can see 429
    try:
        with httpx.Client(timeout=src["timeout_sec"], follow_redirects=True) as client:
            resp = client.get(src["endpoint"], params=params)
        if resp.status_code == 429:
            return [make_result("", "", "[arxiv: rate limited (429), retry with backoff]",
                                "arxiv", 0.0, error="429_rate_limited")]
        resp.raise_for_status()
        feed = feedparse(resp.text)
        results = []
        for e in feed.entries:
            arxiv_url = e.get("id", "")
            results.append(make_result(
                title=e.get("title", "").strip().replace("\n", " "),
                url=arxiv_url,
                snippet=e.get("summary", "").strip().replace("\n", " ")[:500],
                source="arxiv",
                score=0.8,
                published=e.get("published"),
                authors=[a.name for a in e.get("authors", [])],
                journal_ref=e.get("journal_ref"),
                pdf_link=next((l.href for l in e.get("links", []) if l.rel == "related" and "pdf" in l.href), ""),
                primary_category=getattr(e, "arxiv_primary_category", {}).get("term", "") if hasattr(e, "arxiv_primary_category") else "",
            ))
        return results
    except Exception as e:
        return [make_result("", "", f"[arxiv error: {type(e).__name__}: {e}]", "arxiv", 0.0, error=str(e))]


def search_dblp(query: str, cfg: dict, max_results: int = 15) -> list[dict]:
    src = cfg["sources"]["dblp"]
    params = dict(src["default_params"])
    params["q"] = query
    params["h"] = max_results
    try:
        with httpx.Client(timeout=src["timeout_sec"]) as client:
            resp = client.get(src["endpoint"], params=params)
            resp.raise_for_status()
        data = resp.json()
        hits = ((data.get("result") or {}).get("hits") or {}).get("hit", [])
        results = []
        for h in hits:
            info = h.get("info", {})
            # dblp may nest single author as string or list
            authors_raw = info.get("authors", {}).get("author", [])
            if isinstance(authors_raw, dict):
                authors_raw = [authors_raw]
            authors = [a.get("text", a) if isinstance(a, dict) else a for a in authors_raw] if authors_raw else []
            url = info.get("url") or info.get("ee") or ""
            if url and not url.startswith("http"):
                url = f"https://dblp.org/{url}"
            results.append(make_result(
                title=info.get("title", ""),
                url=url,
                snippet=f"{info.get('venue','')} {info.get('year','')}".strip(),
                source="dblp",
                score=0.75,
                year=info.get("year"),
                venue=info.get("venue"),
                type=info.get("type"),
                authors=authors,
                doi=info.get("doi"),
            ))
        return results
    except Exception as e:
        return [make_result("", "", f"[dblp error: {type(e).__name__}: {e}]", "dblp", 0.0, error=str(e))]


def search_semantic_scholar(query: str, cfg: dict, limit: int = 15) -> list[dict]:
    src = cfg["sources"]["semantic_scholar"]
    key = get_api_key(cfg, "semantic_scholar")
    params = dict(src["default_params"])
    params["query"] = query
    params["limit"] = limit
    headers = {}
    if key:
        headers["x-api-key"] = key
    try:
        with httpx.Client(timeout=src["timeout_sec"]) as client:
            resp = client.get(src["endpoint"], params=params, headers=headers)
            resp.raise_for_status()
        data = resp.json()
        results = []
        for p in data.get("data", []):
            oap = p.get("openAccessPdf") or {}
            authors = [a.get("name", "") for a in p.get("authors", [])]
            results.append(make_result(
                title=p.get("title", ""),
                url=p.get("url", ""),
                snippet=(p.get("abstract") or "")[:500],
                source="semantic_scholar",
                score=0.85,
                year=p.get("year"),
                venue=p.get("venue"),
                authors=authors,
                citation_count=p.get("citationCount"),
                paper_id=p.get("paperId"),
                pdf_url=oap.get("url"),
                doi=(p.get("externalIds") or {}).get("DOI"),
                arxiv_id=(p.get("externalIds") or {}).get("ArXiv"),
            ))
        return results
    except Exception as e:
        return [make_result("", "", f"[semantic_scholar error: {type(e).__name__}: {e}]",
                            "semantic_scholar", 0.0, error=str(e))]


# ─── Parallel execution wrapper ─────────────────────────────────────────────
def run_sources_parallel(search_fn_map: dict, query: str, cfg: dict) -> dict[str, list[dict]]:
    """Run multiple source searchers in parallel threads.
    search_fn_map: {source_name: callable(query, cfg) -> list[dict]}
    """
    out: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=len(search_fn_map)) as pool:
        futures = {name: pool.submit(fn, query, cfg) for name, fn in search_fn_map.items()}
        for name, fut in futures.items():
            try:
                out[name] = fut.result()
            except Exception as e:
                out[name] = [make_result("", "", f"[{name} exception: {e}]", name, 0.0, error=str(e))]
    return out


# ─── Retry with backoff ─────────────────────────────────────────────────────
def search_with_retry(fn, query: str, cfg: dict, retries: int = 2, base_delay: float = 1.0,
                      **fn_kwargs) -> list[dict]:
    last_err = None
    for attempt in range(retries + 1):
        try:
            res = fn(query, cfg, **fn_kwargs) if fn_kwargs else fn(query, cfg)
            # if every result has an error field, treat as failure
            if res and all(r.get("error") for r in res):
                last_err = res[0].get("error", "")
                if attempt < retries:
                    # 429 / rate limit → longer exponential backoff (3s, 6s)
                    delay = base_delay * (3 ** attempt) if "429" in str(last_err) else base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
            return res
        except Exception as e:
            last_err = str(e)
            if attempt < retries:
                time.sleep(base_delay * (2 ** attempt))
    return [make_result("", "", f"[retry exhausted: {last_err}]", "retry", 0.0, error=last_err or "unknown")]


# ─── Dedup + rank ───────────────────────────────────────────────────────────
def dedup_and_rank(per_source: dict[str, list[dict]], cfg: dict, top_k: int = 20) -> list[dict]:
    seen: dict[str, dict] = {}
    for source, items in per_source.items():
        weight = cfg["sources"].get(source, {}).get("weight", 1.0)
        for r in items:
            if r.get("error"):
                continue
            nurl = normalize_url(r.get("url", ""))
            key = nurl or (r.get("title", "") + "|" + source)
            if key in seen:
                # bump score if multiple sources agree (cross-validation bonus)
                seen[key]["score"] += 0.15 * weight
                seen[key].setdefault("also_from", []).append(source)
                continue
            r2 = dict(r)
            r2["score"] = r2.get("score", 0.5) * weight
            r2.setdefault("also_from", [source])
            seen[key] = r2
    ranked = sorted(seen.values(), key=lambda x: x.get("score", 0), reverse=True)
    return ranked[:top_k]


# ─── Agreement metric (Jaccard on URL hosts) ────────────────────────────────
def url_agreement(results_a: list[dict], results_b: list[dict]) -> float:
    hosts_a = {normalize_url(r.get("url", "")).split("/")[2] if normalize_url(r.get("url", "")) else "" for r in results_a if r.get("url")}
    hosts_b = {normalize_url(r.get("url", "")).split("/")[2] if normalize_url(r.get("url", "")) else "" for r in results_b if r.get("url")}
    if not hosts_a and not hosts_b:
        return 0.0
    inter = hosts_a & hosts_b
    union = hosts_a | hosts_b
    return len(inter) / len(union) if union else 0.0


# ─── Mode: general (2-source + arbitration) ──────────────────────────────────
def mode_general(query: str, cfg: dict, top_k: int = 15) -> dict:
    mcfg = cfg["modes"]["general"]
    primary = mcfg["primary_pair"]
    arbitrator = mcfg["arbitrator"]
    threshold = mcfg["agreement_threshold"]

    fn_map = {}
    if "keenable" in primary:
        fn_map["keenable"] = lambda q, c: search_with_retry(search_keenable, q, c)
    if "tavily" in primary:
        fn_map["tavily"] = lambda q, c: search_with_retry(search_tavily, q, c, advanced=False)
    per_source = run_sources_parallel(fn_map, query, cfg)

    # check agreement
    sources_with_results = {s: [r for r in v if not r.get("error")] for s, v in per_source.items()}
    src_names = list(sources_with_results.keys())
    agreement = 1.0
    if len(src_names) >= 2:
        agreement = url_agreement(sources_with_results[src_names[0]], sources_with_results[src_names[1]])

    arbitration_used = False
    if agreement < threshold and arbitrator not in per_source:
        arbitration_used = True
        arb_fn = {
            "firecrawl": lambda q, c: search_with_retry(search_firecrawl, q, c),
            "tavily": lambda q, c: search_with_retry(search_tavily, q, c, advanced=True),
            "keenable": lambda q, c: search_with_retry(search_keenable, q, c),
        }.get(arbitrator)
        if arb_fn and quota_available(cfg, arbitrator):
            per_source[arbitrator] = arb_fn(query, cfg)

    merged = dedup_and_rank(per_source, cfg, top_k=top_k)
    return {
        "mode": "general",
        "query": query,
        "sources_used": list(per_source.keys()),
        "agreement_score": round(agreement, 3),
        "arbitration_triggered": arbitration_used,
        "total_results": len(merged),
        "results": merged,
    }


# ─── Mode: academic ─────────────────────────────────────────────────────────
def mode_academic(query: str, cfg: dict, top_k: int = 30) -> dict:
    mcfg = cfg["modes"]["academic"]
    sources_list = mcfg["sources"]
    fn_map = {}
    if "arxiv" in sources_list:
        fn_map["arxiv"] = lambda q, c: search_with_retry(search_arxiv, q, c, max_results=mcfg["max_results_per_source"])
    if "dblp" in sources_list:
        fn_map["dblp"] = lambda q, c: search_with_retry(search_dblp, q, c, max_results=mcfg["max_results_per_source"])
    if "semantic_scholar" in sources_list:
        fn_map["semantic_scholar"] = lambda q, c: search_with_retry(search_semantic_scholar, q, c, limit=mcfg["max_results_per_source"])

    per_source = run_sources_parallel(fn_map, query, cfg)
    merged = dedup_and_rank(per_source, cfg, top_k=top_k)

    # extract paper links for record
    paper_links = []
    for r in merged:
        if r.get("url") and any(r.get("source") == s for s in ["arxiv", "dblp", "semantic_scholar"]):
            paper_links.append({
                "title": r.get("title"),
                "url": r.get("url"),
                "pdf_url": r.get("pdf_url") or r.get("pdf_link"),
                "doi": r.get("doi"),
                "arxiv_id": r.get("arxiv_id"),
                "year": r.get("year"),
                "venue": r.get("venue"),
                "authors": r.get("authors"),
                "source": r.get("source"),
                "also_from": r.get("also_from"),
            })

    # record to history
    if mcfg.get("record_papers"):
        save_history(cfg, query, merged[:5], mode="academic", paper_links=paper_links)

    return {
        "mode": "academic",
        "query": query,
        "sources_used": list(per_source.keys()),
        "total_results": len(merged),
        "paper_links_recorded": len(paper_links),
        "results": merged,
        "paper_links": paper_links,
    }


# ─── Mode: auto ──────────────────────────────────────────────────────────────
ACADEMIC_HINTS = (
    "paper", "论文", "research", "study", "survey", "experiment", "algorithm",
    "model", "neural", "deep learning", "machine learning", "transformer",
    "LLM", "benchmark", "dataset", "arxiv", "doi", "citation", "author",
    "theory", "method", "approach", "novel", "proposed", "evaluation",
)


def classify_intent(query: str) -> str:
    q = query.lower()
    if any(h.lower() in q for h in ACADEMIC_HINTS):
        return "academic"
    return "general"


def mode_auto(query: str, cfg: dict, top_k: int = 20) -> dict:
    intent = classify_intent(query)
    if intent == "academic":
        return mode_academic(query, cfg, top_k=top_k)
    return mode_general(query, cfg, top_k=top_k)


# ─── Fetch (content extraction) ─────────────────────────────────────────────
def fetch_with_firecrawl(url: str, cfg: dict) -> dict:
    if not quota_available(cfg, "firecrawl"):
        return {"error": "firecrawl quota exhausted", "source": "firecrawl"}
    key = get_api_key(cfg, "firecrawl")
    if not key:
        return {"error": "no firecrawl key", "source": "firecrawl"}
    endpoint = "https://api.firecrawl.dev/v2/scrape"
    try:
        with httpx.Client(timeout=45) as client:
            resp = client.post(endpoint, json={"url": url, "formats": ["markdown"]},
                               headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            quota_consume("firecrawl")
        data = resp.json().get("data", {})
        return {
            "url": url, "title": data.get("title", ""), "markdown": data.get("markdown", ""),
            "source": "firecrawl", "status": "ok"
        }
    except Exception as e:
        return {"url": url, "error": f"{type(e).__name__}: {e}", "source": "firecrawl"}


def fetch_with_keenable(url: str, cfg: dict) -> dict:
    try:
        proc = subprocess.run(
            ["keenable", "fetch", url], capture_output=True, text=True, timeout=30
        )
        out = proc.stdout
        if not out.strip():
            return {"url": url, "error": "empty output", "source": "keenable"}
        doc = yaml.safe_load(out)
        return {
            "url": url, "title": doc.get("title", ""), "markdown": doc.get("content", ""),
            "source": "keenable", "status": "ok"
        }
    except Exception as e:
        return {"url": url, "error": f"{type(e).__name__}: {e}", "source": "keenable"}


def fetch_with_tavily(url: str, cfg: dict) -> dict:
    if not quota_available(cfg, "tavily"):
        return {"error": "tavily quota exhausted", "source": "tavily"}
    key = get_api_key(cfg, "tavily")
    if not key:
        return {"error": "no tavily key", "source": "tavily"}
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                "https://api.tavily.com/extract",
                json={"urls": [url]},
                headers={"Authorization": f"Bearer {key}"},
            )
            resp.raise_for_status()
            quota_consume("tavily")
        data = resp.json()
        results = data.get("results", [])
        if results:
            r = results[0]
            return {
                "url": url, "title": r.get("title", ""),
                "markdown": r.get("raw_content") or r.get("content", ""),
                "source": "tavily", "status": "ok"
            }
        return {"url": url, "error": "no results", "source": "tavily"}
    except Exception as e:
        return {"url": url, "error": f"{type(e).__name__}: {e}", "source": "tavily"}


def mode_fetch(url: str, cfg: dict, strategy: str = "markdown_body") -> dict:
    strats = cfg.get("fetch", {}).get("strategies", {})
    strat = strats.get(strategy, strats.get("markdown_body", {}))
    primary = strat.get("primary")
    fallback = strat.get("fallback")
    fetchers = {
        "firecrawl": fetch_with_firecrawl,
        "keenable": fetch_with_keenable,
        "tavily": fetch_with_tavily,
    }
    # try primary
    if primary and primary in fetchers:
        res = fetchers[primary](url, cfg)
        if res.get("status") == "ok":
            return {"mode": "fetch", "url": url, "strategy": strategy, **res}
    # try fallback
    if fallback and fallback in fetchers:
        res2 = fetchers[fallback](url, cfg)
        if res2.get("status") == "ok":
            return {"mode": "fetch", "url": url, "strategy": strategy, **res2}
    # last resort: keenable always
    if primary != "keenable" and fallback != "keenable":
        res3 = fetch_with_keenable(url, cfg)
        if res3.get("status") == "ok":
            return {"mode": "fetch", "url": url, "strategy": "fallback_keenable", **res3}
    return {"mode": "fetch", "url": url, "strategy": strategy,
            "error": "all fetchers failed", "primary_attempt": primary, "fallback_attempt": fallback}


# ─── History (SQLite) ───────────────────────────────────────────────────────
def init_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            query TEXT NOT NULL,
            mode TEXT NOT NULL,
            intent TEXT,
            sources_used TEXT,
            total_results INTEGER,
            top_results TEXT,
            paper_links TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_query ON searches(query);
        CREATE INDEX IF NOT EXISTS idx_ts ON searches(ts);
        """)


def save_history(cfg: dict, query: str, top_results: list[dict], mode: str = "general",
                 paper_links: list[dict] | None = None) -> None:
    hcfg = cfg.get("history", {})
    if not hcfg.get("enabled", True):
        return
    db_path = SKILL_DIR / hcfg.get("db_path", "data/history.db")
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO searches (ts, query, mode, sources_used, total_results, top_results, paper_links) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                query, mode,
                "", len(top_results),
                json.dumps(top_results, ensure_ascii=False),
                json.dumps(paper_links or [], ensure_ascii=False),
            )
        )


def query_history(query: str, cfg: dict, limit: int = 5) -> dict:
    hcfg = cfg.get("history", {})
    db_path = SKILL_DIR / hcfg.get("db_path", "data/history.db")
    if not db_path.exists():
        return {"mode": "history", "query": query, "results": [], "note": "no history db yet"}
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM searches WHERE query LIKE ? ORDER BY ts DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
    results = []
    for r in rows:
        results.append({
            "ts": r["ts"], "query": r["query"], "mode": r["mode"],
            "total_results": r["total_results"],
            "top_results": json.loads(r["top_results"] or "[]"),
            "paper_links": json.loads(r["paper_links"] or "[]"),
        })
    return {"mode": "history", "query": query, "matches": len(results), "results": results}


# ─── Quota report ────────────────────────────────────────────────────────────
def report_quota(cfg: dict) -> dict:
    out = {}
    for src_name in ["tavily", "firecrawl"]:
        qcfg = cfg.get("quota", {}).get(src_name)
        if qcfg:
            remaining = quota_remaining(cfg, src_name)
            used = qcfg["monthly_limit"] - (remaining or 0)
            out[src_name] = {
                "monthly_limit": qcfg["monthly_limit"],
                "used_this_month": used,
                "remaining": remaining,
                "month": current_month_key(),
            }
    return {"mode": "quota", "quota": out}


# ─── CLI ─────────────────────────────────────────────────────────────────────
def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Unified web + academic search aggregator (6 sources)."
    )
    p.add_argument("query", nargs="?", help="search query (or history search term)")
    p.add_argument("--mode", choices=["general", "academic", "auto"], default="auto",
                   help="search mode (default: auto-classify)")
    p.add_argument("--top", type=int, default=None, help="top-K results to return")
    p.add_argument("--fetch", metavar="URL", help="fetch single URL content (markdown)")
    p.add_argument("--strategy", choices=["markdown_body", "fast_summary", "ai_extract"],
                   default="markdown_body", help="fetch strategy")
    p.add_argument("--history", action="store_true", help="search history cache instead of web")
    p.add_argument("--quota", action="store_true", help="show monthly quota usage")
    p.add_argument("--topic", default=None, help="tavily topic hint (general/news/finance)")
    p.add_argument("--time-range", default=None, help="tavily time_range (day/week/month/year)")
    return p


def main() -> int:
    args = build_argparser().parse_args()
    cfg = load_config()

    # ── quota ──
    if args.quota:
        print(json.dumps(report_quota(cfg), indent=2, ensure_ascii=False))
        return 0

    # ── history ──
    if args.history:
        if not args.query:
            print(json.dumps({"error": "history search requires a query"}, ensure_ascii=False))
            return 1
        print(json.dumps(query_history(args.query, cfg), indent=2, ensure_ascii=False))
        return 0

    # ── fetch ──
    if args.fetch:
        result = mode_fetch(args.fetch, cfg, strategy=args.strategy)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    # ── search ──
    if not args.query:
        print(json.dumps({"error": "no query provided"}, ensure_ascii=False))
        return 1

    top_k = args.top or (30 if args.mode == "academic" else 15)
    if args.mode == "general":
        result = mode_general(args.query, cfg, top_k=top_k)
    elif args.mode == "academic":
        result = mode_academic(args.query, cfg, top_k=top_k)
    else:  # auto
        result = mode_auto(args.query, cfg, top_k=top_k)

    # always record general search history too (top-5)
    if result.get("mode") == "general":
        save_history(cfg, args.query, result["results"][:5], mode="general")

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
