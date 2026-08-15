---
name: gitcode-workflow
description: Bootstrap git for local projects on WSL or Linux, apply repo-local git identity defaults, use master as the default branch, use gitcode as the default remote name, preview the exact pending files before any upload, freeze the reviewed snapshot into a .git review manifest before publish, optionally create and connect a private gitcode repository, and analyze an existing project to propose a layered commit strategy. Use this skill whenever the user needs to initialize git, configure local repo identity, read commit rules from docs/rules/git-commit.md with fallback to the bundled template, create a gitcode remote after explicit user instruction, publish only after the user confirms both the reviewed file set and the final commit message, or suggest how to split an already-built project into multiple clean commits without making repo changes. Also use when the user mentions gitcode, wants to push to gitcode, needs to create a gitcode repository, or wants to manage git workflow with token-based authentication.
---

# GitCode Git Workflow

## Quick Commands（快捷指令）

识别用户意图后直接执行对应指令。**不要提前检查环境变量、SSH key 或配置文件** — 脚本自带完整校验，失败时根据具体报错排查即可。

### 仓库操作

| 用户意图 | 指令 |
|---------|------|
| 初始化本地 Git | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_bootstrap.py local-only --project <path> --json` |
| 预览待提交文件 | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_bootstrap.py preview --project <path> --json` |
| 创建远端仓库 | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_bootstrap.py create-remote --project <path> --json` |
| 提交并推送 | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_bootstrap.py publish --project <path> --commit-message "<msg>" --json` |
| 分析已有项目 | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_bootstrap.py adopt-existing-project --project <path> --json` |
| 查看个人信息 | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_bootstrap.py profile --action show --json` |

### Issue 操作

| 用户意图 | 指令 |
|---------|------|
| 列出 Issues | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_issues.py --owner <o> --repo <r> list [--state open\|closed\|all]` |
| 创建 Issue | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_issues.py --owner <o> --repo <r> create --title "..." [--body "..."] [--labels "..."]` |
| 查看 Issue | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_issues.py --owner <o> --repo <r> get <number>` |
| 更新 Issue | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_issues.py --owner <o> --repo <r> update <number> [--title "..."] [--state open\|closed]` |
| 关闭 Issue | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_issues.py --owner <o> --repo <r> close <number>` |
| 重新打开 Issue | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_issues.py --owner <o> --repo <r> reopen <number>` |
| 查看 Issue 评论 | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_issues.py --owner <o> --repo <r> comments <number>` |
| 添加 Issue 评论 | `uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_issues.py --owner <o> --repo <r> comment-create <number> --body "..."` |

**原则：先执行，失败再排查。** `--owner` 和 `--repo` 在仓库目录下运行时自动从 git remote 推断，可不指定。

---

## 执行环境约束

所有 Python 脚本用 `uv --project` 指定 skill 项目运行（**保持当前工作目录为项目仓库**，脚本自动从 git remote 推断 owner/repo）：
```bash
uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/<script>.py ...
```

## 输出规范（脚本 --json 模式）

- **stdout 是纯 JSON**，日志/进度走 stderr —— 读取结果时**勿用 `2>&1` 混流**（会把
  `[gitcode-workflow][...]` 日志混进 JSON）。
- 长输出会截断：重定向到文件后分段读：
  ```bash
  uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_bootstrap.py preview --project . --json > /tmp/gw_preview.json 2>/tmp/gw_preview.err
  ```
  再按需读取 `/tmp/gw_preview.json`（安全扫描在 `safety_scan` 字段，候选输入在
  `diff_excerpt` / `files_by_kind` / `type_hints` / `scope_hints`）。

## Decide the mode first

1. 判断用户意图：
   - **local-only**：初始化本地仓库、配置 Git 身份和忽略规则
   - **adopt-existing-project**：分析已有目录，输出分层提交策略（只读，不改任何文件）
   - **create-remote**：创建 GitCode 远端仓库（需用户明确要求）
   - **preview**：预览待提交文件，生成候选提交信息（安全操作，写 review manifest 到 `.git/`）
   - **publish**：提交并推送（需用户确认最终提交信息后执行）

2. 副作用边界：
   - `local-only`：仅改仓库本地配置
   - `adopt-existing-project`：纯分析，零修改
   - `create-remote`：外部副作用（创建远端仓库、SSH key）
   - `preview`：写 `.git/gitcode-workflow-review.json`
   - `publish`：外部副作用（push），需用户显式确认

3. 配置优先级：CLI args > 环境变量 > `~/.config/gitcode-workflow/config.json` > 内置默认值

4. 提交规则：
   - 优先读 `docs/rules/Git-Commit.md`（项目内）
   - 不存在时用 `references/commit-rules.md`（内置模板）

---

## local-only workflow

```bash
uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_bootstrap.py local-only --project /path/to/project --json
```

此模式：初始化 Git、配置仓库级身份（默认 `x-dc-coder / x.dc0521@gmail.com`）、设置 `master` 为默认分支、检测技术栈、追加 `.gitignore` + `.git/info/exclude` 规则。

完成后汇报结果并停止。不预览、不创建远端、不提交。

---

## adopt-existing-project workflow

```bash
uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_bootstrap.py adopt-existing-project --project /path/to/project --max-layers 6 --json
```

输出启发式分层提交建议（路径+文件名推断），标注为"需人工审查"。不初始化 Git、不修改文件。

---

## create-remote workflow

```bash
uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_bootstrap.py create-remote --project /path/to/project --json
```

先执行 local-only，再：获取 GitCode 用户信息、创建/复用 ED25519 SSH key、上传公钥、创建**私有**个人仓库、设置 `gitcode` 为默认 remote。

仅在用户**明确要求**创建远端时执行。

---

## preview workflow

```bash
uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_bootstrap.py preview --project /path/to/project --json
```

预览待提交文件（按 added/modified/deleted/renamed/untracked 分组）、安全扫描高风险文件、生成候选提交信息、写入 review manifest。

### 提交信息生成（子代理主力）

候选提交信息**完全通过子代理生成**（无脚本 fallback）：

1. 运行 `preview` 拿到 `diff_excerpt`、`files_by_kind`、`type_hints`、`scope_hints`
2. 判断改动规模：
   - **单批次**（files ≤ 6）：spawn **1 个子代理**，生成 3 个候选
   - **多批次**（files > 6 或多种改动类型混合）：先按逻辑关系分组（如核心代码/工具链/文档），每组 spawn **1 个子代理**，每组生成 2-3 个候选
3. 子代理模型：**deepseek-v4-flash**（快速、低成本）
4. **子代理必须先把候选 JSON 落盘、再在回复中重述**（防主代理中断/通知丢失）：
   - 落盘路径：`.git/gitcode-workflow-candidates/<batch>.json`（纯 JSON，无代码块包裹）
   - 主代理从文件读取候选，不以子代理回复文本为唯一来源
5. 候选展示后由开发者审查确认，再决定采用或调整

**候选信息结构**（3 条精简候选，开发者选其一或自行修改）：
- 全部为精简 Conventional Commits 格式 — 中文 subject ≤50 字符，动宾结构
- 格式：`<type>(<scope>): <subject>`
- 3 个候选从不同角度概括（如功能实现 / 问题修复 / 结构调整），便于快速挑选
- ⭐ 不要求逐文件 body——如需补充细节，开发者确认后自行添加即可

**子代理 prompt 模板**：
```
你是代码审查专家。请仔细阅读以下 git diff，分析每个文件的具体改动内容。
基于实际改动内容生成 3 个候选提交信息（均为精简 Conventional Commits 格式）。

