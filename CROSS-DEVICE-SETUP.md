# CROSS-DEVICE-SETUP.md

# 跨设备环境搭建手册

> 本手册回答：「在一台**新设备**（Linux/WSL 或 Windows）上，如何从零搭起这套 Claude Code skills 的运行环境」。
> 已运行环境的日常管理（uv sync、重建 venv 等）见 [README.md](README.md)。
> 环境分类沿用 README 的三类策略：**A 统一共享 venv** / **B 独立重型 venv（paper-reader）** / **C 无 venv（外部工具）**。

---

## 一、从零搭建总览（4 步）

```
① 前置工具（git + uv + node）
② 克隆仓库到目标位置
③ 装依赖（统一 venv + paper-reader + 外部工具）
④ 配置密钥/凭据 + 全量验证
```

---

## 二、① 前置工具

| 工具 | 用途 | Linux / WSL | Windows |
|------|------|-------------|---------|
| **git** | 克隆/同步 | `sudo apt install git` | Git for Windows / `winget install Git.Git` |
| **uv** | Python 依赖管理（A/B 类必需） | `curl -LsSf https://astral.sh/uv/install.sh | sh` | `irm https://astral.sh/uv/install.ps1 \| iex` |
| **node + npm** | mermaid-cli / officecli 等 | `sudo apt install nodejs npm` | `winget install OpenJS.NodeJS` |

> WSL 侧安装后记得 `source ~/.bashrc` 使 uv/node 进入 PATH。

---

## 三、② 克隆仓库

仓库地址：`git@gitcode.com:x-dc-coder/CC-Skills.git`（需配置 SSH key，见第 ⑤ 步）

```bash
# Linux / WSL —— 克隆到用户级 skills 目录
git clone git@gitcode.com:x-dc-coder/CC-Skills.git ~/.claude/skills

# Windows —— 克隆到 Claude Code 读取的 skills 目录（PowerShell）
git clone git@gitcode.com:x-dc-coder/CC-Skills.git "$env:USERPROFILE\.claude\skills"
```

> **注意**：Windows 侧 `C:\Users\<你>\.claude\skills` 必须已有目录（Claude Code 会在首次运行时创建）。
> 仓库自带 `.gitattributes`，所有文本文件统一 LF，Windows checkout 不会产生 CRLF 问题。

---

## 四、③ 安装依赖（按环境分类执行）

### A 类：统一共享 venv（大多数 Python skill）

```bash
cd ~/.claude/skills
uv sync                 # 按 pyproject.toml + uv.lock 创建 .venv 并装齐依赖

# Linux/WSL：重建各 skill 的 .venv 符号链接（指向统一环境）
for skill in diagram-er diagram-ers diagram-module diagram-sequence diagram-usecase db-skill; do
  ln -sf ../.venv "$skill/.venv"
done
```

Windows 符号链接受限时（无开发者模式），**改用绝对路径模式**：脚本统一用
`uv run --project ~/.claude/skills python <skill>/scripts/<script>.py`，不依赖各 skill 下的 `.venv` 符号链接。

### B 类：paper-reader（重型 GPU venv，约 6GB）

```bash
# Linux/WSL：跑自带 bootstrap（自动建 venvs/marker + venvs/mineru）
bash ~/.claude/skills/paper-reader/scripts/bootstrap.sh
```

**Windows / GPU 场景**：paper-reader 通过 WSL 桥接调用 Windows 原生 Python 跑 GPU，
需按 `CLAUDE.md` 的 GPU 桥接规范单独建 Windows venv（uv 建 `E:\venvs\marker`、`E:\venvs\mineru` 并装 cu128 torch）。
> 这部分细节见 CLAUDE.md「GPU 桥接」「用 uv 管理 Windows 侧 Python 环境」章节。

### C 类：外部工具（非 Python，按需安装）

见下表，只装你实际会用到的 skill 对应的工具。

