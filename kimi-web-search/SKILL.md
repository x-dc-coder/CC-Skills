---
name: kimi-web-search
description: >
  Use this skill whenever the user asks a question that requires real-time
  internet information, current events, or up-to-date data. This skill calls
  Kimi API's built-in $web_search tool to perform web searches and return
  results. Trigger on: questions about today's news, current prices,
  weather, recent events, latest technology, stock prices, or any query where
  the answer might have changed since training data cutoff. Also trigger when
  the user explicitly asks to search the web, use web search, or get latest
  information.
---

# Kimi Web Search Tool

## 概述

此 skill 通过调用 Kimi API 的内置 `$web_search` 工具执行联网搜索，获取实时信息。

**工作原理：**
- 当用户的问题需要实时信息时，运行 `scripts/kimi_search.py` 脚本
- 脚本调用 Kimi 的 `$web_search` builtin_function 执行搜索
- 搜索结果以 JSON 格式返回，由你整合到回答中

**核心特性：**
- 绕过 Kimi 模型自身的时间认知限制，可搜索未来年份的技术趋势和预测
- 支持普通模式（模型总结）和 Raw 模式（原始搜索结果）
- 自动拒绝检测 + Fallback 重试机制

---

## 环境配置

使用此 skill 前，需要配置 Kimi API 密钥。以下方式任选其一：

### 方式一：环境变量（推荐）

```bash
export MOONSHOT_API_KEY="your-api-key-here"
# 或
export KIMI_API_KEY="your-api-key-here"
```

### 方式二：Claude Code settings.json

在项目的 `.claude/settings.json` 中添加：

```json
{
  "env": {
    "MOONSHOT_API_KEY": "your-api-key-here"
  }
}
```

或在用户级别的 `~/.claude/settings.json` 中配置全局生效。

### 方式三：运行时传入

```bash
MOONSHOT_API_KEY=your-key uv run python scripts/kimi_search.py "搜索内容"
```

---

## 使用方法

当用户的问题需要实时信息时，执行以下步骤：

### Step 1：判断是否需要搜索

以下情况**应该**使用搜索：
- 询问今天/本周/本月的新闻或事件
- 询问当前天气、股价、汇率、价格
- 询问最新技术动态、产品发布、版本更新
- 询问技术文档、API 变更、框架新版本
- 询问"最近"、"最新"、"现在"相关的问题
- 用户明确说"帮我搜一下"、"上网查一下"
- 询问未来技术趋势、行业预测（脚本已绕过模型时间限制）

以下情况**不需要**搜索：
- 纯知识性问题（数学、历史事实、基础编程语法）
- 代码调试、代码 review
- 文件操作、代码生成

### Step 2：执行搜索

**普通模式**（模型总结搜索结果）：

```bash
python /home/dc-ubuntu/.claude/skills/kimi-web-search/scripts/kimi_search.py "用户搜索查询"
```

**Raw 模式**（返回原始搜索结果，不经过模型总结）：

```bash
python /home/dc-ubuntu/.claude/skills/kimi-web-search/scripts/kimi_search.py --raw "用户搜索查询"
```

Raw 模式适用于：
- 模型总结丢失了你关心的细节
- 你需要自行提取特定信息
- 搜索结果需要进一步处理

### Step 3：解析结果

脚本输出 JSON 格式：

```json
{
  "success": true,
  "searched": true,
  "result": "Kimi 基于搜索结果生成的回答内容...",
  "search_query": "实际执行的搜索关键词",
  "usage": {
    "prompt_tokens": 14230,
    "completion_tokens": 312,
    "total_tokens": 14542,
    "search_tokens": 13046
  }
}
```

### Step 4：整合回答

- 将 `result` 中的内容作为搜索结果的参考
- 用你自己的语言组织回答，不要原样照搬
- 如果搜索结果不够准确或完整，可以补充你的知识
- 如果搜索失败（`success: false`），告知用户并尝试用你的知识回答

---

## 搜索失败处理

| 错误 | 原因 | 处理方式 |
|------|------|----------|
| `API key not set` | 环境变量未配置 | 提示用户设置 `MOONSHOT_API_KEY` |
| `Input token length too long` | 搜索内容超出上下文限制 | 简化查询后重试 |
| `Model 未触发搜索` | 查询不需要实时信息 | 直接基于你的知识回答 |
| 网络/API 错误 | Kimi 服务端问题 | 告知用户服务暂时不可用 |
| 模型拒绝回答 | 触发了时间/能力限制 | 使用 `--raw` 模式获取原始结果 |

---

## 注意事项

1. **Token 消耗**：搜索内容计入 prompt tokens，一次搜索可能消耗 10000+ tokens。搜索结果中的 `usage.search_tokens` 显示搜索本身占用的 token 数。

2. **计费**：除 Token 费用外，每次 `$web_search` 调用还收取额外搜索费用。

3. **不要过度搜索**：只对确实需要实时信息的问题使用搜索，避免浪费 Token。

4. **脚本位置**：`scripts/kimi_search.py` 是此 skill 的核心执行脚本，确保路径正确。

5. **时间绕过**：脚本通过强化 system prompt 和 fallback 机制绕过了 Kimi 模型的时间认知限制，可以搜索未来年份的技术趋势和行业预测。
