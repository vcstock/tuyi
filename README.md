# 图译 TuYi

图译识别图片里的文字，调用所选翻译服务，再按照原图文字区域回填译文。仓库提供 Windows 便携版和可自托管的网页版。

| 版本 | 运行方式 | OCR |
| --- | --- | --- |
| Windows | 下载 [Windows 64 位 EXE](https://github.com/vcstock/tuyi/releases/latest/download/TuYi-Windows-x64.exe)，双击运行 | 优先使用 DirectML GPU，失败时回退 CPU |
| 网页版 | 在 Docker 主机执行 `docker compose up -d --build`，用浏览器打开 | 在服务器上使用 CPU |

两版均支持选择图片或粘贴图片、术语与指定译法、目标语言选择，以及缩放导出。译图保留图像布局，并根据 OCR 结果估算对齐和字号。同字号组共用字号。复杂背景、装饰字体和低清晰度图片可能影响识别与回填效果。

## Windows 便携版

1. 下载 [Windows 64 位 EXE](https://github.com/vcstock/tuyi/releases/latest/download/TuYi-Windows-x64.exe)，复制到任意有权限的文件夹后运行。
2. 打开「设置」，选择翻译服务，输入账号或 API Key；如有需要可配置 HTTP、HTTPS、SOCKS5 或 SOCKS5H 代理。
3. 使用 Ctrl+V 或「选择图片」导入。需要指定译法时，填写「术语与翻译要求」后点击「开始翻译」。
4. 选择格式和缩放后保存。JPG 默认画质为 92%，译图下方显示当前配置下的输出尺寸和文件大小。

设置使用 Windows 当前用户加密保存在 `%LOCALAPPDATA%\TuYi\settings.dat`。ChatGPT 登录使用随应用打包的官方 Codex CLI。使用豆包、Kimi、DeepSeek 或 Gemini 的网页登录时，可在弹窗查看和复制完整提示词。点击「打开官网登录」，在网页发送提示词后，把 AI 回复贴回应用并点击「生成译图」。

通用模型可在「设置 → 翻译服务」选择「自定义模型（兼容 API）」。填写 OpenAI 兼容的 API 地址（例如 `https://example.com/v1`）和模型 ID，服务要求鉴权时再填写 API Key。

## Docker 部署

需要 Docker Engine 或 Docker Desktop，以及 Docker Compose 2.24.0 或更高版本。在仓库目录运行以下命令。

```bash
docker compose up -d --build
```

然后打开 [http://127.0.0.1:8080](http://127.0.0.1:8080)。可以用以下命令查看状态或停止服务。

```bash
docker compose ps
docker compose logs -f tuyi
docker compose down
```

默认只在本机监听。需要跨设备访问时，可在部署主机前配置带 HTTPS 和访问控制的反向代理。容器监听 8080。若反向代理运行在另一台主机，复制 `.env.example` 为 `.env` 后按网络情况设置 `TUYI_BIND`，并用防火墙限制访问来源。HTTPS 也让浏览器可以在线使用剪贴板功能。

### 翻译服务

| 服务 | 可选服务器环境变量 |
| --- | --- |
| DeepSeek | `DEEPSEEK_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| 豆包 / 火山方舟 | `ARK_API_KEY`，另在页面填写模型或接入点 |
| Kimi | `MOONSHOT_API_KEY` |
| Gemini | `GEMINI_API_KEY` |

在「翻译服务设置」里填写 API Key，勾选「记住此设备」可按服务保存在当前浏览器，刷新和切换服务后仍可使用。「清除已保存的 Key」清除当前服务保存的值。服务端环境变量也可作为站点管理员单独设置的默认 Key。能访问网页的用户可使用服务器配置的额度，所以应先配置访问控制。使用代理时，在 `.env` 中设置 `HTTP_PROXY`、`HTTPS_PROXY` 或 `ALL_PROXY` 后重建容器。

网页版也能切换到豆包、Kimi、DeepSeek 或 Gemini 的「网页登录」模式，并提供生成提示词与回填译文的界面。网页版的 OpenAI 自动翻译使用 API Key。ChatGPT 账号直连模式由 Windows 版提供。

### 图片处理与隐私

- 网页版将图片交给部署服务器做 OCR，自动翻译时把识别出的文本和术语说明交给所选供应商。自填 Key 随翻译请求交给后端转发，应用不会在服务器上持久保存它。「记住此设备」使用浏览器本地存储，Key 没有额外加密。联网使用时请访问受信任的 HTTPS 实例，共用设备上请选择临时使用。
- 支持 PNG、JPG、WebP、AVIF、TIFF、BMP、GIF、SVG、SVGZ 等格式。SVG 和 SVGZ 导出内嵌位图。部分浏览器无法预览 TIFF 或 SVGZ，仍可下载。动图和多页图片按首帧处理。
- 上传请求限制为 20 MB，图片和缩放后的输出限制为 3000 万像素。

## 从源码构建 Windows 版

安装 Windows x64 的 Python 3.11（含 `py`）和 Node.js（含 npm）。在 PowerShell 中运行以下命令。

```powershell
.\scripts\build-windows.ps1
```

输出在 `dist\TuYi.exe`。有支持 DirectML 的显卡时，可增加 `-ExpectGpu`，在打包后验证 GPU 和 CPU 识别。构建脚本下载官方 Codex CLI，并使用 PyInstaller 打包。

项目复用 RapidOCR、ONNX Runtime、Pillow 和 resvg。各组件的授权以其发布包为准。
