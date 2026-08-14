# Claude Code Skills 统一环境管理

本文档说明本目录下 Python Skill 的统一环境管理方式。

> **跨设备搭建手册**：新设备（Linux/WSL 或 Windows）从零配置环境，见 [CROSS-DEVICE-SETUP.md](CROSS-DEVICE-SETUP.md)。

> **注意**：本文件为辅助说明文档，不影响 Claude Code/OpenCode 的 Skill 系统。各子目录中的 `SKILL.md`（需含 YAML frontmatter）才是 Skill 的规范定义文件。

## 目录结构

```
~/.claude/skills/
├── README.md              # 本说明文档
├── CLAUDE.md              # 执行约束（cd ~/.claude/skills 再 uv run）
├── pyproject.toml         # 统一依赖声明
├── uv.lock                # 锁定文件（精确版本）
├── .venv/                 # 统一的 uv 虚拟环境（所有轻量 skill 共享）
│
├── diagram-er/            # 单表 ER 图
│   ├── SKILL.md
│   ├── .venv -> ../.venv  # 符号链接到统一环境
│   └── scripts/
├── diagram-ers/           # 多实体 ER 图
│   ├── .venv -> ../.venv
│   └── ...
├── diagram-module/        # 功能模块树形图
│   ├── .venv -> ../.venv
│   └── ...
├── diagram-sequence/      # UML 时序图
│   ├── .venv -> ../.venv
│   └── ...
├── diagram-usecase/       # UML 用例图
│   ├── .venv -> ../.venv
│   └── ...
├── db-skill/              # MySQL/PostgreSQL 工具
│   ├── .venv -> ../.venv  # 已统一（曾为独立 venv）
│   └── scripts/
├── word-extractor/        # .docx 提取
│   └── scripts/
├── unified-search/        # 6 源聚合搜索
│   └── scripts/
├── gitcode-workflow/      # Git/GitCode 工作流
│   └── scripts/
│
├── paper-reader/          # ⚠️ 例外：持有独立重型 venvs
│   ├── SKILL.md
│   ├── scripts/
│   └── venvs/             # 独立 venv（不共享，含 GPU 模型权重）
│       ├── marker/        # ~5.1GB（Marker + 模型）
│       └── mineru/       # ~613MB（MinerU + 模型）
│
├── diagram-flow/          # 纯 Mermaid 代码生成，无 Python
├── diagram-architecture/  # 纯 Graphviz DOT，无 Python
├── d2-paper/              # 纯 D2 语言，无 Python
├── doubao-vision/         # curl 调 API，无 Python
├── keenable-cli/          # 二进制 CLI，无 Python
├── kimi-webbridge/        # curl 调 daemon，无 Python
├── md-to-thesis-latex/    # 纯 xelatex，无 Python
├── thesis-writing/        # 双模式论文写作（本科毕设 + 期刊论文），含 profiler + checker
├── thesis-ref-check/      # 纯 Bash/grep，无 Python
└── wsl-windows-bridge/      # WSL→Windows 三层桥接 + GPU 资源治理，含 Python 脚本但使用系统 Python，不纳入统一 .venv
```

## 三类环境策略

| 类别 | 环境 | 适合的 Skill | 说明 |
|------|------|-------------|------|
| **A. 统一共享** | `.venv/` 符号链接 | diagram-er/ers/module/sequence/usecase, db-skill, word-extractor, unified-search, gitcode-workflow, thesis-writing | 依赖轻量（Pillow/sqlglot/psycopg2/pytest 等），共享一份 venv |
| **B. 独立重型** | skill 内 `venvs/` | paper-reader | 含 GPU 模型权重（5GB+），不可合并，`.gitignore` 已忽略 |
| **C. 无统一 venv** | 系统/Windows Python | diagram-flow, diagram-architecture, d2-paper, doubao-vision, keenable-cli, kimi-webbridge, md-to-thesis-latex, thesis-ref-check, wsl-windows-bridge | 无统一 venv（使用系统/Windows Python） |

## 统一执行约定（所有 Python skill 必须遵守）

**所有 Python 脚本必须先 `cd ~/.claude/skills` 再用 `uv run` 执行**，绝不依赖用户当前项目的 `pyproject.toml`。

### 标准格式

```bash
cd ~/.claude/skills && uv run python <skill-name>/scripts/<script>.py ...
```

### 为什么是 `cd` 而非 `--directory`

`uv run --directory` 只影响 `pyproject.toml` 的查找位置，但**脚本相对路径仍基于当前工作目录解析**。先 `cd` 再执行可同时保证：pyproject.toml 正确 + 相对路径正确。

### 例外：diagram-* 系列的 `scripts.cli` 模块

diagram-er/ers/module/sequence/usecase 使用 Python 包形式（`-m scripts.cli`），需进入 skill 子目录：

