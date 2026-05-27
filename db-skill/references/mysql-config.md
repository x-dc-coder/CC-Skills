# MySQL Config Reference

Use project-local JSON config so one global skill can work across many repos.

## Discovery Order

1. CLI `--config /path/to/file.json`
2. Env `DB_SKILL_CONFIG`
3. Auto-discovery from cwd upward:
- `.db-skill/mysql.json`
- `.db-skill.json`
- `config/mysql.json`

## Recommended File

Prefer `<project-root>/.db-skill/mysql.json`.

Example:

```json
{
  "mysql": {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "app_user",
    "password": "your-password",
    "database": "app_db",
    "charset": "utf8mb4",
    "connect_timeout": 5
  },
  "limits": {
    "default_limit": 200,
    "max_limit": 1000
  }
}
```

## Notes

- `mysql` object is required.
- `limits` is optional.
- Keep secrets in project-only files and avoid committing credentials.
