# docs-sync 设计方案：三种触发方式对比

> 关联 Issue: #4 feat: 提交后自动同步 Wiki 文档

## 背景

主仓库代码发布后，自动分析变更内容，通过 LLM 将 `docs/` 中的源码级文档加工为 Wiki 中的发布级文档，并推送到 GitCode Wiki 仓库。

## 核心数据流（三种方式通用）

```
git push 代码
     │
     ▼
┌─────────────────┐
│ 1. 收集变更上下文  │  ← git diff / commit message / 变更文件列表
└────────┬────────┘
         ▼
┌─────────────────┐
│ 2. 匹配映射规则   │  ← .gitcode-docs-map.json 决定更新哪些 wiki 页面
└────────┬────────┘
         ▼
┌─────────────────┐
│ 3. LLM 生成文档   │  ← 传入 diff + 现有 wiki 内容 + 页面目标 → 生成新内容
└────────┬────────┘
         ▼
┌─────────────────┐
│ 4. 提交 Wiki      │  ← clone → 写入 .md → commit → push
└─────────────────┘
```

---

## 方式 A：CLI 手动触发

### 触发方式

```bash
cd ~/.claude/skills && uv run python gitcode-workflow/scripts/gitcode_bootstrap.py \
  docs-sync --project /path/to/project
```

用户在 publish 完成后，执行此命令进行文档同步。

### 可选参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--since` | 从哪个 commit 开始分析 | `HEAD~1`（最近一次提交） |
| `--dry-run` | 只生成预览，不实际 push wiki | `false` |
| `--pages` | 指定更新哪些 wiki 页面（逗号分隔） | 全部匹配的页面 |
| `--review` | 生成后暂停等待人工确认再 push | `true` |

### 流程时序

```
用户                       CLI                          Wiki Git
 │                         │                              │
 │  gitcode-workflow       │                              │
 │  docs-sync              │                              │
 │ ──────────────────────► │                              │
 │                         │  git diff HEAD~1             │
 │                         │  读取 .gitcode-docs-map.json │
 │                         │  git clone wiki              │
 │                         │ ───────────────────────────► │
 │                         │ ◄─── wiki 文件列表 ────────── │
 │                         │                              │
 │                         │  LLM 分析变更 + 生成文档      │
 │                         │                              │
 │  展示预览：              │                              │
 │  - 将更新 3 个页面       │                              │
 │  - API文档.md (+120行)  │                              │
 │  - CHANGELOG.md (+5行)  │                              │
 │  - 架构说明.md (修改15行)│                              │
 │ ◄────────────────────── │                              │
 │                         │                              │
 │  确认 (y)                │                              │
 │ ──────────────────────► │                              │
 │                         │  git add → commit → push     │
 │                         │ ───────────────────────────► │
 │                         │ ◄────── push OK ──────────── │
 │  完成                    │                              │
 │ ◄────────────────────── │                              │
```

### 优劣分析

| ✅ 优势 | ❌ 劣势 |
|---------|---------|
| 完全可控，每次变更可审查 | 每次 publish 后多一步操作 |
| 可选 `--dry-run` 只看不写 | 容易忘记执行 |
| 可以选择性更新指定页面 | 需要记住命令 |
| 失败不影响代码 publish | |
| 实现最简单 | |

### 实现复杂度

- `lib/wiki.py`：约 80 行（clone、write、commit、push）
- `lib/docs_sync.py`：约 200 行（diff 解析、映射匹配、LLM 调用编排）
- CLI 集成：约 50 行（新增子命令 + 参数）
- **总计：约 330 行新代码**

---

## 方式 B：publish 后自动触发

### 触发方式

在 `publish` 命令成功 commit + push 代码后，自动调用 docs-sync。

```bash
# 默认启用，可关闭
cd ~/.claude/skills && uv run python gitcode-workflow/scripts/gitcode_bootstrap.py \
  publish --commit-message "feat: xxx" --auto-docs-sync

# 或通过配置控制
# ~/.config/gitcode-workflow/config.json
{
  "docs_sync": {
    "enabled": true,
    "auto_after_publish": true,
    "require_confirmation": true   // true=展示预览并确认, false=全自动
  }
}
```

### 流程时序

```
用户                       publish                      docs-sync               Wiki Git
 │                         │                              │                        │
 │  publish                │                              │                        │
 │ ──────────────────────► │                              │                        │
 │                         │  preview 验证                 │                        │
 │                         │  commit + push 代码           │                        │
 │                         │ ───────────────────────────────────────────────────► │
 │                         │ ◄────── push OK ─────────────────────────────────── │
 │                         │                              │                        │
 │                         │  ── 自动触发 docs-sync ──►   │                        │
 │                         │                              │  clone wiki            │
 │                         │                              │ ─────────────────────► │
 │                         │                              │ ← wiki 内容 ────────── │
 │                         │                              │                        │
 │                         │                              │  LLM 生成              │
 │                         │                              │                        │
 │  预览（require_confirmation=true 时）:                   │                        │
 │  - 代码已推送成功 ✅                                     │                        │
 │  - 文档更新预览:                                        │                        │
 │    · API文档.md (+80行)                                │                        │
 │    · CHANGELOG.md (+3行)                               │                        │
 │  确认推送文档? (y/n/skip)                                │                        │
 │ ◄───────────────────────────────────────────────────── │                        │
 │                         │                              │                        │
 │  y                      │                              │                        │
 │ ──────────────────────► │                              │                        │
 │                         │                              │  push wiki             │
 │                         │                              │ ─────────────────────► │
 │                         │                              │ ← OK ───────────────── │
 │  完成                    │                              │                        │
 │ ◄────────────────────── │                              │                        │
```

