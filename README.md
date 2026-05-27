# Claude Code Skills 统一环境管理

本文档说明本目录下 Python Skill 的统一环境管理方式。

> **注意**：本文件为辅助说明文档，不影响 Claude Code 的 Skill 系统。各子目录中的 `SKILL.md` 才是 Skill 的规范定义文件。

## 目录结构

```
~/.claude/skills/
├── README.md              # 本说明文档
├── pyproject.toml         # 统一依赖声明
├── uv.lock                # 锁定文件（精确版本）
├── .venv/                 # 统一的 uv 虚拟环境
├── diagram-er/
│   ├── SKILL.md
│   ├── .venv -> ../.venv  # 符号链接
│   └── scripts/
├── diagram-module/
│   ├── SKILL.md
│   ├── .venv -> ../.venv
│   └── scripts/
├── diagram-usecase/
│   ├── SKILL.md
│   ├── .venv -> ../.venv
│   └── scripts/
├── diagram-ers/
│   ├── SKILL.md
│   ├── .venv -> ../.venv
│   └── scripts/
├── diagram-sequence/
│   ├── SKILL.md
│   ├── .venv -> ../.venv
│   └── scripts/
├── diagram-flow/
│   └── SKILL.md
└── thesis-writing/
    └── SKILL.md
```

## 为什么统一管理

所有 Skill 均为自用，数量少且依赖简单，统一维护一份环境可以：
- 减少重复依赖安装，节省磁盘空间
- 降低维护成本（只需维护一个 `pyproject.toml`）
- 移植到新机器时，执行一次 `uv sync` 即可激活所有 Skill

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
uv run python -c "import PIL, sqlglot; print('OK')"
```

## 符号链接机制

包含 Python 脚本的 Skill 目录（`diagram-er`、`diagram-module`、`diagram-usecase`、`diagram-ers`、`diagram-sequence`）内包含一个指向统一环境的符号链接 `.venv`。这使得：

- 各 Skill 的 `SKILL.md` 中可以直接写 `uv run python -m scripts.cli ...`
- `uv` 在子目录执行时能够自动找到虚拟环境
- 实际上所有 Skill 共享同一个物理环境

## 工作目录依赖（重要）

`uv run` 通过当前工作目录查找 `pyproject.toml` 来定位虚拟环境。以下场景需注意：

1. **在项目目录内运行**
   ```bash
   cd ~/.claude/skills
   uv run python db-skill/scripts/pg_tool.py ...
   ```
   正常找到虚拟环境，推荐方式。

2. **在临时/外部目录运行**
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

4. **db-skill / 配置发现也依赖 cwd**
   `mysql_tool.py` 和 `pg_tool.py` 会从当前工作目录向上查找 `.db-skill/mysql.json` 或 `.db-skill/pg.json`。在项目根目录下运行才能正确发现配置，或使用 `--config` 显式指定。

## 当前依赖

| 包名 | 用途 |
|------|------|
| `Pillow` | 图片生成与处理（diagram 系列） |
| `sqlglot` | SQL 解析（diagram-er） |

Node 工具（非 Python 依赖）：
- `@mermaid-js/mermaid-cli`：用于 `diagram-sequence` 渲染 Mermaid 到 PNG（推荐用 `npx` 调用，避免全局安装）。

## 新增含 Python 的 Skill 时的 checklist

1. 在该 Skill 目录下创建符号链接：
   ```bash
   ln -s ~/.claude/skills/.venv ~/.claude/skills/<new-skill>/.venv
   ```
2. 如果新 Skill 需要新的 Python 包，在 `~/.claude/skills/pyproject.toml` 中添加依赖，然后执行 `uv lock` 或 `uv sync`。
3. 更新本 README 的依赖列表。