- 中文 subject，≤50 字符，动宾结构
- 格式：<type>(<scope>): <subject>
- type 从 {valid_types} 中选择
- 3 个候选从不同角度概括（如功能实现 / 问题修复 / 结构调整），供开发者挑选

改动文件：
{file_list}

Diff 内容：
{diff_excerpt}

注意：
- 若某个文件标注 "preview omitted because the file is larger than ..."，用
  `git diff HEAD -- <file>`（已跟踪文件）或读取文件的结构摘要（untracked）补充分析，
  不要猜测其内容。
- 完成分析后，先把候选 JSON **原样写入** .git/gitcode-workflow-candidates/<batch>.json
  （纯 JSON 文件，无 markdown 代码块、无前后缀文本），再在回复中重述同一 JSON。

返回 JSON，candidates 数组固定 3 个元素。
```

**结构化输出 Schema**：
```json
{
  "type": "object",
  "properties": {
    "candidates": {
      "type": "array",
      "minItems": 3,
      "maxItems": 3,
      "items": {
        "type": "object",
        "properties": {
          "type": {"type": "string", "enum": ["feat","fix","docs","style","refactor","perf","test","chore","revert"]},
          "scope": {"type": "string"},
          "subject": {"type": "string", "maxLength": 50}
        },
        "required": ["type", "scope", "subject"]
      }
    }
  },
  "required": ["candidates"]
}
```

**候选 JSON 容错解析**（子代理回复可能带前后缀文本）：
1. 优先读落盘文件 `.git/gitcode-workflow-candidates/<batch>.json`（文件应为纯 JSON）
2. 若读回复文本：剥离 markdown 代码块（```json ... ```），取首个 `{` 到末个 `}` 之间的子串再 `json.loads`
3. 解析失败（`JSONDecodeError`）：把原文发给子代理要求"仅重述 JSON，无其他文本"

### 预览后的流程

1. 展示分组后的待提交文件列表 + 安全扫描结果
2. 展示子代理生成的候选信息，由开发者审查确认
3. 多批次时：先展示分批方案和各批候选，等待用户逐批确认
4. 用户确认最终消息后，记录 review manifest 路径和 snapshot hash
5. **不要**在用户确认前执行 publish

### review manifest 结构（.git/gitcode-workflow-review.json）

| key | 类型 | 说明 |
|---|---|---|
| `version` | int | manifest 版本 |
| `project_path` | str | 项目路径 |
| `created_at` | str | 生成时间（ISO） |
| `head_commit` | str | 生成时的 HEAD 提交 |
| `status_lines` | list[str] | `git status --short` 原文行 |
| `counts` | dict | 各状态文件计数 |
| `files` | list[dict] | 逐文件详情（path/kind/status/raw） |
| `stage_targets` | list[dict] | 建议的提交分组（含候选提示） |
| `snapshot_hash` | str | 工作区快照哈希（**worktree 一致性校验**：publish 前重新计算比对，不一致须重跑 preview） |

---

## publish workflow

仅用户明确确认提交信息后执行：

```bash
uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_bootstrap.py publish --project /path/to/project --commit-message "<msg>" --json
```

**单批次**：加载 review manifest → 验证 worktree 未变 → 安全扫描 → stage 文件 → commit → push → 清除 manifest

**多批次**：优先用 publish 的 `--batches <json>`（每批 `{files, message}`，脚本统一做
manifest 校验 → snapshot 比对 → 安全扫描 → 逐批 commit → 一次 push）；脚本不可用时
才手动逐批 `git add <files>` + `git commit -m "<msg>"`，全部完成后一次 `git push`。

如果 worktree 在 preview 后发生了变化，必须重新运行 preview。

**push 完成判定（9p 挂载已知噪音）**：`/mnt/e` 等 9p 挂载下 push 可能伴随
`error: chmod on .../.git/config.lock failed: Operation not permitted` —— 只要输出含
`To gitcode.com:...` 与 `master -> master`（或对应分支）即为成功；该警告无害，可顺带
检查 `.git/config.lock` 无残留即可。

---

## 中断恢复 SOP（主代理中断 / 子代理通知丢失）

1. `list_agents`（scope: descendants）查看子代理状态：`ready` = 结果已产出可恢复
2. 读候选落盘文件 `.git/gitcode-workflow-candidates/*.json` —— 有文件则直接取结果
3. 无落盘文件时 `send_message` 让子代理"原样重述最终 JSON，不要重新分析"
4. 子代理上下文也未留存（回复称无法重述）→ 按 review manifest 的 `files` / `stage_targets`
   重新 spawn 子代理（输入用 manifest 中记录的 diff 信息）
5. 恢复完成后校验 `snapshot_hash` 是否仍与工作区一致，再进入候选确认流程

## SSH 发布前检查

1. `~/.ssh/config` 需有 `Host gitcode.com` 条目（`User git`、`IdentityFile`、`IdentitiesOnly yes`）
2. 权限：`chmod 600 ~/.ssh/config`，私钥 `600`
3. 连通性：`ssh -T git@gitcode.com`

非默认 key 且无 ssh-agent 时可用临时 fallback：
```bash
GIT_SSH_COMMAND='ssh -i ~/.ssh/<your-key> -o IdentitiesOnly=yes' git push -u gitcode master
```

---

## 分支与合并规范

### 分支命名

| 前缀 | 用途 | 示例 |
|------|------|------|
| `feat/` | 新功能 | `feat/user-auth` |
| `fix/` | Bug 修复 | `fix/login-redirect` |
| `docs/` | 文档更新 | `docs/api-reference` |
| `refactor/` | 代码重构 | `refactor/payment-flow` |
| `chore/` | 工程杂项 | `chore/update-deps` |
| `exp/` | 实验性分支 | `exp/new-algorithm` |

### 分支策略

- 默认分支：`master`
- 新功能/修复：从 `master` 切出分支，开发完成后合并回 `master`
- **禁止 force-push 到 `master`**
- 合并方式：默认 `git merge`（保留完整提交历史）。小改动、单 commit 特性可用 `git merge --squash`
- 合并前确保目标分支已拉取最新

---

## .gitignore 规范

### 两层规则体系

| 文件 | 用途 | 纳入版本控制 | 示例 |
|------|------|-------------|------|
| `.gitignore` | 团队共享的忽略规则 | ✅ 是 | `target/`, `__pycache__/`, `node_modules/`, `.idea/`, `*.log` |
| `.git/info/exclude` | 本机的敏感/私有规则 | ❌ 否 | `.env`, `*.key`, `*.pem`, `application-local.yml`, `credentials*.json` |

### 禁止做法

- ❌ 将密钥/证书/本地配置模式放在 `.gitignore`（必须放在 `.git/info/exclude`）
- ❌ 将 IDE 个人配置（如 `.vscode/settings.json`）放在 `.gitignore`（团队统一 IDE 配置时才放 gitignore）
- ❌ 手动编辑 `.gitignore` 后不运行 `preview` 验证
- ❌ 在 `.gitignore` 中逐文件列出所有环境配置变体（应使用通配符）

### 标准忽略项（脚本自动追加）

- **通用**：`.DS_Store`, `Thumbs.db`, `.idea/`, `.vscode/`, `*.log`, `logs/`
- **Java/Spring**：`target/`, `build/`, `.gradle/`, `*.class`, `out/`
- **Python**：`__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.venv/`, `venv/`, `dist/`, `*.egg-info/`
- **Go**：`bin/`, `coverage.out`, `*.coverprofile`, `*.test`

---

## 提交信息规范

### 格式约束

- **绝对禁止**在提交信息末尾或正文添加 `Co-Authored-By` 标记
- 格式：`<type>(<scope>): <subject>`
- 可选 type：`feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `revert`
- scope 强烈建议提供，命名简短清晰
- 中文 subject，不超过 50 字符，结尾不加标点
- 多行消息：subject 与 body 之间空一行，body 每行不超过 72 字符

### 提交规则来源

优先读项目内的 `docs/rules/Git-Commit.md`，不存在时用内置模板 `references/commit-rules.md`。

---

## CJK 路径

仓库含中文/日文/韩文文件名时，设置：
```bash
git config core.quotepath false
```

---

## Issue 管理

### commit message 引用关闭 Issue

在提交信息中使用 `fix #N` 或 `close #N` **可能**自动关闭 Issue，但这取决于：
- 仓库的 PR 设置是否启用"合并后自动关闭关联 Issue"
- commit 是否通过 PR 合并（直接推送到默认分支的 commit 通常不会触发自动关闭）

**可靠做法**：commit-push 后，手动调用 `close` 命令关闭 Issue：
```bash
uv run --project ~/.claude/skills python ~/.claude/skills/gitcode-workflow/scripts/gitcode_issues.py close <number>
```

### Issue 使用场景

- **个人 TODO**：用 Issue 替代本地待办列表
- **Bug 跟踪**：记录发现的问题，关联修复提交
- **功能规划**：标记未来要实现的功能

---

## 安全规则

- 团队共享的忽略规则放 `.gitignore`
- 本机敏感文件模板放 `.git/info/exclude`
- GitCode config 文件放在仓库外（`~/.config/gitcode-workflow/config.json`）
- SSH key 只存路径，不存私钥内容
- Token 优先走环境变量（`GITCODE_TOKEN`），避免写入 JSON
- 每次 push 前自动扫描：`.env`、密钥文件、证书、service-account JSON、本地 Spring 配置

---

## Worked examples

### 示例 A：初始化本地 Git
用户："帮我在这个项目里先初始化 Git，但先不要连远端。"
→ 执行 `local-only`，汇报结果后停止。

### 示例 B：预览提交
用户："帮我看看现在会提交哪些文件，并给我几个提交信息备选。"
→ 执行 `preview` → spawn 子代理分析 diff → 展示分组文件 + 安全发现 + 候选信息 → 等待用户确认。

### 示例 C：确认后推送（单批次）
用户："就用第 2 个提交信息，开始推送。"
→ 执行 `publish`，校验 manifest，推送，汇报结果。

### 示例 D：确认后推送（多批次）
用户："第一批用选项 1，第二批用选项 2，第三批用选项 1，帮我推送。"
→ 逐批 `git add` + `git commit`，全部完成后 `git push`。

---

## 配置文件

- [references/config-format.md](references/config-format.md) — 配置格式与优先级
- [references/commit-rules.md](references/commit-rules.md) — 内置提交规范模板
- [references/safety-and-ignore.md](references/safety-and-ignore.md) — 安全扫描与忽略策略
- [references/api-capabilities.md](references/api-capabilities.md) — GitCode API v5 完整清单
- [assets/config.example.json](assets/config.example.json) — 配置模板

## 脚本

- [scripts/gitcode_bootstrap.py](scripts/gitcode_bootstrap.py) — 核心 bootstrap CLI
- [scripts/gitcode_issues.py](scripts/gitcode_issues.py) — Issue 管理 CLI
- [scripts/lib/](scripts/lib/) — 共享模块（api, config, git, preview, manifest, safety 等）