### 优劣分析

| ✅ 优势 | ❌ 劣势 |
|---------|---------|
| 一次操作完成所有事情 | publish 流程变长 ~5-15 秒（LLM 调用） |
| 不会忘记更新文档 | 文档生成失败会让人困惑（虽然代码已推送成功） |
| 与 publish 绑定，文档和代码天然关联 | 对于纯文档变更（docs:）提交，可能无限循环 |
| 可配置 `require_confirmation` 自由切换 | 如果 wiki clone 失败会阻塞流程 |

### 失败处理

```
docs-sync 失败 → 代码已推送成功 → 提示用户:
  "⚠️ 文档同步失败: {原因}
   可以稍后手动执行: gitcode-workflow docs-sync --since HEAD~1"
```

**重要**：docs-sync 失败**绝不回滚**代码 publish。两者完全解耦。

### 实现复杂度

- 依赖方式 A 的全部代码
- `publish` 流程修改：约 30 行（调用 + 错误处理）
- 配置文件扩展：约 20 行
- **总计：在方式 A 基础上 +50 行**

---

## 方式 C：Webhook 全自动

### 触发方式

在 GitCode 仓库设置 Webhook（`push_events`），指向你的接收服务。每次代码推送后，GitCode 向你的服务发送 POST 请求，服务处理文档同步。

### 架构

```
GitCode                         你的服务 (自建/Cloudflare Workers/等)
──────                         ────────────────────────────────
 │                                │
 │  git push master               │
 │  ────── push_events ─────────→ │
 │  {                             │
 │    "ref": "refs/heads/master", │  1. 验证 Webhook 签名
 │    "commits": [...],           │  2. clone wiki 仓库
 │    "repository": {...}         │  3. 用 API 获取 commit diff
 │  }                             │  4. LLM 生成文档更新
 │                                │  5. push wiki 仓库
 │                                │  6. 可选: 通知用户
 │                                │
 │  ◄── 文档已更新到 wiki ─────── │
```

### 流程时序

```
开发者          GitCode                       你的服务                   Wiki Git
 │                │                              │                        │
 │  git push      │                              │                        │
 │ ─────────────► │                              │                        │
 │                │  push_events POST             │                        │
 │                │ ────────────────────────────► │                        │
 │                │                              │  验证签名               │
 │                │                              │  识别分支（只处理master）│
 │                │                              │                        │
 │                │                              │  API: 获取 commit diff  │
 │                │ ◄─────────────────────────── │                        │
 │                │  commits JSON ──────────────► │                        │
 │                │                              │                        │
 │                │                              │  clone wiki             │
 │                │                              │ ─────────────────────► │
 │                │                              │ ← wiki 内容 ────────── │
 │                │                              │                        │
 │                │                              │  LLM 生成               │
 │                │                              │                        │
 │                │                              │  push wiki              │
 │                │                              │ ─────────────────────► │
 │                │                              │ ← OK ───────────────── │
 │                │                              │                        │
 │  文档已更新     │                              │                        │
 │ ◄───────────── │  （用户在 wiki 页面看到更新）  │                        │
```

### 优劣分析

| ✅ 优势 | ❌ 劣势 |
|---------|---------|
| 完全自动化，开发者零操作 | 需要部署一个持续运行的服务 |
| 支持团队多人协作，所有人的 push 都会触发 | 服务维护成本（监控、重启、更新） |
| 可以结合更多 GitCode events | 网络问题可能导致服务不可达 |
| 灵活扩展（通知、统计、审计等） | 安全性需要 Webhook 签名验证 |
| 与 publish CLI 完全解耦 | 延迟取决于服务部署位置 |

### 部署选项

| 方案 | 成本 | 复杂度 |
|------|------|--------|
| **Cloudflare Workers** | 免费额度（10 万次/天） | 低，JS/TS 单文件 |
| **自建 VPS** | ~$5/月 | 中，需维护 |
| **GitCode Actions** | 可能免费 | 低，但不确定是否支持自定义 Actions |
| **Raspberry Pi / 本地** | 电费 | 中，需要公网可达 |

### 实现复杂度

- Webhook 接收服务：约 100 行
- GitCode Webhook 配置：通过现有 API 创建
- 签名验证：约 30 行
- 复用了方式 A 的 docs-sync 核心逻辑
- **总计：在方式 A 基础上 +150 行 + 部署**

---

## 三种方式对比总表

