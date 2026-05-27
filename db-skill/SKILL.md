---
name: db-skill
description: High-performance MySQL operations for project-local databases with global skill reuse. Use when Codex must run MySQL CRUD (insert/update/delete/select), load connection settings from a project config file, enforce bounded result sizes, emit JSON, and use jq plus temp files to avoid context bloat.
---

# DB Skill

## Quick Workflow

1. Resolve config path in this order:
- Use `--config <path>` when explicitly provided.
- Else use env `DB_SKILL_CONFIG`.
- Else auto-discover from current directory upward:
  - `.db-skill/mysql.json`
  - `.db-skill.json`
  - `config/mysql.json`

2. Run SQL through the Python runner:
- `python3 scripts/mysql_tool.py run --sql "SELECT * FROM users"`
- `python3 scripts/mysql_tool.py run --sql "UPDATE users SET active=0 WHERE id=42" --confirm-write`

3. Keep query output bounded:
- SELECT/CTE queries are wrapped and limited automatically.
- Results are always written to a temp JSON file.
- Terminal output returns a compact summary and optional jq preview.

## Commands

- Query with default row limit:
```bash
python3 scripts/mysql_tool.py run --sql "SELECT * FROM orders"
```

- Query with custom limit and jq filter:
```bash
python3 scripts/mysql_tool.py run \
  --sql "SELECT * FROM orders WHERE status='paid' ORDER BY id DESC" \
  --limit 200 \
  --jq '.[].id'
```

- Execute DML (insert/update/delete):
```bash
python3 scripts/mysql_tool.py run --sql "DELETE FROM sessions WHERE expired=1" --confirm-write
```

- Read SQL from file:
```bash
python3 scripts/mysql_tool.py run --sql-file ./sql/report.sql --jq '.[0:10]'
```

## Behavior Rules

- Treat SELECT and WITH queries as read operations.
- Require user second confirmation before any non-read SQL.
- Require `--confirm-write` for any non-read SQL; reject execution when missing.
- Enforce a hard cap for read rows (`max_limit`) from config, default 1000.
- Store full read results in `/tmp/db-skill/` as JSON.
- Print only compact metadata + jq preview to control context size.
- Commit only write operations.

## Resources

- Script: `scripts/mysql_tool.py`
- Config reference: `references/mysql-config.md`
