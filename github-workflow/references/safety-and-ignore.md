# Safety and ignore strategy

This skill uses two levels of ignore rules.

## 1. Shared project ignores in `.gitignore`

Use `.gitignore` for patterns that the whole team should ignore and that should be version-controlled.

The script appends a small shared block:
- generic editor / log noise
- `target/`, `build/`, `*.class` for Spring Boot / Java projects
- `__pycache__/`, `*.py[cod]`, `.venv/`, `venv/` for Python projects
- `bin/`, `coverage.out`, `*.test` for Go projects

## 2. Local-only secret protection in `.git/info/exclude`

Use `.git/info/exclude` for machine-local or user-local secret patterns that should not be committed into the repository rules.

The script appends a local-only block for patterns such as:
- `.env`, `.env.*`
- `*.key`, `*.p12`, `*.pfx`, `*.jks`, `*.keystore`
- `*id_ed25519*`, `*id_rsa*`
- `application-local.yml`, `application-dev.yml`, `application-prod.yml` and yaml variants
- `secrets*.json`, `credentials*.json`, `service-account*.json`

## 3. Review-manifest guard before publish

`preview` writes a review manifest under `.git/gitcode-workflow-review.json` by default.

The manifest stores:
- the reviewed file list
- per-file content hashes when files still exist
- the exact status lines seen during preview
- a snapshot hash used to verify publish is operating on the same reviewed worktree

Before `publish`:
- the script loads the review manifest
- rebuilds the current snapshot
- aborts if anything changed after preview
- stages only the manifest targets instead of running `git add .`

This prevents a “preview one set of files, publish a different set of files” failure mode.

## High-risk publish guard

Before `publish`, the script scans the project tree.

- If a high-risk path exists and is **not** ignored, publish fails.
- If a warning-level path exists and is **not** ignored, publish continues but reports the warning.

## Spring Boot guidance

Prefer externalized configuration and environment-specific overrides instead of storing real secrets in repository files.

Practical defaults for Spring Boot projects:
- commit `application.yml` or `application-example.yml` with non-secret defaults
- keep local secrets in environment variables or a local-only config file outside the repo
- if a repo truly needs per-developer overrides, add those filenames to `.git/info/exclude`

## Recommended manual review before first push

1. Run `git status --short`
2. Inspect `.gitignore`
3. Inspect `.git/info/exclude`
4. Run `preview` and review the grouped file list
5. Confirm the review-manifest path and snapshot hash were generated
6. Confirm that no token, password, certificate, or SSH private key is staged
7. Only then publish