| 维度 | A. CLI 手动 | B. publish 自动 | C. Webhook 全自动 |
|------|------------|----------------|-------------------|
| **触发者** | 用户执行命令 | publish 流程自动调用 | GitCode push 事件 |
| **操作步数** | publish + 额外一步 | publish 一步完成 | git push 一步完成 |
| **人工审查** | ✅ 默认展示预览 | ✅ 可配置 | ❌ 全自动无审查 |
| **失败影响** | 不影响代码 | 代码已推送，文档失败单独提示 | 不影响代码推送 |
| **适用人数** | 个人 | 个人/小团队 | 团队（任意规模） |
| **部署依赖** | 无 | 无 | 需要服务运行 |
| **实现行数** | ~330 行 | ~380 行（含 A） | ~480 行（含 A）+ 部署 |
| **维护成本** | 零 | 零 | 低~中 |
| **幂等性** | 靠用户判断 | 靠用户判断 | 需自行处理重复事件 |
| **最合适的阶段** | **第一阶段实现** | **第二阶段集成** | **第三阶段（可选）** |

---

## 推荐实施路线

```
Phase 1: 方式 A (CLI)
  ├── lib/wiki.py        ← Wiki git 仓库操作
  ├── lib/docs_sync.py   ← 核心分析+LLM编排
  └── CLI 子命令          ← docs-sync 子命令
  预计工作量: 2-3 小时
  产出: 可以手动同步文档到 Wiki

Phase 2: 方式 B (publish 集成)
  ├── 修改 publish 流程    ← 调用 docs-sync
  ├── 配置文件扩展         ← docs_sync 配置段
  └── 错误处理             ← 失败不回滚代码
  预计工作量: 0.5 小时
  产出: publish 时自动同步文档

Phase 3: 方式 C (Webhook) — 可选
  ├── webhook 接收服务     ← 独立部署
  ├── webhook 签名验证     ← 安全
  └── 通知机制             ← 推送到 IM/邮件
  预计工作量: 2-4 小时 + 部署
  产出: 完全自动化
```

---

## 配置文件设计

```jsonc
// ~/.config/gitcode-workflow/config.json 新增
{
  "docs_sync": {
    // 开关: 是否启用文档同步
    "enabled": true,

    // 方式 B: publish 后自动触发
    "auto_after_publish": true,

    // 方式 B: 自动触发时是否需要人工确认
    "require_confirmation": true,

    // LLM 配置
    "llm": {
      "provider": "claude",          // claude | kimi | openai
      "model": "claude-sonnet-4-6",  // 模型版本
      "max_tokens": 4000
    },

    // 默认分析最近 N 次提交
    "default_since": "HEAD~1"
  }
}
```

```jsonc
// 项目根目录 .gitcode-docs-map.json（版本控制）
{
  "wiki_repo": "x-dc-coder/Words-Production.wiki",
  "branch": "main",
  "rules": [
    {
      "name": "API文档更新",
      "when": {
        "paths": ["src/**/*.py"],
        "types": ["feat", "refactor", "fix"]
      },
      "update": "API文档.md",
      "prompt": "分析代码变更，更新 API 文档。关注新增/修改/删除的函数签名、参数和返回值，保留原有文档的结构和风格"
    },
    {
      "name": "配置变更记录",
      "when": {
        "paths": ["pyproject.toml", "*.cfg", "*.ini", ".env.example"],
        "types": ["*"]
      },
      "update": "环境配置.md",
      "prompt": "分析依赖和配置变化，更新环境配置文档"
    },
    {
      "name": "更新日志",
      "when": {
        "paths": ["*"],
        "types": ["*"]
      },
      "update": "CHANGELOG.md",
      "prompt": "基于提交信息，在 CHANGELOG 顶部追加一条简明的版本变更记录，格式: ## {日期} - {提交摘要}"
    }
  ]
}
```

---

## 常见问题

### Q: 如果 wiki 页面被人在 Web 上手动编辑了，docs-sync 会覆盖吗？

A: 会。docs-sync 走的是 git clone → 修改 → commit → push 流程。如果 Web 上有未合并到 git 的编辑（GitCode wiki 是否能同时在 Web 和 git 编辑待验证），会产生冲突。建议团队约定 wiki 只能通过 docs-sync 更新，或者至少在执行 docs-sync 前先 git pull。

### Q: LLM 生成的内容质量如何保证？

A: 方式 A 和 B 都支持 `--review` / `require_confirmation`，生成后展示 diff 预览，人工确认后才 push。方式 C 是全自动的，建议初期只用 A/B，对 LLM 质量建立信心后再启用 C。

### Q: 如果代码提交只是修改了文档（docs:），会不会循环更新？

A: 需要做去重处理。映射规则可以配置 `"types": ["feat", "refactor", "fix"]` 排除 `docs` 类型。或者 docs-sync 判断如果本次提交 90%+ 的变更是 `.md` 文件，则跳过。

### Q: Token 权限够吗？

A: 够。已验证 `GITCODE_TOKEN` 可以对 wiki 仓库进行 clone/push，无需额外的 SSH 配置。
