# LightNovelSelector 轻小说自动整理工具

LightNovelSelector 是面向 Windows 的本地桌面工具，用来批量识别、预览和整理轻小说文件。程序先生成完整分类计划，只有用户确认后才移动文件；每次整理都会保存报告，并可按报告安全撤销。

![LightNovelSelector 浅色界面](docs/interface-winui-light.png)

## 主要能力

- 从文件名、电子书内容提示、自定义规则和可选在线条目中识别作品系列。
- 批量扫描目录或拖入同一目录中的文件，显示系列、目标位置、来源和置信度。
- 支持搜索、系列筛选、状态筛选、详情查看和手动修正。
- 使用完整文件 SHA-256 指纹检测重复内容，避免仅比较文件名或头尾片段造成误判。
- 执行前再次检查源文件与目标路径；冲突、错误和重复文件会明确标记并安全跳过。
- 移动成功后持续写入 `classification_report.json`，即使后续文件失败也保留已完成记录。
- 支持报告查看、历史条目、撤销上次整理和自定义分类规则。
- 设置保存失败只提示警告，不阻断扫描主流程。
- 默认跟随 Windows 深浅色，提供 Acrylic、Mica、实色与减少动态效果选项。

## 原生架构

桌面界面统一采用 **WinUI 3 + Windows App SDK**。分类、文件解析、网络元数据、报告和撤销逻辑继续由 Python 负责，WinUI 通过本机 JSON Lines Sidecar 协议调用 Python 核心。

```text
WinUI 3 窗口
    │ JSON Lines / stdin + stdout
    ▼
Python Sidecar
    │
    ├─ 文件名与内容解析
    ├─ 系列识别与自定义规则
    ├─ 完整指纹重复检测
    └─ 移动、报告与撤销
```

旧 WebView 界面已经停用并从当前源码移除。最后一个包含旧界面的完整版本保存在 Git 标签 `legacy-webview-final`，不会影响当前 WinUI 代码和安装包。

## 快速开始

### 安装版

从仓库 Release 下载：

```text
LightNovelSelector-v2.0.0-win-x64-setup.exe
```

双击安装器即可。默认安装到当前 Windows 用户目录，不需要管理员权限；安装器会创建开始菜单入口，并提供可选桌面快捷方式。应用本体自带 .NET、Windows App SDK 和 Python Sidecar，下载者不需要另装编程环境。

发布产物目前未进行商业代码签名。请只从本仓库 Release 获取安装器，并核对发布页提供的 SHA-256。

### 从源码启动

开发机需要：

- Windows 10 1809 或更高版本，推荐 Windows 11
- Python 3.10 或更高版本
- .NET 10 SDK

双击 `run_winui.bat`，或在 PowerShell 中运行：

```powershell
.\run_winui.bat
```

`run.bat` 现在也是同一 WinUI 入口，不再启动旧界面。

## 使用流程

1. 点击“选择目录”，或把一个目录/同一目录中的一批小说拖入导入卡片。
2. 点击“扫描并预览”，等待识别完成。
3. 使用搜索和筛选检查分类计划，必要时在详情面板手动修正系列。
4. 点击“确认整理”，再次核对文件数量后执行移动。
5. 在“活动与报告”中查看移动、跳过、重复和错误条目；需要时按报告撤销。

常用快捷键：

| 快捷键 | 操作 |
| --- | --- |
| `Ctrl+O` | 选择目录 |
| `F5` | 扫描并预览 |
| `Ctrl+Enter` | 打开整理确认对话框 |

## 文件安全

- 扫描阶段只读取文件，不移动原文件。
- 筛选只改变当前显示，不会缩小“确认整理”的执行范围。
- 目录或设置变化后，旧预览自动失效。
- 重复检测使用完整内容指纹；同大小且头尾相同、中间不同的文件不会被误判为重复。
- 每个成功移动项立即进入内存报告，部分失败时仍会在 `finally` 阶段落盘。
- 目标位置已有同名文件时不会覆盖，撤销时同样采用安全跳过策略。

分类报告位于所选目录：

```text
所选目录\classification_report.json
```

用户设置和元数据缓存保存在当前 Windows 账户的本地应用数据目录中，不写入安装目录。

## 支持格式

`TXT`、`EPUB`、`PDF`、`MOBI`、`AZW`、`AZW3`、`FB2`、`DOC`、`DOCX`、`RTF`、`MD`、`HTML`、`CBZ`、`CBR`、`ZIP`、`RAR`、`7Z`。

EPUB、ZIP 和 CBZ 可读取本地封面与部分内容提示；其他格式仍可通过文件名、自定义规则和可选在线元数据识别。

## 命令行模式

Python CLI 保留给自动化和排错使用，但不再承载桌面界面：

```powershell
py .\lightnovel_classifier.py "D:\你的轻小说目录" --dry-run
py .\lightnovel_classifier.py "D:\你的轻小说目录" --dry-run --no-network --recursive
py .\lightnovel_classifier.py --undo-report "D:\你的轻小说目录\classification_report.json"
```

## 构建安装器

构建机还需要 Inno Setup 6 或更高版本：

```powershell
winget install JRSoftware.InnoSetup
.\build_winui.bat
```

`build_exe.bat` 是同一构建入口。脚本会在 `build\` 的干净暂存区完成 Python/C# 测试、Sidecar、WinUI 自包含发布、启动/外观冒烟和安装器编译；只有全部成功后才替换最终目录：

```text
dist\winui\LightNovelSelector-v2.0.0-win-x64-setup.exe
```

`dist\winui` 不再生成 ZIP 和时间戳便携目录。WinUI 的语言 `.mui`、原生 DLL 与 Sidecar 会封装在安装器中，下载者不会再面对数百个运行文件。详见 [开发说明](DEVELOPMENT.md)。

## 项目结构

```text
lightnovel_selector/             Python 分类核心与 Sidecar 服务
native/LightNovelSelector.WinUI/ WinUI 3 原生桌面界面
native/LightNovelSelector.WinUI.Tests/ C# 纯逻辑测试
scripts/windows/                 Windows 启动、构建与安装器脚本
tests/                           Python 核心和协议测试
tools/                           图标与 Sidecar 验证工具
docs/                            架构、结构和界面资料
```

更完整的职责边界见 [项目结构说明](docs/PROJECT_STRUCTURE.md) 与 [WinUI 架构说明](docs/WINUI_ARCHITECTURE.md)，本轮变化见 [更新说明](UPDATE_NOTES.md)。
