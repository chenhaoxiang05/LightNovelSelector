<div align="center">
  <img src="native/LightNovelSelector.WinUI/Assets/StoreLogo.png" width="96" height="96" alt="LightNovelSelector 图标">
  <h1>LightNovelSelector</h1>
  <p><strong>在移动文件之前，把轻小说分类结果完整地交给你确认。</strong></p>
  <p>面向 Windows 的本地轻小说识别、预览、整理与安全撤销工具。</p>

  <p>
    <a href="https://github.com/chenhaoxiang05/LightNovelSelector/actions/workflows/windows-ci.yml"><img alt="Windows 持续集成" src="https://github.com/chenhaoxiang05/LightNovelSelector/actions/workflows/windows-ci.yml/badge.svg"></a>
    <a href="https://github.com/chenhaoxiang05/LightNovelSelector/actions/workflows/codeql.yml"><img alt="CodeQL 安全分析" src="https://github.com/chenhaoxiang05/LightNovelSelector/actions/workflows/codeql.yml/badge.svg"></a>
    <a href="https://github.com/chenhaoxiang05/LightNovelSelector/releases/latest"><img alt="最新版本" src="https://img.shields.io/github/v/release/chenhaoxiang05/LightNovelSelector?display_name=tag"></a>
    <img alt="Windows 10 和 11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows11&logoColor=white">
    <img alt="WinUI 3" src="https://img.shields.io/badge/UI-WinUI%203-005FB8">
    <img alt="Python 3.10 或更高版本" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
    <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/License-MIT-2EA44F"></a>
  </p>

  <p>
    <a href="#快速开始"><strong>快速开始</strong></a> ·
    <a href="https://github.com/chenhaoxiang05/LightNovelSelector/releases">下载发布版</a> ·
    <a href="CHANGELOG.md">更新记录</a> ·
    <a href="docs/WINUI_ARCHITECTURE.md">架构说明</a> ·
    <a href="docs/RELEASE_TRUST.md">下载验证</a> ·
    <a href="CONTRIBUTING.md">参与贡献</a> ·
    <a href="https://github.com/chenhaoxiang05/LightNovelSelector/issues">问题反馈</a>
  </p>
</div>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/interface-winui-dark.png">
  <img src="docs/interface-winui-light.png" alt="LightNovelSelector WinUI 3 整理工作台">
</picture>