| 外部工具 | 服务 skill | Linux / WSL | Windows |
|---------|-----------|-------------|---------|
| **d2** CLI | d2-paper | `curl -fsSL https://d2lang.com/install.sh \| sh -s --` | `winget install --id Terrastruct.D2 -e` 或 `scoop install d2` |
| **d2-render**（工具包） | d2-paper | 见 d2-paper/SKILL.md「工具与安装」（依赖本地 toolkit，非全局二进制） | 需在 Windows 侧准备对应渲染脚本 |
| **graphviz**（dot） | diagram-architecture | `sudo apt install graphviz` | `winget install Graphviz.Graphviz` |
| **poppler-utils**（pdftoppm） | diagram-architecture（PDF→PNG 预览） | `sudo apt install poppler-utils` | `winget install oschwartz10612.Poppler` |
| **中文字体** | diagram-* | `sudo apt install fonts-noto-cjk` | SimSun 自带；如需可装思源字体 |
| **mermaid-cli**（mmdc） | diagram-flow / diagram-sequence | `npm install -g @mermaid-js/mermaid-cli`（或按 SKILL.md 用 `npx -y`） | 同左（需 node） |
| **xelatex** + texlive-lang-chinese | md-to-thesis-latex | `sudo apt install texlive-xetex texlive-lang-chinese` | MiKTeX：`winget install MiKTeX.MiKTeX` |
| **officecli** | officecli | `curl -fsSL https://d.officecli.ai/install.sh \| bash` | `irm https://d.officecli.ai/install.ps1 \| iex` |
| **mysql / psql 客户端** | db-skill | `sudo apt install mysql-client postgresql-client` | 官网客户端，或直接用现有 Docker 容器（mysql8 / postgis） |
| **keenable-cli** | keenable-cli、unified-search | `curl --proto '=https' --tlsv1.2 -LsSf -o /tmp/keenable-install.sh https://github.com/keenableai/keenable-cli/releases/latest/download/keenable-cli-installer.sh` | 官方暂以 Linux/macOS 为主，见其仓库说明 |
| **kimi-webbridge** | kimi-webbridge | `curl -fsSL https://cdn.kimi.com/webbridge/install.sh \| bash`（装到 `~/.kimi-webbridge/bin/`） | 同左 + 安装浏览器扩展登录会话 |

---

## 五、④ 配置密钥/凭据

| Skill | 需要的凭据 | 配置位置 | 说明 |
|-------|-----------|---------|------|
| **gitcode-workflow** | `GITCODE_TOKEN` | 环境变量（如 `~/.bashrc` 导出） | 用于 gitcode API |
| **gitcode-workflow** | SSH key | `~/.ssh/gitcode_wsl_ed25519` + `~/.ssh/config` 的 `Host gitcode.com` 条目 | 私钥 600、config 600 |
| **unified-search** | tavily / firecrawl API key | `unified-search/config.json` 的 `api_keys.<源>.value`，或填入对应 `env_var` 指定的环境变量 | 密钥不进 git（config.json 已 gitignore） |
| **doubao-vision** | 豆包 API key | SKILL.md「API 配置」段 | — |
| **kimi-webbridge** | 浏览器登录会话（无 key） | 浏览器扩展 + daemon | daemon 状态见 `references/operations.md` |
| **db-skill** | 数据库连接 | 项目目录下的 `.db-skill/mysql.json` / `.db-skill/pg.json` | 脚本从 cwd 向上查找，或 `--config` 显式指定 |
| **keenable-cli** | keenable 配置 | 见 keenable-cli/SKILL.md「配置」 | — |

> **安全提醒**：所有带 key 的文件（`config.json`、`.db-skill/*.json`）都已被 `.gitignore` / `.git/info/exclude` 排除，**不要**手动 `git add -f` 提交。

---

## 六、全量验证

```bash
# ① 统一 venv 关键依赖
cd ~/.claude/skills
uv run python -c "import PIL, sqlglot, psycopg2, pymysql; print('py deps OK')"

# ② 外部工具（按需）
d2 --version              # d2-paper
dot -V                    # diagram-architecture
mmdc --version            # diagram-flow/sequence（如全局安装）
xelatex --version         # md-to-thesis-latex
officecli --version       # officecli
mysql --version && psql --version   # db-skill

# ③ 密钥（按需）
printenv GITCODE_TOKEN    # gitcode-workflow
```

---

## 七、平台差异注意点

| 主题 | Linux / WSL | Windows |
|------|-------------|---------|
| **行尾** | 无感 | `.gitattributes` 已统一 LF；不要用 `core.autocrlf true` |
| **符号链接** | `ln -sf ../.venv <skill>/.venv` | 无开发者模式时改用 `uv run --project` 绝对路径模式 |
| **GPU（paper-reader）** | 不直接用 GPU 训练 | 通过 WSL 桥接 Windows 原生 Python（见 CLAUDE.md「GPU 桥接」） |
| **环境变量转发** | — | WSL→Windows 子进程需 `WSLENV` 白名单（见 CLAUDE.md） |
| **同步方式** | `git pull` | 同左；同机 WSL→Windows 可用 rsync 落盘 |

---

## 八、常见问题

- **`uv run` 报找不到包** → 未在 skills 根目录执行；先 `cd ~/.claude/skills` 或改用 `--project ~/.claude/skills`
- **Windows 上 `.venv` 符号链接失效** → 用 `uv run --project` 绝对路径模式，或 `mklink /J` 建 junction
- **中文变方框** → 缺中文字体 / texlive-lang-chinese（见外部工具表）
- **kimi-webbridge 不工作** → 按 `references/operations.md` 的启动/诊断表排查（含陈旧 PID 文件场景）
- **paper-reader OOM** → 按 `--gpu-fraction` / `--max-workers` 限制并发（见 CLAUDE.md「GPU 多路并发铁律」）
