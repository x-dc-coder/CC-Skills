---
name: keenable-cli
description: Install and use the Keenable CLI for fast web search and page fetching from the terminal. Use when you need to search the web, fetch a page as clean markdown, or configure Keenable as the search provider (MCP) for AI clients like Claude Code or Cursor.
---

# Keenable CLI

`keenable` is a single-binary CLI for Keenable's web search and content APIs. Search and fetch work without login on a free tier; logging in raises rate limits. Default output is YAML, designed to be parsed by agents.

## Installation

Homebrew (macOS / Linux):

```bash
brew install keenableai/tap/keenable-cli
```

Installer script (macOS / Linux, installs to `~/.cargo/bin` or `~/.local/bin`; two steps so no pipe is needed):

```bash
curl --proto '=https' --tlsv1.2 -LsSf -o /tmp/keenable-install.sh \
  https://github.com/keenableai/keenable-cli/releases/latest/download/keenable-cli-installer.sh
sh /tmp/keenable-install.sh
```

The installer updates PATH for future shells only. To use `keenable` in the current shell, source the env file it wrote (or restart the shell). Sourcing both covers either install dir — `~/.cargo/env` may exist from rustup even when keenable went to `~/.local/bin`:

```bash
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
[ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env"
```

Windows (PowerShell):

```powershell
Invoke-WebRequest -OutFile $env:TEMP\keenable-install.ps1 `
  https://github.com/keenableai/keenable-cli/releases/latest/download/keenable-cli-installer.ps1
& $env:TEMP\keenable-install.ps1
```

From source: `cargo install --git https://github.com/keenableai/keenable-cli`

Verify with `keenable --version`. Update via `brew upgrade keenable-cli` or by re-running the installer.

## Authentication (optional)

```bash
# Device-code flow: prints a link + code for the user to approve. Works in headless/agent environments.
keenable login
# Save an API key directly (CI, servers)
keenable login --api-key keen_***
# Clear credentials from ~/.keenable/
keenable logout
```

Any command also accepts `--api-key <KEY>`, overriding the stored key.

## Configure MCP in AI clients

Supported clients: Claude Code, Claude Desktop, Cursor, Windsurf, Codex, OpenCode.

```bash
# Show which clients are detected/configured
keenable configure-mcp
# Configure all detected clients
keenable configure-mcp --all
# One client (also: --cursor, --codex, ...)
keenable configure-mcp --claude-code
# Remove Keenable MCP, restore defaults
keenable reset --all
```

## Search

```bash
# YAML output (for agents)
keenable search "rust async patterns"
# Pretty output (for humans)
keenable search "rust async patterns" -p
# Restrict to one site
keenable search "anthropic" --site techcrunch.com
# Date filter
keenable search "AI news" --published-after 2026-05-01
```

Date filters — `--published-after/-before` (publication date), `--acquired-after/-before` (index date) — accept `YYYY-MM-DD`, ISO 8601 datetimes, or relative values (`12h`, `7d`, `3mo`, `1y`).

Each YAML result has `title`, `url`, `description`, `snippet`, `published_at`, `acquired_at`.

## Fetch

```bash
# YAML: content (markdown), title, url
keenable fetch https://example.com
```

## CLI configuration

```bash
# View all settings
keenable config
```

## Links

- MCP endpoint: https://api.keenable.ai/mcp
- Full docs: https://docs.keenable.ai (append `.md` to any docs URL for markdown)
- CLI reference: https://docs.keenable.ai/cli.md
