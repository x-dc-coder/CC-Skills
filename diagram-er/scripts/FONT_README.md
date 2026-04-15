# 字体配置说明

## 内置字体支持

本工具优先从 `fonts/` 目录加载字体，确保在不同设备上都能正确显示中文。

## 推荐的免费字体

由于版权原因，以下字体需要您自行获取：

### 1. 思源黑体 Noto Sans CJK（推荐）
- 开源免费，支持简体中文
- 下载地址：https://github.com/notofonts/noto-cjk/releases
- 推荐文件：`NotoSansCJK-Regular.ttc` 或 `NotoSansSC-Regular.otf`

### 2. 文泉驿微米黑
- 开源免费
- 下载地址：http://wenq.org/wqy2/index.cgi?MicroHei
- 推荐文件：`wqy-microhei.ttc`

### 3. 阿里巴巴普惠体
- 免费商用
- 下载地址：https://fonts.alibabadesign.com/

## 使用方法

1. 下载上述任意一种字体的 Regular（常规）版本
2. 将字体文件放入 `scripts/fonts/` 目录
3. 工具会自动检测并使用

## 字体加载优先级

1. `scripts/fonts/` 目录下的字体文件
2. 系统字体（Linux/Windows/macOS）
3. PIL 默认字体（不支持中文，仅作备选）

## 注意事项

- 字体文件名不限，工具会自动识别常见的中文字体文件
- 建议使用 TTC/TTF/OTF 格式
- 如需指定特定字体，可设置环境变量：`export DIAGRAM_FONT_PATH=/path/to/font.ttf`
