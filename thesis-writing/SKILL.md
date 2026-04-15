---
name: thesis-writing
description: Use when writing undergraduate thesis content for science/engineering projects, generating structured Markdown from project code, opening reports and task specifications
---

# 毕业论文正文撰写 Skill

## 适用范围
- 理工科本科毕业论文（基于 SpringBoot 等 Web 系统类）
- 输出格式：Markdown
- 遵循无锡学院本科毕业论文撰写规范

## 阶段一：环境检查与项目分析

### 1.1 环境检查
1. 检查 python-docx 是否已安装：
   - 执行 `python3 -c "import docx"`
   - 若失败，执行 `pip3 install --break-system-packages python-docx`
2. 校验用户提供的文档文件：
   - 检查文件是否存在
   - 检查文件扩展名是否为 .docx
   - 若为 .doc 格式，提示用户转换为 .docx 后再继续

### 1.2 项目分析
1. 读取用户指定的开题报告、任务书（通过 python-docx 提取文本）
2. 扫描项目代码结构：
   - 前端：路由文件、页面组件、API 接口调用
   - 后端：Controller、Service、Entity/Model、数据库配置
3. 分析数据库表结构（从 Entity 类或 SQL 文件推断）
4. 输出"项目理解摘要"，请用户确认是否准确
   - 若用户指出遗漏或错误，补充分析后重新确认

## 阶段二：大纲生成

1. 读取 `references/thesis-template.md`，获取标准章节结构和字数分配
2. 根据项目分析结果，将模板中的占位符替换为实际内容：
   - 确定相关技术栈的具体名称
   - 确定需求分析中的角色和功能
   - 确定系统设计中的具体模块划分
   - 确定数据库实体和表结构
   - 确定第4章各功能模块的具体子节
3. 标注每章预估字数（确保总计 ≥ 15000 字）
4. 标注所有图片位置，引用 `references/image-spec.md` 的占位符格式
5. 呈现完整大纲，等待用户确认或修改

## 阶段三：逐章撰写

1. 读取 `references/example-output.md` 作为写作风格参考
2. 按大纲顺序逐章生成 Markdown 内容
3. 每章完成后写入 `thesis-output/第X章-章节名.md`
4. 每章完成后询问用户：
   - 确认，继续下一章
   - 需要修改（指出具体修改点后重新生成）
   - 调整大纲（回退到阶段二，修改大纲后从当前章节继续）
5. 全部章节完成后，进入阶段四

## 阶段四：合并与质量检查

1. 将所有章节合并为 `thesis-output/full-thesis.md`
2. **执行 Markdown 规范检查**（必须）：
   ```bash
   python3 thesis-output/check_markdown_spec.py --md thesis-output/full-thesis.md
   ```
   - 若检查失败，必须修复所有 ERROR 后才能继续
   - 建议修复所有 WARN 以获得最佳质量
3. 执行质量检查：
   - 统计正文总字数，检查是否 ≥ 15000 字
   - 检查图片编号是否连续（图X-1, X-2, ...无跳缺）
   - 检查表格编号是否连续（表X-1, X-2, ...无跳缺）
   - 检查章节编号层次是否一致（1, 1.1, 1.1.1）
   - 检查参考文献引用标记与参考文献列表是否一一对应
4. 输出检查报告，标注发现的问题
5. 若有问题，修复后重新检查；若无问题，完成

## Markdown 格式规范

所有生成的 Markdown 文档必须符合以下规范（由 `check_markdown_spec.py` 检查）：

### 图片格式
- **必须使用 Markdown 语法**：`![图X-X 标题](./path/to/image.png)`
- **禁止使用 HTML `<img>` 标签**
- 图片标题格式：`图X-X 标题`（如"图3-1 系统功能结构图"）
- **禁止在图片下方重复添加标题文字**（如 `**图3-1 系统功能结构图**`），标题应仅在图片的 alt 属性中体现

### 表格格式
- 表格前必须有规范表题：**`表X-X 标题`**
- 表题与表格之间不要有空行

### 其他规范
- 禁止使用 Setext 标题风格（`===` 或 `---`），使用 ATX 风格（`#` / `##`）
- 禁止在正文中保留 Mermaid 代码块（应渲染为图片后引用）
- 引用编号必须为正整数

## 写作规范要求
- 读取 `references/writing-norms.md` 获取详细写作规范
- 章节编号使用阿拉伯数字：1, 1.1, 1.1.1
- 图片使用文字占位符，格式见 `references/image-spec.md`
- 表格使用 Markdown 表格格式
- 参考文献格式遵循 GB/T 7714-2015