> [!TIP]
> 最新稳定版是 **WinUI 3 原生版 `v2.0.2`**。可直接下载 [Windows x64 安装器](https://github.com/chenhaoxiang05/LightNovelSelector/releases/download/v2.0.2/LightNovelSelector-v2.0.2-win-x64-setup.exe)，不需要另装 Python、.NET 或 Windows App SDK。

## 为什么使用它

- **先预览，再整理**：扫描阶段只读取文件并生成分类计划，确认前不会移动原文件。
- **识别结果可解释**：统一显示书名、系列、作者、卷号、语言、标签、校准后的置信度，以及本次判断采用的具体证据。
- **修正会被记住**：明确保存的手动修正会在本机形成系列别名，后续精确命中时优先复用，仍可再次手动覆盖。
- **同系列快速校正**：单条修正默认安全，也可在二次确认后把当前系列的同组条目一次修正。
- **批量操作仍可控**：支持搜索、系列筛选、状态筛选、重复标记和错误隔离。
- **文件安全优先**：完整 SHA-256 指纹确认重复内容，目标冲突不会覆盖现有文件。
- **失败也能恢复**：每次移动前都会把恢复意图刷盘，批处理中断后可重建报告并撤销已完成项。
- **异常输入有明确边界**：损坏 EPUB、极端 Unicode 文件名、畸形本地协议消息和核心进程退出都进入可复现的自动测试。
- **多批次可追溯**：活动页保留最近分类历史，可查看、导出或恢复指定批次，而不只限于“撤销上次”。
- **大书库再次扫描更快**：未变化文件会复用经过强文件状态校验的完整哈希与本地识别结果。
- **第一次就能安全上手**：首次启动用一次简短提示说明“先预览、再整理”，之后不会反复打扰，也可随时重新打开。
- **工作区随窗口调整**：宽屏同时展示详情，紧凑窗口使用可收起的详情侧栏，低高度下仍可滚动到筛选、结果和确认操作。
- **键盘与辅助技术友好**：主要页面、筛选、详情、报告和设置提供稳定焦点顺序、快捷键与屏幕阅读器名称。
- **元数据来源可扩展**：Bangumi、AniList 和 Jikan 使用同一公开接口，社区可以增加新书库而无需修改分类核心。
- **本地优先**：小说文件、哈希和报告保留在本机；联网识别可随时关闭。

## 快速开始

### 下载发布版

从 [`v2.0.2` 发布页](https://github.com/chenhaoxiang05/LightNovelSelector/releases/tag/v2.0.2) 下载：

```text
LightNovelSelector-v2.0.2-win-x64-setup.exe
```

安装器按当前 Windows 用户安装，不要求管理员权限，并包含 .NET、Windows App SDK 与 Python Sidecar。`v2.0.2` 暂未进行商业代码签名，请只从本仓库 Release 下载并核对发布页提供的 SHA-256。

下载后可在 PowerShell 中计算校验值，并与 Release 页面逐字比对：

```powershell
Get-FileHash .\LightNovelSelector-v2.0.2-win-x64-setup.exe -Algorithm SHA256
```

新版发布流水线会同时提供 `SHA256SUMS.txt`、SPDX SBOM、构建信息和 GitHub 构建来源证明；代码签名状态会如实写入构建信息。完整验证方法见 [发布可信度与下载验证](docs/RELEASE_TRUST.md)。

### 从源码运行 WinUI 3 版本

开发环境需要 Windows 10 1809 或更高版本、Python 3.10+ 与 .NET 10 SDK：

```powershell
git clone https://github.com/chenhaoxiang05/LightNovelSelector.git
cd LightNovelSelector
.\run_winui.bat
```

首次启动会自动准备 Python 环境。`run.bat` 与 `run_winui.bat` 均进入同一个 WinUI 3 界面。

## 三步完成整理

1. **选择目录**：选择存放待整理小说的目录，或拖入一个目录及同目录中的一批文件。
2. **扫描并预览**：检查系列、置信度、目标路径、重复项和异常项，必要时比较候选并单条或同系列批量修正。
3. **确认整理**：核对完整执行范围后移动文件；随后可在“活动与报告”中选择批次、查看条目、导出报告或撤销。

常用快捷键：

| 快捷键 | 操作 |
| --- | --- |
| `Ctrl+1` / `Ctrl+2` / `Ctrl+3` | 切换到整理工作台、活动与报告、设置 |
| `Ctrl+O` | 选择目录 |
| `Ctrl+F` | 切换到工作台并聚焦结果搜索 |
| `F5` | 在工作台扫描并预览；在活动页刷新历史 |
| `Ctrl+Enter` | 打开整理确认对话框 |
| `Ctrl+S` | 在设置页保存变更 |
| `F6` / `Shift+F6` | 向前或向后切换当前页面的主要区域 |

所有主要操作都可以用 `Tab` / `Shift+Tab` 到达。系统关闭动画或应用启用“减少动态效果”时，非必要位移与缩放反馈会自动取消。

<details>
<summary><strong>查看深色与浅色界面</strong></summary>

| 跟随 Windows 浅色 | 跟随 Windows 深色 |
| :---: | :---: |
| ![浅色界面](docs/interface-winui-light.png) | ![深色界面](docs/interface-winui-dark.png) |

</details>

## 原生桌面架构

桌面界面采用 **WinUI 3 + Windows App SDK**，分类与文件安全逻辑由 Python 负责。两端通过本机标准输入输出上的 JSON Lines 协议通信，不启动本地网页服务器。

```mermaid
flowchart LR
    UI["WinUI 3 原生界面"] -->|"JSON Lines"| Sidecar["Python Sidecar"]
    Sidecar --> Plan["识别与分类计划"]
    Plan --> Files["文件校验与移动"]
    Files --> Report["报告与安全撤销"]
    Plan -. "可选标题查询" .-> Metadata["在线元数据"]
```

旧 WebView 界面已经停用并从当前源码移除，最后一个完整版本保存在 Git 标签 [`legacy-webview-final`](https://github.com/chenhaoxiang05/LightNovelSelector/tree/legacy-webview-final)。详细职责边界见 [WinUI 架构说明](docs/WINUI_ARCHITECTURE.md) 和 [项目结构说明](docs/PROJECT_STRUCTURE.md)。

## 文件安全

LightNovelSelector 将“能恢复”视为批量整理的基本要求：

- 扫描只生成预览，不移动文件。
- 搜索与筛选只改变当前显示，不会悄悄缩小执行范围。
- 设置或目录变化后，旧预览自动失效。
- 重复检测比较完整文件内容，不依赖容易碰撞的头尾片段。
- 增量缓存只有在文件 ID、大小、最后写入时间和可靠变更令牌全部一致时才复用；不支持可靠令牌的文件系统自动实时重算。
- 执行前再次验证源文件、目标路径和报告写入能力。
- 扫描后源文件发生大小或修改时间变化时拒绝执行，并提示重新扫描。
- 从查找目录项开始即可随时取消；单次最多检查 200,000 个目录项、处理 10,000 个受支持文件，超出时会提示缩小范围。
- 主程序只保留一个活动实例，重复启动会唤回已有窗口，避免并发操作同一目录。
- 目标存在同名文件时不会覆盖，重复项与错误项默认跳过。
- 批量整理使用线性恢复日志，部分移动成功、进程异常退出或后续步骤失败时仍可重建已完成记录。
- 恢复时会同时核对原计划、源和目标位置及文件状态；状态有歧义时停止并要求人工检查。
- 撤销会把每项严格判定为“待撤销”或“已恢复”；源和目标同时存在、同时缺失或文件状态不匹配时整批停止。
- 分类后的目标文件若已被编辑、替换为目录或符号链接，撤销会停止并保留现状。
- 撤销前会校验报告版本、应用标识、所在目录和全部文件路径，拒绝执行超出所选目录的记录。
- 历史列表只接受核心生成的执行编号；打开、导出和撤销都拒绝任意路径、链接替换与越界报告。
- 标题和目标目录会过滤不成对 Unicode 代理字符、方向覆盖符及不可见控制符，避免报告编码失败和界面文字方向伪装。

最近一次分类报告保持原有兼容位置：

```text
所选目录\classification_report.json
```

通过校验的新报告还会原子归档到：

```text
所选目录\.lightnovel-selector\history\
```

活动页最多显示最近 100 个有效批次；损坏、链接或越界报告会被忽略并提示。筛选历史只影响查看，撤销前仍会按所选批次重新验证完整文件状态。旧版 `classification_report.json` 仍可查看和撤销，但不会自动复制进历史目录。

增量扫描缓存保存在 `%LOCALAPPDATA%\LightNovelSelector\scan_cache.json`。它只包含派生书籍身份、查询、快速签名和完整 SHA-256，不保存正文片段，也不会联网发送。缓存损坏、被锁定或被手动删除都不会影响小说文件和分类报告，只会让下一次扫描重新计算。

项目在 Windows CI 中持续验证 10,000 个合成小说文件的取消、冷缓存扫描、热缓存重扫、内存和缓存复用，并单独验证 10,000 行结果筛选。固定种子的边界测试还会覆盖损坏 EPUB、异常文件名、文件移动各阶段失败和真实 Sidecar 崩溃重连。性能预算用于发现明显退化，不代表所有磁盘都能达到固定耗时；测试方法和本地命令见 [性能基准说明](docs/PERFORMANCE.md)。

人工修正记忆保存在 `%LOCALAPPDATA%\LightNovelSelector\recognition_aliases.json`。它只记录脱离路径的系列别名、用户确认的系列名和更新时间，不保存小说完整路径或正文。文件损坏、不可写或被删除时，当前修正和分类功能仍然有效，只是不再复用此前别名。

整理进行中或异常退出后，同目录可能短暂保留
`classification_report.recovery.jsonl`。它只用于核对尚未汇总的移动记录，成功完成或恢复后会自动删除。请勿修改、移动或单独删除报告与恢复日志；两者都包含绝对路径，也不要公开上传。

## 识别能力

识别顺序综合自定义规则、本地修正记忆、文件名、本地 EPUB 元数据与内容提示，以及可选的 Bangumi、AniList、Jikan 在线条目。三个在线来源通过统一注册表运行，可在设置页逐个启停和调整优先级；单个来源异常会进入独立冷却，后续来源与本地结果继续工作，不会让整批文件反复等待同一超时。设置页同时显示来源健康状态。内部使用统一书籍身份记录书名、系列、作者、卷号、语言和标签；字段没有足够证据时会显示“未识别”，不会为了填满详情而强行猜测。不同来源的原始分数会经过统一的保守标尺，详情区同时展示置信度等级、分类原因和证据；选择候选只填写修正框，不会立即移动文件。

提供器接口、显式注册方式、缓存版本和安全要求见 [元数据提供器开发指南](docs/METADATA_PROVIDERS.md)。应用不会自动扫描或执行来源不明的本地 Python 插件。

在线识别仅向这些服务发送从文件名、用户规则或手动修正得到的标题/系列查询；从 EPUB 或弱文件名小说正文中读取的作者、语言、标签和内容提示始终留在本机，不会加入联网查询。应用不上传小说文件、完整哈希或分类报告；远程 JSON 和封面只允许公开 HTTPS 地址，并设有体积上限，同时拒绝解析到本机或内部网络的域名。关闭联网后仍可使用全部本地整理能力。同系列批量修正默认关闭，只更新完整分类预览，并在提交前再次确认；任一条目无法安全修改时整批保持原状。

支持格式：

```text
TXT  EPUB  PDF  MOBI  AZW  AZW3  FB2  DOC  DOCX  RTF
MD   HTML  CBZ  CBR   ZIP  RAR   7Z
```

EPUB、ZIP 和 CBZ 可读取本地封面与部分内容提示；其他格式仍可通过文件名、自定义规则和可选在线元数据识别。

## 命令行与构建

Python CLI 保留给自动化与排错：

```powershell
py .\lightnovel_classifier.py "D:\你的轻小说目录" --dry-run
py .\lightnovel_classifier.py "D:\你的轻小说目录" --dry-run --no-network --recursive
py .\lightnovel_classifier.py --undo-report "D:\你的轻小说目录\classification_report.json"
```

构建单 EXE 安装器还需要 .NET 8 Runtime（SBOM 工具）与 Inno Setup 6 或更高版本：

```powershell
winget install Microsoft.DotNet.Runtime.8
winget install JRSoftware.InnoSetup
.\build_winui.bat
```

完整开发环境、测试命令和发布流程见 [DEVELOPMENT.md](DEVELOPMENT.md)，发布资产的验证与签名边界见 [发布可信度说明](docs/RELEASE_TRUST.md)，自包含依赖与体积测量见 [安装包体积说明](docs/PACKAGE_SIZE.md)；新增在线书库请同时阅读 [元数据提供器开发指南](docs/METADATA_PROVIDERS.md)。

## 获取帮助

- 使用问题或异常：选择 [Bug 报告](https://github.com/chenhaoxiang05/LightNovelSelector/issues/new?template=bug_report.yml)。
- 功能想法：选择 [功能建议](https://github.com/chenhaoxiang05/LightNovelSelector/issues/new?template=feature_request.yml)。
- 安全问题：不要公开附带真实目录、小说内容或敏感日志，请按 [安全说明](SECURITY.md) 私下报告。
- 参与开发：阅读 [贡献指南](CONTRIBUTING.md) 和 [行为准则](CODE_OF_CONDUCT.md)。

## 开源许可证

LightNovelSelector 采用 [MIT License](LICENSE)。你可以使用、修改、分发、再许可或销售本软件，也欢迎提交改进；分发源码或软件副本时需保留原版权声明和许可证文本。正式安装器同时附带 [第三方组件说明](THIRD_PARTY_NOTICES.md) 及各运行时的原始许可证全文。
