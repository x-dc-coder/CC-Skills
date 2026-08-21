---
name: officecli
description: Create, analyze, proofread, and modify Office documents (.docx, .xlsx, .pptx) using the officecli CLI tool. Use when the user wants to create, inspect, check formatting, find issues, add charts, or modify Office documents.
---

# officecli

AI-friendly CLI for .docx, .xlsx, .pptx. Single binary, no dependencies, no Office installation needed.

## Install

```bash
# macOS / Linux
curl -fsSL https://d.officecli.ai/install.sh | bash
# Windows (PowerShell)
irm https://d.officecli.ai/install.ps1 | iex
```

Verify with `officecli --version`. If still not found after install, open a new terminal.

## Strategy

**L1 (read) → L2 (DOM edit) → L3 (raw XML)**. Always prefer higher layers. Add `--json` for structured output.

**Before doc work, check Specialized Skills**（下方索引）。Fundraising decks, academic papers, financial models, dashboards, and Morph animations need their own skill loaded first — `load_skill` once, then proceed.

## Help System (IMPORTANT)

**When unsure about property names, value formats, or command syntax, ALWAYS run help instead of guessing.** One help query beats guess-fail-retry loops.

```bash
officecli help                                  # All commands + global options + schema entry points
officecli help docx                             # List all docx elements
officecli help docx paragraph                   # Full schema: properties, aliases, examples, readbacks
officecli help docx set paragraph               # Verb-filtered: only props usable with `set`
officecli help docx paragraph --json            # Structured schema (machine-readable)
```

Format aliases: `word`→`docx`, `excel`→`xlsx`, `ppt`/`powerpoint`→`pptx`. Verbs: `add`, `set`, `get`, `query`, `remove`. MCP exposes the same schema via the single `command` string param: `{"command":"help docx paragraph"}` (the MCP tool has exactly one param, `command`, passed through to the CLI verbatim).

## Performance: Resident Mode

**Every command auto-starts a resident on first access** (60s idle timeout) — file-lock conflicts are automatically avoided. Explicit `open`/`close` recommended for longer sessions (12min idle):
```bash
officecli open report.docx       # explicitly keep in memory
officecli set report.docx ...    # no file I/O overhead
officecli close report.docx      # save and release
```

Opt out of auto-start: `OFFICECLI_NO_AUTO_RESIDENT=1`.

**Flush only at the non-officecli boundary.** officecli's own reads (`get`/`query`/`view`/`dump`) always see your latest edits — run `save` (keeps resident) or `close` (flush + release) only **before a non-officecli program reads the file** (python-docx/openpyxl, Word, a renderer, delivery/upload). Idle sessions auto-flush within seconds; `OFFICECLI_RESIDENT_FLUSH=each` makes every mutation flush before returning.

## Quick Start

**PPT:**
```bash
officecli create slides.pptx
officecli add slides.pptx / --type slide --prop title="Q4 Report" --prop background=1A1A2E
officecli add slides.pptx '/slide[1]' --type shape --prop text="Revenue grew 25%" --prop x=2cm --prop y=5cm --prop font=Arial --prop size=24 --prop color=FFFFFF
```

**Word:**
```bash
officecli create report.docx
officecli add report.docx /body --type paragraph --prop text="Executive Summary" --prop style=Heading1
officecli add report.docx /body --type paragraph --prop text="Revenue increased by 25% year-over-year."
```

**Excel:**
```bash
officecli create data.xlsx
officecli set data.xlsx /Sheet1/A1 --prop value="Name" --prop bold=true
officecli set data.xlsx /Sheet1/A2 --prop value="Alice"
```

## L1: Create, Read & Inspect

```bash
officecli create <file>               # Create blank .docx/.xlsx/.pptx (type from extension)
officecli view <file> <mode>          # outline | stats | issues | text | annotated | html
officecli get <file> <path> --depth N # Get a node and its children [--json]
officecli query <file> <selector>     # CSS-like query
officecli validate <file>             # Validate against OpenXML schema
```

### view modes

| Mode | Description | Useful flags |
|------|-------------|-------------|
| `outline` | Document structure | |
| `stats` | Statistics (pages, words, shapes) | |
| `issues` | Formatting/content/structure problems | `--type format\|content\|structure`, `--limit N` |
| `text` | Plain text extraction | `--start N --end N`, `--max-lines N` |
| `annotated` | Text with formatting annotations | |
| `html` | Static HTML snapshot — same renderer as `watch`, no server needed | `--browser`, `--page N` (docx), `--start N --end N` (pptx) |
| `screenshot` / `svg` / `pdf` / `forms` | PNG via headless browser / SVG (pptx slide) / PDF via exporter plugin / form-fields JSON via format-handler plugin | `-o`, `--screenshot-width/-height`, pptx `--grid N` |

