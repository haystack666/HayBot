# 模型供应商页面原型

打开 `index.html` 即可使用。单文件包含所有样式、图标和交互，无外部依赖、无 API 调用；不修改正式应用、真实供应商或机器人配置。

## 信息结构

- **连接管理**：紧凑列表，按用途、名称与状态筛选；展示默认模型、使用者和验证状态。支持编辑、添加、删除演示连接。
- **服务目录**：按用途查找接入类型，普通 API 与订阅计划分别展示；选择后打开配置抽屉，随服务用途显示字段与测试区域。
- **模型分配**：分别为机器人配置对话、TTS、STT、Embedding 与 Rerank，含语音回复开关。

沿用正式页面的黑白灰色值、216px 侧栏、按钮、边框及圆角；支持浅色、深色和移动端。

## 类型覆盖

保留现有 5 种对话类型，新增 13 种，共 18 种：

DeepSeek、DeepSeek Responses、Kimi、Kimi Code Plan、MiniMax、MiniMax Token Plan、Zhipu、Xiaomi、Xiaomi Token Plan、xAI、OpenRouter、Azure OpenAI、Gemini OpenAI API、Gemini Compatible、OpenAI Compatible、OpenAI Responses、Anthropic Compatible、Ollama。

TTS 7 种：OpenAI TTS、小米 MiMo TTS、阿里云百炼 TTS、MiniMax TTS、火山引擎 TTS、Azure TTS、Gemini TTS。

STT 4 种：小米 MiMo STT、Whisper（Local）、Whisper（API）、讯飞星火。

保留 4 种 Embedding、2 种 Rerank。合计 **35 种接入类型**。小米按 MiMo 显示，同时支持搜索 `mino`。

## 原型边界

连接、使用状态、保存和测试结果均为演示。TTS 试听只展示播放区域，不产生真实音频；STT 上传只显示文件名，不读取文件内容。表单用于讨论信息结构，实际地址、服务字段、支持格式和能力需在正式接入时逐项核对。所有修改仅留在当前页面，刷新会还原。

## 检查

已用 Chrome 检查完整类型覆盖、名称搜索、TTS/STT 测试流程、连接保存、模型分配、深浅主题和 390px 移动端；没有脚本异常和横向溢出。

预览截图：`preview-light.png`、`preview-dark.png`、`preview-catalog.png`、`preview-tts.png`、`preview-assignments.png`、`preview-mobile.png`、`preview-mobile-editor.png`。
