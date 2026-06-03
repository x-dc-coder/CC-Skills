---
name: db-skill
description: High-performance MySQL and PostgreSQL operations for project-local databases with global skill reuse. Use when Codex must run MySQL/PostgreSQL CRUD (insert/update/delete/select), load connection settings from a project config file, enforce bounded result sizes, emit JSON, and use jq plus temp files to avoid context bloat.
---

# DB Skill

## Supported Databases

| Database | Script | Driver |
|----------|--------|--------|
| MySQL | `scripts/mysql_tool.py` | mysqlclient / pymysql / mysql-connector-python |
| PostgreSQL | `scripts/pg_tool.py` | psycopg2-binary |

## Quick Workflow

1. Resolve config path in this order:
   - Use `--config <path>` when explicitly provided.
   - Else use env `DB_SKILL_CONFIG`.
   - Else auto-discover from current directory upward:
     - `.db-skill/mysql.json` or `.db-skill/pg.json`
     - `.db-skill.json`
     - `config/mysql.json` or `config/pg.json`

2. Run SQL through the Python runner:
   - **MySQL**: `uv run python scripts/mysql_tool.py run --sql "SELECT * FROM users"`
   - **PostgreSQL**: `uv run python scripts/pg_tool.py run --sql "SELECT * FROM users"`

3. Keep query output bounded:
   - SELECT/CTE queries are wrapped and limited automatically.
   - Results are always written to a temp JSON file.
   - Terminal output returns a compact summary and optional jq preview.

## MySQL Commands

- Query with default row limit:
```bash
uv run python scripts/mysql_tool.py run --sql "SELECT * FROM orders"
```

- Query with custom limit and jq filter:
```bash
uv run python scripts/mysql_tool.py run \
  --sql "SELECT * FROM orders WHERE status='paid' ORDER BY id DESC" \
  --limit 200 \
  --jq '.[].id'
```

- Execute DML (insert/update/delete):
```bash
uv run python scripts/mysql_tool.py run --sql "DELETE FROM sessions WHERE expired=1" --confirm-write
```

- Read SQL from file:
```bash
uv run python scripts/mysql_tool.py run --sql-file ./sql/report.sql --jq '.[0:10]'
```

## PostgreSQL Commands

- Query with default row limit:
```bash
uv run python scripts/pg_tool.py run --sql "SELECT * FROM orders"
```

- Query with custom limit and jq filter:
```bash
uv run python scripts/pg_tool.py run \
  --sql "SELECT * FROM orders WHERE status='paid' ORDER BY id DESC" \
  --limit 200 \
  --jq '.[].id'
```

- Execute DML (insert/update/delete):
```bash
uv run python scripts/pg_tool.py run --sql "DELETE FROM sessions WHERE expired=1" --confirm-write
```

- Read SQL from file:
```bash
uv run python scripts/pg_tool.py run --sql-file ./sql/report.sql --jq '.[0:10]'
```

## Behavior Rules

- Treat SELECT and WITH queries as read operations.
- Require user second confirmation before any non-read SQL.
- Require `--confirm-write` for any non-read SQL; reject execution when missing.
- Enforce a hard cap for read rows (`max_limit`) from config, default 1000.
- Store full read results in `/tmp/skills-output/<date>/db-skill/` as JSON.
- Print only compact metadata + jq preview to control context size.
- Commit only write operations.

## Resources

- MySQL Script: `scripts/mysql_tool.py`
- PostgreSQL Script: `scripts/pg_tool.py`
- MySQL Config reference: `references/mysql-config.md`
- PostgreSQL Config reference: `references/pg-config.md`