### get — any XML path via element localName, `--depth N` expands children

```bash
officecli get report.docx '/body/p[3]' --depth 2 --json
officecli get slides.pptx '/slide[1]' --depth 1          # list all shapes on slide 1
officecli get data.xlsx '/Sheet1/B2' --json
```

**Stable ID addressing**: elements with stable IDs return `@attr=value` paths instead of positional indices — prefer these in multi-step workflows (positional indices shift on insert/delete, stable IDs do not):
```
/slide[1]/shape[@id=550950021]                    # PPT shape
/body/p[@paraId=1A2B3C4D]                         # Word paragraph
/comments/comment[@commentId=1]                    # Word comment
```

### query — CSS-like selectors

`[attr=value]`, `[attr!=value]`, `[attr~=text]`, `[attr>=value]`, `[attr<=value]`, `:contains("text")`, `:empty`, `:has(formula)`, `:no-alt`. Boolean `and`/`or`: `cell[value>5000 or value<100]`. Excel row-by-column-name: `Sheet1!row[Salary>5000]`.

```bash
officecli query report.docx 'paragraph[style=Normal] > run[font!=Arial]'
officecli query slides.pptx 'shape[fill=FF0000]'
```

## L2/L3: 编辑操作（DOM / Raw XML）

执行编辑（set/find/add/move/swap/remove/batch/pivottable/sort/文本锚点插入/clone/raw XML）前读取 **`references/dom-operations.md`**。

## Watch 与 Marks：交互选择

实时预览、浏览器点击选择（`get <file> selected`）、编辑提案审阅（`mark`/`unmark`/`get-marks`）详见 **`references/watch-marks.md`**。

## Common Pitfalls

| Pitfall | Correct Approach |
|---------|-----------------|
| `--name "foo"` | Use `--prop name="foo"` — all attributes go through `--prop` |
| Unquoted `[N]` paths in zsh/bash | Always quote: `'/slide[1]'` or `"/slide[1]"` (shell glob-expands brackets) |
| PPT `shape[1]` for content | `shape[1]` is typically the title placeholder. Use `shape[2]+` for content shapes |
| `/shape[myname]` | Name indexing not supported. Use numeric index or `@name=` (PPT only) |
| Guessing property names | Run `officecli help <format> <element>` to see exact names |
| Modifying an open file | Close the file in PowerPoint/WPS first |
| `\n` in shell strings | Use `\\n` for newlines in `--prop text="..."` |
| `$` in shell text | `--prop text="$15M"` strips `$15`. Use single quotes: `--prop text='$15M'`, or heredoc batch |

## Specialized Skills

`officecli load_skill <name>` — output is a SKILL.md, follow its rules.

**Loading rule**: pick the most specific match in "When to use"; if none fits, load the format default (`word` / `pptx` / `excel`). Scenes already contain the format default's rules — load **one** skill per artifact, never stack. Loaded rules persist across turns; don't re-load each reply. Two distinct artifacts → two separate loads.

| Format | Skills |
|--------|--------|
| Word | `word`（通用文档）· `academic-paper`（期刊/论文：APA/Chicago/IEEE/MLA、公式、SEQ+PAGEREF、多栏布局；不用于商务文档） |
| PowerPoint | `pptx`（通用 deck）· `pitch-deck`（**仅融资**）· `morph-ppt`（Morph 动画）· `morph-ppt-3d`（3D Morph：GLB/相机/景深） |
| Excel | `excel`（通用工作簿）· `financial-model`（财务模型/情景预测）· `data-dashboard`（CSV→KPI/分析仪表盘） |

Example: a fundraising deck task → `officecli load_skill pitch-deck` → use the printed rules.

## Notes

- Paths are **1-based** (XPath convention): `'/body/p[3]'` = third paragraph
- `--index` is **0-based** (array convention): `--index 0` = first position
- **Excel exception**: for `add --type row` and `add --type col`, `--index N` is **1-based** (matches OOXML RowIndex / column letter index)
- After modifications, verify with `validate` and/or `view issues`
- **When unsure**, run `officecli help <format> <element>` instead of guessing