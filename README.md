# MangaCleanup

ttkbootstrap GUI：漫画清字。两种策略共用同一提示词：

- **过审 = 全图编辑**：整图发给图像编辑模型，失败重试（默认 2 次）后自动回退到截屏回填。
- **不过审 = 截屏回填**：按 `.neko` 中 `texts.json` 的 `bubbleBox`（回退 `box`）+ 可配置扩展像素（默认 20px）截块，逐块编辑后回填原位。

`.neko` 本质是 zip，`texts.json` 位置不固定，程序内自动查找；按 `project.json` 文件名优先匹配，失败按顺序回退，查不到则兼容处理（截屏模式无框时转全图）。

## 环境（uv 隔离，Python 3.12.8）

```powershell
uv venv --python 3.12.8
uv sync
uv run python main.py
```

## 界面

- **运行**页：输入文件夹 / neko 工程、运行模式快捷切换、开始 / 取消 / 重试失败、图像列表（双击切换强制截屏）、日志。
- **配置**页：协议与模型、处理参数、提示词、保存配置。进度条常驻窗口底部。

## 配置

- 协议可选 `OpenAI / Gemini / Grok / Mock`（离线自测），模型名均为可编辑 Combobox，直传 API。
  - Grok 走 `{base}/images/edits` JSON 接口（`image_url` 传图，xAI 不支持 multipart），Key 用 `XAI_API_KEY`。
- Key 优先读环境变量 `OPENAI_API_KEY` / `GEMINI_API_KEY`（或 `GOOGLE_API_KEY`）/ `XAI_API_KEY`，勾选记住才写入 `config.json`（该文件含敏感信息，不提交）。
- 分辨率 `size`：留空即 `auto`（默认）；OpenAI 填 `WxH`（如 `1024x1536`），Gemini / Grok 填 `1K / 2K` 或宽高比（如 `16:9`）。下拉选项随协议切换，不适用的值切换时自动清空。
- 输出默认 `输入目录/cleaned/`，文件名 `原名_cleaned.jpg`，附 `results.csv`。
