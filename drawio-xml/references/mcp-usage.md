# MCP Server 使用手册（@next-ai-drawio/mcp-server v0.2.3）

> 本手册基于源码阅读 + 本机端到端实测（initialize → tools/list → start_session → create → get → export 全通）。
> 定位：drawio-xml skill 的**执行层**——负责会话状态、结构校验、编辑门控、多页、导出；质量规则由 SKILL 层负责。

## 一、安装与配置

```bash
# 无需安装，npx 直接拉取（Node ≥ 18）
npx -y @next-ai-drawio/mcp-server@latest
```

MCP 客户端配置（Claude Code / VS Code / Cursor / Cline 通用）：

```json
{
  "mcpServers": {
    "drawio": {
      "command": "npx",
      "args": ["@next-ai-drawio/mcp-server@latest"]
    }
  }
}
```

Claude Code CLI 一行接入：
```bash
claude mcp add drawio -- npx @next-ai-drawio/mcp-server@latest
```

环境变量：
- `PORT`：内嵌 HTTP 服务端口（默认 6002，被占用自动尝试至 6020）
- `DRAWIO_BASE_URL`：draw.io 页面来源（默认 `https://embed.diagrams.net`，私有化指向自托管）

## 二、10 个工具清单

| 工具 | 用途 | 关键参数 |
|---|---|---|
| `start_session` | **必须先调用**，打开浏览器实时预览 | 无；返回 sessionId + Browser URL |
| `create_new_diagram` | 新图（替换整个文档，含所有页） | `xml`：完整 mxfile 或裸 mxGraphModel（自动包装单页） |
| `load_diagram` | 从磁盘加载 .drawio（自动解压） | `filePath` |
| `edit_diagram` | 按 id 增/改/删 cell | `operations`（update/add/delete），可带 page_id/page_name/page_index |
| `get_diagram` | 取当前 XML（含浏览器端用户手工改动） | 可选 page 选择器 |
| `export_diagram` | 导出文件 | **`path`**（注意：不是 filePath！）支持 .drawio/.png/.svg，格式由扩展名识别 |
| `list_pages` | 列出所有页 | 无 |
| `add_page` | 追加新页（不破坏已有页） | page 名称等 |
| `rename_page` | 重命名页 | page 选择器 + 新名 |
| `delete_page` | 删除页（拒绝删最后一页） | page 选择器 |

## 三、协同工作流中的关键机制（SKILL + MCP）

### 3.1 编辑门控（edit-gate.ts）——防数据丢失的核心
- 机制：MCP 维护会话内最后一次 `get_diagram` 时的图状态快照。若用户在浏览器/桌面端手工修改了图，AI 基于**过期状态**提交 `edit_diagram` 会被**拒绝**（无副作用），并提示重新 `get_diagram` 后重试
- 用法：**每次编辑前先 `get_diagram`**；被拒绝时不要重试旧操作，重新读取最新状态再编辑
- 价值：多轮"AI 改 → 用户手动调 → AI 再改"的协同迭代不会互相踩踏

### 3.2 结构校验（xml-validation.ts）——底层质量兜底
- `validateAndFixXml`：XML 语法、重复属性、重复 id、标签配对、特殊字符转义、嵌套 mxCell 检查；超限（>1MB）报性能警告
- 每次 `create_new_diagram` / `edit_diagram` 写入时自动执行，失败会拒绝并给出修复提示
- **边界**：只查结构合法，不查视觉质量（重叠/越界/连线交叉照单全收——实测验证）

### 3.3 状态感知（get_diagram）——读取用户手工修改
- `get_diagram` 从浏览器拉取最新状态（含用户手动拖拽/改字），是协同迭代的"眼睛"
- 会话内存态（sessionId 前缀 mcp-，TTL 1 小时），`get_diagram` 总是返回最新

### 3.4 双层质检分工
| 层 | 检查内容 | 时机 |
|---|---|---|
| MCP 结构校验 | XML 合法、id 唯一、转义正确 | 每次写入时（自动） |
| SKILL 质检脚本（check-quality.py） | 节点重叠、越界、孤立边、注释 | 交付前（必跑） |

## 四、实测踩坑记录

1. **必须先 start_session**，否则任何工具报 `No active session. Please call start_session first.`
2. **export_diagram 参数名是 `path`**（zod schema 定义），用 filePath 会报 `expected string, received undefined`
3. start_session 用 `open` 包打开浏览器；WSL 无 DISPLAY 时浏览器可能打不开，但 HTTP server 仍运行，可用 `http://localhost:6002?mcp=<sessionId>` 手动访问
4. 浏览器预览默认加载 `embed.diagrams.net`（需联网）；离线/私有化设 `DRAWIO_BASE_URL`
5. HTTP server 仅绑定 127.0.0.1（安全修复后），勿直接暴露公网
6. MCP 仍为 Preview 阶段（issue #287），工具可能有变动
7. **无视觉校验**：缺陷 XML（重叠节点+边穿节点）实测被照单全收——布局质量必须靠 SKILL 质检脚本

## 五、协同工作流标准流程（配合 drawio-xml skill）

1. `start_session` → 得到 Browser URL，通知用户浏览器已打开预览（可随时手动调整）
2. 按质量规则生成 XML → `create_new_diagram`（新图）或 `load_diagram`（改已有文件）
3. 迭代闭环：
   - `get_diagram` 拿当前最新状态（感知用户手工改动）
   - 对比后 `edit_diagram` 按 id 精修（被编辑门控拒绝 = 用户又改了 → 重新 get_diagram）
   - 结构性大改用 `create_new_diagram` 重写
4. 交付前：`export_diagram` 前先跑 `python3 scripts/check-quality.py` 布局质检
5. `export_diagram`（path=xxx.drawio/png/svg）→ 交付文件路径
6. 多页场景：`list_pages` → `add_page`/`rename_page`/`delete_page`；页选择器用于 edit/get/export

## 六、相关生态（可选叠加）

- draw.io 官方 jgraph/drawio-mcp：`npx @drawio/mcp`，支持 Mermaid 输入 + libavoid 自动布线，与 next MCP 工具集不冲突可并存
- 社区 Agents365-ai/drawio-skill：单 SKILL.md，复杂图类型（SysML/BPMN/C4）+ 代码库转图
- 无头/CI：AI 生成 Mermaid → draw.io Desktop CLI `-x -f xml` 转换导出，免 MCP
