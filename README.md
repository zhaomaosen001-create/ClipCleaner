# ClipCleaner - 多平台下载

跨平台桌面工具（**macOS / Windows**），支持短视频平台链接解析、批量下载、图文笔记导出。

## 功能

- **真实 API 解析**：内置平台解析 + douyin.wtf 混合 API + 自定义 API 回退
- **批量下载**：多行粘贴或导入 txt，队列并发下载（可配置并发数）
- **图文导出**：小红书图文笔记下载全部无水印图片，并导出文案 `caption.txt`
- **小红书视频**：内置解析提取 xhscdn 源视频流，自动下载无平台水印的 mp4
- **腾讯妙思抓取**：Playwright 无头浏览器自动拦截视频地址（无需第三方 API）
- **智能输入识别**：自动区分平台分享链接、图文/视频与直链
- **自动图标**：首次启动或运行脚本自动生成应用图标
- **系统托盘**：关闭窗口最小化到托盘

## 环境要求

- Python 3.10+
- macOS 12+ 或 Windows 10/11

## 安装与运行（macOS）

```bash
cd duanship
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

python scripts/generate_icon.py   # 可选
python main.py
```

## 使用说明

1. 在输入框粘贴一条或多条分享链接（每行一条），或点击「导入 txt」
2. 点击「加入队列」仅入队，或点击「开始下载」自动入队并开始处理
3. 任务列表显示类型（视频/图文）、状态与操作按钮
4. 失败任务可点击「重试失败」

## 图文导出目录结构

```
{输出目录}/xiaohongshu/{作者}_{标题}_{note_id}/
  001.jpg
  002.jpg
  ...
  caption.txt
```

## 解析 API 说明

默认 **auto** 模式按顺序尝试：

1. **内置解析**：抖音、B站、快手、小红书（视频+图文）、视频号
2. **douyin.wtf API**
3. **自定义 API**：支持 `{url}` 占位符

## 配置路径

| 系统 | 配置目录 |
|------|----------|
| macOS | `~/Library/Application Support/ClipCleaner/` |
| Windows | `%APPDATA%\ClipCleaner\` |
| Linux | `~/.config/ClipCleaner/` |

## 打包分发（给其他电脑使用）

### 已生成的 macOS 安装包

在本机执行 `./scripts/build_mac.sh` 后，`dist/` 目录下会有：

| 文件 | 大小约 | 给其他 Mac 用户 |
|------|--------|----------------|
| **ClipCleaner-macOS.dmg** | ~90MB | **推荐**：双击打开，拖入「应用程序」 |
| ClipCleaner-macOS.zip | ~80MB | 解压后双击 `ClipCleaner.app` |

首次打开若提示「无法验证开发者」，请 **右键应用 → 打开 → 确认打开**。

### Windows 安装包（需在 Windows 电脑上打包）

当前 Mac 无法直接生成 Windows 程序，请在 **Windows 10/11** 上执行：

```bat
scripts\build_windows.bat
```

生成：

| 文件 | 给其他 Windows 用户 |
|------|---------------------|
| **ClipCleaner-Windows.zip** | **推荐**：解压后双击 `ClipCleaner.exe` |
| ClipCleaner.exe | 单文件，可直接复制运行 |

若 SmartScreen 拦截，点击「更多信息」→「仍要运行」。

### 使用 GitHub 自动打双平台包（可选）

若项目已推送到 GitHub，可在 Actions 中运行 **Build Release** 工作流，同时产出 macOS 与 Windows 两个安装包。

## 项目结构

```
duanship/
├── main.py
├── clipcleaner/
│   ├── core/           # MediaInfo、批量队列
│   ├── download/     # 图文下载导出
│   ├── platform_parsers.py
│   ├── api_resolver.py
│   ├── downloader.py
│   └── gui/
└── scripts/
```

## 许可证

本项目代码仅供学习交流。第三方 API 遵循各自许可协议。
