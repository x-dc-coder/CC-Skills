# Claude 技能项目

## 核心约束：Python 脚本执行目录

**所有 skill 中的 Python 脚本必须先 `cd` 到 `~/.claude/skills` 再通过 uv 执行**，绝不能依赖用户当前项目的 `pyproject.toml`。

### 执行规则

```bash
cd ~/.claude/skills && uv run python <skill-name>/scripts/<script>.py ...
```

- `cd ~/.claude/skills` 确保 uv 的 `pyproject.toml` 解析起点正确
- 技能脚本位于各自的子目录下，如 `gitcode-workflow/scripts/gitcode_bootstrap.py`

### 为什么是 `cd` 而非 `--directory`

`uv run --directory` 只影响 `pyproject.toml` 的查找位置，但**脚本相对路径仍基于当前工作目录解析**。先 `cd` 再执行可以同时保证：pyproject.toml 正确 + 相对路径正确。

### 禁止的做法

```bash
# ❌ 错误：会解析当前项目（如 Words-Production）的 pyproject.toml
uv run python scripts/gitcode_issues.py ...

# ❌ 错误：可能缺少 skills 项目的依赖
python3 scripts/gitcode_issues.py ...

# ❌ 错误：--directory 不会改变相对路径的解析基准
uv run --directory ~/.claude/skills python scripts/gitcode_issues.py ...
```

### 为什么需要这个约束

- `uv run` 在当前目录向上查找最近的 `pyproject.toml` 来决定依赖环境
- 用户的项目（如 Words-Production）可能依赖 Windows-only 包（如 `pywin32`），在 WSL/Linux 下无法安装
- `~/.claude/skills` 有自己独立的 `pyproject.toml`，所有依赖都是跨平台的
- skill 脚本应该使用 skills 项目的 venv，不依赖也不污染用户项目的环境

## 核心约束：输出目录统一约定

**所有 SKILL 的文件输出必须遵循以下两级回退规则**，杜绝孤儿目录和 `/tmp/skills-output/<date>/` 垃圾堆积。

### 规则

| 优先级 | 条件 | 输出位置 | 示例 |
|--------|------|----------|------|
| **1（首选）** | 用户当前在工作项目目录下（即 cwd 不在 `~/.claude/skills`） | `<工作项目目录>/<skill-output-root>/<skill-name>/<filename>` | `/home/dc/projects/MyThesis/thesis-output/diagram-er/er-diagram.png` |
| **2（兜底）** | cwd 在 `~/.claude/skills` 或无明确工作项目 | `~/.claude/skills-output/<skill-name>/<filename>` | `~/.claude/skills-output/diagram-er/er-diagram.png` |

### skill-output-root 命名

- 论文类 skill（diagram-*、thesis-*、md-to-thesis-latex）：统一用 `thesis-output/`
- 数据库类（db-skill）：用 `db-output/`
- 文档提取类（word-extractor、paper-reader）：用 `doc-output/`
- 其他：用 `<skill-name>-output/`

### 禁止的做法

```bash
# ❌ 固定文件名导致互相覆盖
<项目>/thesis-output/img/diagram.png   # 所有 diagram skill 都叫 diagram.png

# ❌ /tmp 临时目录永久堆积
/tmp/skills-output/2026-07-15/diagram-er/diagram.png

# ❌ skill 目录内的 -workspace 孤儿目录
~/.claude/skills/diagram-architecture-workspace/
```

### 各 skill 输出文件名约定（避免覆盖）

| Skill | 输出文件名 |
|------|-----------|
| diagram-er | `er-diagram.png` |
| diagram-ers | `ers-diagram.png` |
| diagram-module | `module-diagram.png` |
| diagram-sequence | `sequence-diagram.png` |
| diagram-usecase | `usecase-diagram.png` |
| diagram-architecture | `architecture.<pdf\|png>` |
| diagram-flow | `flow.mmd` / `flow.png` |
| d2-paper | `<name>.<svg\|png\|pdf>` |
| thesis-writing | `第X章-章节名.md` / `full-thesis.md` |
| md-to-thesis-latex | `main.tex`（在 `thesis-output/latex/` 下） |
| word-extractor | `extracted.md` + `images/` |
| paper-reader | `paper-analysis/<pdf_stem>/` |

### paper-reader 例外

paper-reader 默认输出到**输入 PDF 同级**的 `paper-analysis/` 目录（已在上表注明），不走两级回退规则——因为它的输入路径已隐含输出位置。

### 实现

SKILL.md 中应明确写出输出路径规则，CLI 脚本应：
1. 接受 `--output <dir>` 显式参数（最高优先）
2. 无 `--output` 时，检测 cwd：若不在 `~/.claude/skills`，用 `<cwd>/<skill-output-root>/<skill-name>/`；否则用 `~/.claude/skills-output/<skill-name>/`
3. 自动 `mkdir -p` 创建输出目录
