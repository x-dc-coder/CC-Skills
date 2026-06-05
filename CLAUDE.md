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
