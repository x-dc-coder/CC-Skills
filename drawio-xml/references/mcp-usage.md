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

## 七、实测验证记录（2026-08-25，本地源码构建版）

> 验证环境：WSL + Node 24 + Chromium/Playwright + 本地构建 `packages/mcp-server/dist/index.js`。
> 结论：**MCP + 浏览器渲染 + 高清导出全链路可用，复杂论文级图（Transformer：21 顶点[19 形状+2 容器]+16 边）端到端通过。**

### 7.1 无头/无 DISPLAY 环境的三步法（关键）
1. `BROWSER=echo` 启动 server，避免 `open()` 在无 DISPLAY 时抛错：
   ```bash
   BROWSER=echo DRAWIO_EXPORT_SCALE=4 node packages/mcp-server/dist/index.js
   ```
2. start_session 返回 URL `http://localhost:6002?mcp=<sessionId>`（HTTP server 仍正常监听 127.0.0.1）
3. 用 Playwright/Chromium 打开该 URL 充当浏览器渲染器：
   - 页面 JS 自动 poll `/api/state`（2s 间隔）→ 加载 diagram XML → 渲染
   - 导出请求由浏览器 iframe postMessage 处理 → base64 回传 `/api/state`
   - **浏览器必须保持打开**，否则 export_diagram 超时（默认 10s，投影导出 15s）

### 7.2 PNG 高清导出（已参数化）
- **原版硬编码 `scale: 2`**（http-server.ts 两处），逻辑图 762×722 → PNG 1524×1444
- **已修改源码**：`DRAWIO_EXPORT_SCALE` 环境变量控制（默认 2），scale=4 实测 → **3048×2888（约 300DPI，论文可用）**
- 修改点：src/http-server.ts 三处（EXPORT_SCALE 常量 + MCP 导出 + 浏览器手动导出按钮）
- 发布版 npm 包仍是 0.2.3 旧行为；要用高清导出需本地构建或等上游合并

### 7.3 视觉质检闭环（VLM 校验的 DSH 等价实现）
主应用用 VLM（generateObject + /api/validate-diagram）对渲染截图做视觉校验并反馈修正。
DSH/Claude 侧等价：导出 PNG → 用 vision 工具（describe_image / analyze_screenshot）
核验（重叠/穿线/文字/完整性/布局）→ 发现问题 → edit_diagram 修正 → 再导出复检。
**实测**：vision 对导出 PNG 逐项核验通过（无重叠/无穿线/编辑改动可见/论文级排版）。

### 7.4 编辑门控实测
create → get_diagram → edit_diagram（update 标签 + add 节点）→ get_diagram 验证改动
→ export PNG，全流程通过。编辑门控正常：基于过期状态编辑会被拒并提示重新 get_diagram。

### 7.5 常用调试
- 端口：PORT=6002（默认），被占用自动 6003-6020
- server 日志：stdout 前缀 [MCP-DrawIO]
- 会话 TTL 1 小时；HTTP 仅绑 127.0.0.1
- 页面控制台：Playwright console_messages 可查 iframe 错误


### 7.6 重大坑：PNG 导出黑底（暗色主题）问题与解决方案（2026-08-25 实测）

**症状**：`export_diagram` 导出的 PNG 是**黑底**（深色像素占比 70%+），放入浅色论文文档中节点/背景异常。用户浏览器暗色模式时更明显。

**根因**（实测排除法）：
- iframe 容器页/画布背景均浅色（bodyBg 241、pageBg 255、geDiagramContainer 236），但导出 PNG 四角纯黑 (0,0,0)
- 设置 `ui=light`/`theme=default` URL 参数、`emulateMedia({colorScheme:'light'})`、`graph.background='#ffffff'`（mxGraph 实例不可访问，window.mxGraph 是类）、export 加 `backgroundColor:'#FFFFFF'` 参数——**全部无效**，PNG 仍黑底（文件大小完全一致，导出内容未变）
- draw.io embed 的 PNG 导出固定使用暗色画布背景（与 iframe 主题无关）

**关键事实**：`export_diagram` 的 **SVG 导出是自适应的**——SVG 头部 `color-scheme: light dark`，所有文字 fill 为 `light-dark(rgb(17,17,17), rgb(223,223,223))`（浅色渲染器=黑字，暗色渲染器=浅字），节点 fill 为显式浅色（#ffffff/#d9d9d9...）。

**解决方案（已验证）**：**SVG → 强制 light 渲染 → PNG**：
1. `export_diagram` 导出 .svg
2. 用 Chromium/Playwright 加载 SVG（`file://` 路径），`emulateMedia({ colorScheme: 'light' })`
3. evaluate 放大 SVG（`svg.setAttribute('width', W*4+'px')`），视口设 `W*4 × H*4`
4. screenshot → 白底黑字高清 PNG（实测 3328×2020、深色像素仅 4%）
5. PIL 可选裁剪边缘（`ImageOps.autocontrast` 或背景裁剪）

**注意**：
- SVG 交付物本身是"自适应"的（用户暗色浏览器打开 SVG 会显示浅色文字）——如需固定浅色，用上述转换后的 PNG
- 转换脚本要点：SVG 文档无 `document.body`（根是 svg），用 `document.documentElement`；run_code_unsafe 环境无 require/fs/setTimeout，用 `file://` + `page.waitForTimeout`