```bash
cd ~/.claude/skills/diagram-er && uv run python -m scripts.cli ...
```

这是因为 `-m scripts.cli` 要求 `scripts/` 在 cwd 下。其 `.venv` 符号链接确保 uv 仍解析到统一环境。

## 环境管理命令

### 添加新依赖

```bash
cd ~/.claude/skills
uv add <package-name>
```

### 同步环境（新机器/重装后）

```bash
cd ~/.claude/skills
uv sync
```

### 验证环境

```bash
cd ~/.claude/skills
uv run python -c "import PIL, sqlglot, psycopg2, pymysql; print('OK')"
```

### 重建符号链接（新机器/重装后必做）

```bash
cd ~/.claude/skills
for skill in diagram-er diagram-ers diagram-module diagram-sequence diagram-usecase db-skill; do
  ln -sf ../.venv "$skill/.venv"
done
```

### paper-reader 重型 venv 重建

```bash
bash ~/.claude/skills/paper-reader/scripts/bootstrap.sh
```

## 工作目录依赖（重要）

`uv run` 通过当前工作目录查找 `pyproject.toml` 来定位虚拟环境。以下场景需注意：

1. **在 skills 目录内运行（推荐）**
   ```bash
   cd ~/.claude/skills
   uv run python db-skill/scripts/pg_tool.py ...
   ```
   正常找到虚拟环境。

2. **在临时/外部目录运行（错误）**
   ```bash
   cd /tmp
   uv run python ~/.claude/skills/db-skill/scripts/pg_tool.py ...
   ```
   `uv` 在 `/tmp` 找不到 `pyproject.toml`，会使用系统默认 Python，导致依赖缺失（如 `psycopg2` 找不到）。

3. **子进程调用时应使用 `sys.executable`**
   当脚本需要作为子进程在其他目录运行时，应使用当前 Python 解释器的绝对路径，而非 `uv run`：
   ```python
   import sys
   subprocess.run([sys.executable, "db-skill/scripts/pg_tool.py", ...])
   ```

4. **db-skill 配置发现也依赖 cwd**
   `mysql_tool.py` 和 `pg_tool.py` 会从当前工作目录向上查找 `.db-skill/mysql.json` 或 `.db-skill/pg.json`。在项目根目录下运行才能正确发现配置，或使用 `--config` 显式指定。

## 当前依赖

| 包名 | 用途 |
|------|------|
| `Pillow` | 图片生成与处理（diagram-er/ers/module/sequence/usecase） |
| `sqlglot` | SQL 解析（diagram-er） |
| `python-docx` | .docx 提取（word-extractor） |
| `psycopg2-binary` | PostgreSQL（db-skill） |
| `pymysql` | MySQL（db-skill） |
| `cryptography` | 加密（db-skill） |
| `requests` | HTTP 请求（kimi-web-search 已删，unified-search 等） |
| `beautifulsoup4` | HTML 解析 |
| `openai` | OpenAI 兼容 API |
| `httpx` | 异步 HTTP |
| `pyyaml` | YAML 解析 |
| `feedparser` | RSS/Atom 解析 |

Node 工具（非 Python 依赖）：
- `@mermaid-js/mermaid-cli`：用于 `diagram-sequence` 渲染 Mermaid 到 PNG（推荐用 `npx` 调用，避免全局安装）。

## WSL ↔ Windows 桥接 Skill

以下 skill 需要 Windows 侧执行，不适用于纯 Linux 环境：

| Skill | Windows 依赖 | 机制 |
|------|------------|------|
| `paper-reader` | `E:\venvs\marker`、`E:\venvs\mineru` | `paper_reader.py` 自动检测 WSL，通过 `cmd.exe` 桥接 GPU 到 Windows 原生 Python |
| `wsl-windows-bridge` | `cmd.exe`、`powershell.exe`、`reg.exe` 等 | 三层桥接：cmd.exe(~55ms) / Direct EXE(~10ms) / PowerShell(~600ms) + GPU 资源治理（GpuLimits + GpuGovernor） |

## 新增含 Python 的 Skill 时的 checklist

1. 在该 Skill 目录下创建符号链接：
   ```bash
   ln -sf ~/.claude/skills/.venv ~/.claude/skills/<new-skill>/.venv
   ```
2. 如果新 Skill 需要新的 Python 包，在 `~/.claude/skills/pyproject.toml` 中添加依赖，然后执行 `uv lock` 或 `uv sync`。
3. 如果新 Skill 依赖 GPU/重型模型（如 paper-reader），保持独立 `venvs/`，并在 `.gitignore` 中添加忽略条目。
4. SKILL.md **必须**以 YAML frontmatter 开头（`---` 包裹的 `name` + `description`），否则 OpenCode 无法识别。
5. 更新本 README 的依赖列表和环境分类表。
