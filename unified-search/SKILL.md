---
name: unified-search
description: >
  Unified web + academic search aggregator over 6 sources (keenable, tavily,
  firecrawl, arxiv, dblp, semantic_scholar). Use INSTEAD OF built-in
  `websearch_web_search_exa`, `webfetch`, or `keenable_search_web_pages` for
  ANY query needing current info, papers, or web content. Triggers on:
  real-time info, academic papers, library docs, news, "搜一下", "查一下",
  "find papers", "latest", "search the web", any web search request.
  Modes: general (2-source + arbitration), academic (3-source parallel + paper
  links recorded), fetch (single-URL content extraction), history (cache reuse).
---

# Unified Search

A single skill that replaces ALL default web search tools. 6 sources, 3 modes,
quota-aware, with retry and dedup. **Always use this skill first** for any
search need; only fall back to built-in tools if this skill fails entirely.

## Sources

| Source | Type | Cost | Strength |
|---|---|---|---|
| keenable | CLI | free | General web search, fast fetch |
| tavily | HTTP, 1000/mo | metered | AI answer summary, high relevance |
| firecrawl | HTTP, 1000/mo | metered | Markdown body extraction, scraping |
| arxiv | HTTP | free | Preprint papers (physics/CS/math) |
| dblp | HTTP | free | CS publication catalog |
| semantic_scholar | HTTP | free | Citation graph, abstracts, PDF links |

## When to Use (MANDATORY)

**Use this skill INSTEAD OF** `websearch_web_search_exa`, `webfetch`, or
`keenable_search_web_pages` whenever:

- User asks for current/real-time info, news, prices, weather
- User asks to find papers, research, academic literature
- User says "搜一下", "查一下", "search", "look up", "find"
- User needs web page content extracted (use `--fetch`)
- You need to verify info across multiple sources

**Do NOT use this skill** for:
- Pure code/logic questions answerable from the codebase
- Mathematical facts or historical events in training data
- Single-file local lookups (use Read/Grep)

## Quick Start

```bash
# Auto-classify intent (general vs academic) and search
cd ~/.claude/skills && uv run python unified-search/scripts/unified_search.py "your query"

# Force general mode (keenable + tavily, firecrawl arbitration if divergent)
cd ~/.claude/skills && uv run python unified-search/scripts/unified_search.py "query" --mode general

# Force academic mode (arxiv + dblp + semantic_scholar, paper links recorded)
cd ~/.claude/skills && uv run python unified-search/scripts/unified_search.py "transformer attention" --mode academic

# Fetch single URL content (markdown) — firecrawl primary, keenable fallback
cd ~/.claude/skills && uv run python unified-search/scripts/unified_search.py --fetch https://example.com/article

# Search history cache (reuse past accurate results)
cd ~/.claude/skills && uv run python unified-search/scripts/unified_search.py --history "past query"

# Check monthly quota usage for tavily/firecrawl
cd ~/.claude/skills && uv run python unified-search/scripts/unified_search.py --quota
```

## Modes

### `general` (default for non-academic queries)

1. **Parallel**: keenable + tavily (basic depth)
2. **Agreement check**: compute URL-host Jaccard overlap
   - If overlap ≥ 0.4 → merge, dedup, rank, done
   - If overlap < 0.4 → **arbitration**: invoke firecrawl as 3rd source
3. **Merge**: dedup by normalized URL, cross-validated results get score bonus

Rationale: 2 free/metered sources first; expensive firecrawl only when
the two sources disagree, conserving the 1000/month quota.

### `academic` (auto-triggered for paper/research queries)

1. **Parallel**: arxiv + dblp + semantic_scholar (all free, no quota)
2. **Merge**: dedup by DOI/arxiv-id/normalized-URL, cross-validated bonus
3. **Record**: all paper links saved to `data/history.db` for later retrieval
4. Each result includes: title, url, pdf_url, doi, arxiv_id, year, venue, authors

Academic hint keywords that trigger auto-classification: paper, 论文, research,
study, survey, algorithm, model, neural, deep learning, transformer, LM,
benchmark, dataset, arxiv, doi, citation, method, approach, novel, proposed.

### `fetch` (single-URL content extraction)

| Strategy | Primary | Fallback | Use when |
|---|---|---|---|
| `markdown_body` (default) | firecrawl | keenable | Need full article body as markdown |
| `fast_summary` | keenable | — | Quick snippet, free |
| `ai_extract` | tavily | firecrawl | AI-structured extraction |

### `history`

Searches past results in `data/history.db`. General mode stores top-5;
academic mode stores top-5 + all paper links. Use this before re-searching
a similar query to save quota.

## Quota Conservation (CRITICAL)

Tavily and Firecrawl each have **1000 calls/month**. The script:

- Uses **basic** search depth by default (cheaper)
- Only invokes firecrawl for arbitration when sources diverge
- Only uses tavily `advanced` depth on explicit academic arbitration
- Falls back to free keenable when quota exhausted
- Tracks usage in `data/quota.json` per month

**Before searching, check quota**:
```bash
cd ~/.claude/skills && uv run python unified-search/scripts/unified_search.py --quota
```

If a metered source is exhausted, the script automatically degrades to free
sources (keenable for general, arxiv+dblp+semantic_scholar for academic).

## Output Format

All output is JSON to stdout. Example (general mode):

```json
{
  "mode": "general",
  "query": "rust async patterns",
  "sources_used": ["keenable", "tavily"],
  "agreement_score": 0.62,
  "arbitration_triggered": false,
  "total_results": 12,
  "results": [
    {
      "title": "...",
      "url": "https://...",
      "snippet": "...",
      "source": "keenable",
      "score": 0.78,
      "also_from": ["keenable", "tavily"]
    }
  ]
}
```

For academic mode, additional `paper_links` array with DOI/PDF URLs.

## Integration with Sub-agents

When delegating to `librarian` or `explore` agents, pass
`load_skills=["unified-search"]` so they use this skill instead of
built-in web search.

## Files

```
unified-search/
├── SKILL.md                  # this file
├── config.json               # sources, keys, modes, quota
├── scripts/
│   └── unified_search.py     # main script
├── data/
│   ├── history.db            # SQLite: past searches + paper links
│   └── quota.json            # monthly usage tracking
└── cache/                    # reserved for future result caching
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `keenable: command not found` | Run `source ~/.cargo/env` first |
| `tavily: quota_exhausted` | Wait for month rollover or use `--mode general` (keenable only path) |
| `firecrawl: 401` | Check `FIRECRAWL_API_KEY` env var or value in config.json |
| arxiv returns empty | arxiv rate-limits (1 req/3s); script retries with backoff |
| All sources fail | Script returns error entries; check network and API keys |
