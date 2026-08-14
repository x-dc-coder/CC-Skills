---
name: vision-workflow
description: 图像理解、网页截图核验、OCR 文字提取、科研绘图验证与本地图片批量分析的编排流程。当任务涉及看图、识图、图片内容理解、截图验证、图表解读或批量处理图片时使用本技能。
---

# Vision Workflow（视觉任务编排）

本技能编排 Vision MCP 工具（`vision_health` / `describe_image` / `analyze_screenshot` / `extract_text` / `verify_figure` / `batch_analyze`）。当模型本身无视觉能力时，通过调用这些工具完成视觉任务。

## 流程总则

1. 首次使用时先调用 `vision_health()`（DSH/Claude Code 中的命名为 `mcp__vision__vision_health`）确认服务在线；返回 `mock: true` 表示当前为模拟模式，结果不可信，必须在汇报中注明。
2. 所有工具返回统一契约 JSON：`{"ok": bool, "data": ..., "error": str?, "code": str?, "meta": {...}}`。`ok=false` 时读取 `error` 向用户解释，不要重试超过 2 次。
3. 输出给用户时标注模型与模式：`meta.model`、`meta.mock`、`meta.cross_validated`。

## 分层路由（性价比 / 旗舰）

- **日常性价比**：`describe_image` / `analyze_screenshot` / `extract_text` / `batch_analyze` 默认走性价比模型（qwen3-vl-flash / glm-4.6v-flash），成本最低。
- **质量要求高 / 旗舰**：`verify_figure` 走旗舰模型（glm-4.6v + qwen3-vl-plus 跨厂商交叉验证），结果最稳。
- 策略引擎内置失败升级与跨厂商回退，无需人工干预；`meta.tier` / `meta.model` 标注实际档位与模型。

## 场景 SOP

### A. 单图理解
1. 调用 `describe_image(path, question)`；question 要具体（对象/关系/文字/异常点）。
2. 直接引用返回的 `data.description`，不要脱离工具结果另行编造。

### B. 网页截图核验
1. 调用 `analyze_screenshot(path, checklist)`；checklist 用逗号分隔核验点（如"页面正常加载,无报错弹窗,关键元素可见"）。
2. 按 `data.results` 逐项汇报 pass/fail；fail 项附 note 并给出修复建议。

### C. OCR 文字提取
1. 调用 `extract_text(path, lang)`；lang 填 zh/en/自动。
2. 原样输出 `data.text`，不要润色；批量场景改用 batch_analyze。

### D. 科研绘图验证
1. 调用 `verify_figure(path, checks)`；checks 默认六项：title,axes,legend,trend,values,colors。
2. 汇报 `data.report`：逐项 pass/note、issues 清单；默认双模型交叉验证，结果见 `meta.cross_validated`。

### E. 批量图片分析
1. 调用 `batch_analyze(directory, pattern, question)`；工具返回摘要 + `report_path`（完整报告落盘 reports/）。
2. 用户需要详情时读取 report_path 对应的 JSON 文件，不要要求工具把全文回传。

## 失败回退

- `code=IMAGE_ERROR`：检查路径/格式/大小（上限 4MB），修正后重试。
- `code=PROVIDER_ERROR` 或提示未配置 key：告知用户补 ZHIPU_API_KEY（repo 根目录 .env）并把 config.json 的 mock 改为 false；或说明当前为 mock 结果。
- 性价比模型失败会自动升级旗舰模型（策略引擎内置），无需人工干预。

## 输出规范

- 每条结论注明来源工具与模式；mock 结果必须标注「模拟数据」。
- 科研/截图验证类输出使用清单式 markdown，fail 项加粗。
