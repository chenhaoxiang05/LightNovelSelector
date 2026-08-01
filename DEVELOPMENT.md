# LightNovelSelector 开发说明

本文档面向维护者。普通用户只需要下载 `LightNovelSelector-v2.0.2-win-x64-setup.exe`。

## 技术栈

- Python 3.10+：识别、解析、分类计划、文件移动、报告和撤销。
- WinUI 3 / Windows App SDK 2.3：唯一桌面界面。
- .NET 10：WinUI 应用和 C# 测试。
- PyInstaller：把 Python Sidecar 构建为独立 EXE。
- Inno Setup 6+：把 WinUI 运行文件封装为单个安装 EXE。
- Microsoft SBOM Tool 4.1.5：生成并验证 SPDX 2.2 软件物料清单。
- Windows SDK SignTool：配置正式证书时执行 Authenticode 签名与时间戳验证。
- defusedxml：安全读取 EPUB XML。
- pytest、ruff、mypy、bandit、vulture、pip-audit、MSTest：自动验证。

## 环境准备

```powershell
winget install Python.Python.3.12
winget install Microsoft.DotNet.Runtime.8
winget install Microsoft.DotNet.SDK.10
winget install JRSoftware.InnoSetup
```

.NET 10 用于应用与测试；固定的 Microsoft SBOM Tool 当前以 .NET 8 为目标，因此构建机还需安装 .NET 8 Runtime。只有进行 Authenticode 签名时才需要包含 SignTool 的 Windows SDK。

构建脚本优先使用 `.venv-build\Scripts\python.exe`。不存在时会从 `py -3` 或 `python` 创建该环境。

```powershell
py -3 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-dev.txt
```

运行时依赖固定在 `requirements-runtime.txt`；开发、测试和打包依赖固定在 `requirements-dev.txt`。

## 架构边界

### Python 核心

- `classification.py`：保持历史公开导入路径的轻量兼容门面。
- `classification_discovery.py` / `classification_planning.py`：文件发现、分类计划生成与人工修正。
- `classification_reporting.py` / `classification_recovery.py`：报告序列化、有界读取与崩溃恢复日志。
- `classification_execution.py` / `classification_undo.py`：文件移动事务与撤销执行。
- `classification_safety.py`：执行、报告和撤销共用的路径与文件状态校验。
- `corrections.py`：人工修正形成的有界本地系列别名与原子持久化。
- `recognition.py`：跨来源置信度校准、等级与可读分类依据。
- `report_history.py`：报告归档、受限历史列表、执行编号解析和撤销状态。
- `parsing.py`：文件名清洗、卷号与系列名解析。
- `files.py`：文件扫描、内容提示、封面和网络字节读取。
- `metadata.py`：提供器协调、错误隔离和按注册表分区的元数据缓存。
- `providers/`：公开提供器接口、注册表和 Bangumi、AniList、Jikan 独立实现。
- `provider_reliability.py`：来源级限流、失败冷却、短期负缓存与健康状态。
- `scan_cache.py`：可靠文件快照、增量扫描和完整哈希缓存。
- `scan_session.py`：一次可取消扫描的缓存生命周期、进度回调与结果，不持有线程或 UI 状态。
- `storage.py`：设置、缓存、原子 JSON 和持久化 JSON Lines。
- `application.py`：线程安全应用状态、后台线程和 Sidecar 快照。
- `sidecar.py`：JSON Lines 请求分发。
- `cli.py`：自动化命令行；不再启动桌面界面。

### WinUI 原生界面

- `Views/MainWindow.*`：标题栏、窗口尺寸、主题与窗口材质。
- `Views/MainPage.*`：按状态、筛选、详情、报告、设置、通知和连接职责拆分。
- `Services/PythonSidecarClient.cs`：进程生命周期、请求关联、超时与安全重连。
- `Security/ReportPathSafety.cs`：限制 WinUI 可打开或导出的本地报告位置。
- `ViewModels/`：连接状态、筛选等可独立测试的纯逻辑。
- `Appearance/` 与 `Styles/`：主题、Acrylic/Mica 回退和语义设计令牌。
- `Helpers/Motion.cs`：按压、页面 reveal、Toast 与减少动态效果。

Sidecar 协议见 [WinUI 架构说明](docs/WINUI_ARCHITECTURE.md)。WinUI 不复制分类规则；Python 不操作窗口控件。
新增在线书库必须遵守 [元数据提供器开发指南](docs/METADATA_PROVIDERS.md)，不得在分类核心中加入特定服务分支。

## 本地运行

```powershell
.\run_winui.bat
```

根目录 `run.bat` 指向同一 WinUI 脚本。源码模式下，WinUI 按以下顺序寻找核心：

1. `LN_SELECTOR_PYTHON` 指定解释器。
2. `.venv-build`。
3. `.venv`。
4. 系统 `py` / `python`。

发布版只使用应用目录中的 `LightNovelSelector.Sidecar.exe`。

## 开发验证

```powershell
.\.venv-build\Scripts\python.exe -m py_compile lightnovel_classifier.py lightnovel_sidecar.py tools\verify_sidecar.py
.\.venv-build\Scripts\python.exe -m pytest -q
.\.venv-build\Scripts\python.exe -m ruff check .
.\.venv-build\Scripts\python.exe -m ruff format --check .
.\.venv-build\Scripts\python.exe -m mypy lightnovel_classifier.py lightnovel_sidecar.py lightnovel_selector tests
.\.venv-build\Scripts\python.exe -m bandit -q -r lightnovel_selector lightnovel_classifier.py lightnovel_sidecar.py
.\.venv-build\Scripts\python.exe -m vulture lightnovel_classifier.py lightnovel_selector tests --min-confidence 80
.\.venv-build\Scripts\python.exe -m pip_audit -r requirements-dev.txt --strict --cache-dir build\pip-audit-cache --progress-spinner off

dotnet restore native\LightNovelSelector.WinUI.Tests\LightNovelSelector.WinUI.Tests.csproj --locked-mode
dotnet test native\LightNovelSelector.WinUI.Tests\LightNovelSelector.WinUI.Tests.csproj -c Release --no-restore
dotnet build native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj -c Debug -p:Platform=x64 -p:WindowsPackageType=None
dotnet build native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj -c Release -p:Platform=x64 -p:WindowsPackageType=None

git diff --check
```

测试数量会随回归覆盖增长，不在文档中固定；以命令输出和 GitHub Actions 为准。

### 大型书库性能基准

性能基准只生成临时合成文件，不读取真实书库，也不访问网络：

```powershell
.\.venv-build\Scripts\python.exe -m tools.benchmark_large_library `
  --files 10000 `
  --budget benchmarks\performance_budget.json `
  --output build\performance\large-library.json `
  --enforce
```

它依次验证快速取消、取消后的完整重扫、热缓存重扫、缓存复用率和峰值工作集。JSON
报告写入被 Git 忽略的 `build\performance`；GitHub Actions 同时把摘要写入任务页面。
预算修改必须附带同一机器上的修改前后报告，不能为了让退化通过而单独放宽阈值。详细方法见
[性能基准说明](docs/PERFORMANCE.md)。

## UI 与动效约束

- 默认跟随 Windows 深浅色，首次材质为 Acrylic；透明效果关闭或高对比度时回退实色。
- 窗口只创建一层 Desktop Acrylic，卡片使用半透明实色，避免重复模糊带来的 GPU 开销。
- 高频列表筛选和键盘操作不增加位移动画；大结果集采用短防抖和单次数据源替换，避免逐行刷新阻塞界面。
- 进入、Toast、页面切换和按压只动画 `Opacity`、`Translation`、`Scale`，单次不超过 220ms。
- 按下 100ms、释放 160ms；Toast 进入 180/220ms、退出 140ms。
- 动画从当前 Composition 状态继续，快速连续通知不会跳回起点。
- “减少动态效果”或系统关闭动画时移除位移和缩放，只保留短透明度反馈。
- 图标按钮必须同时提供 Tooltip 和 `AutomationProperties.Name`。

## 构建单 EXE 安装器

开发版本使用 `主版本.次版本.修订版本-dev.序号`。修改版本时必须同步
`lightnovel_selector/constants.py`、WinUI 项目属性、`app.manifest` 和
`Package.appxmanifest`；正式构建会在打包前自动拒绝不一致的版本元数据。

```powershell
.\build_winui.bat
```

`build_exe.bat` 指向相同入口。实际实现位于 `scripts\windows\build_winui.ps1`，共十一步：

1. 安装固定版本的开发依赖。
2. 还原仓库固定的 SBOM 工具并生成原生图标。
3. 生成 `LightNovelSelector.Sidecar.exe`。
4. 使用独立 Python 工具验证 `ping` / `shutdown` 协议。
5. 执行 Python 测试、类型检查、静态安全扫描和依赖漏洞审计。
6. 执行 C# 测试。
7. 发布自包含 WinUI 到 `build\winui-package` 暂存区，剔除调试产物、拒绝未使用的可选运行组件、检查 210 MiB 体积预算并收集第三方许可证全文。
8. 配置证书时签署并验证项目自有 WinUI、程序集和 Sidecar；未配置时记录未签名状态。
9. 执行启动和外观两轮冒烟。
10. 使用 Inno Setup 编译安装器，并在配置证书时签署最终安装器。
11. 扫描安装器与依赖，生成并验证 SBOM、构建信息和 SHA-256 清单，成功后原子式替换 `dist\winui`。

最终只保留四项可分发资产：

```text
dist\winui\LightNovelSelector-v<版本>-win-x64-setup.exe
dist\winui\LightNovelSelector-v<版本>-win-x64-sbom.spdx.json
dist\winui\LightNovelSelector-v<版本>-win-x64-build-info.json
dist\winui\SHA256SUMS.txt
```

安装器会在安装前显示根目录中的 MIT `LICENSE`，并把项目许可证、`THIRD_PARTY_NOTICES.md` 以及 Python、PyInstaller、defusedxml、.NET、各 Windows App SDK 组件、WebView2 和 Inno Setup 的原始许可文本保留在应用安装目录。

可选参数：

```powershell
.\build_winui.bat -SkipDependencyInstall
.\build_winui.bat -SkipTests
.\build_winui.bat -KeepStaging
.\build_winui.bat -RequireCleanSource
```

默认不保留发布暂存区。`-KeepStaging` 仅用于检查内部 WinUI 运行文件；正式暂存区不应包含 `.pdb` 或 `*.runtimeconfig.dev.json`。`-RequireCleanSource` 用于正式发布，在工作树有任何未提交源码时阻断构建。

构建结束后可以独立复核最终目录：

```powershell
.\.venv-build\Scripts\python.exe .\tools\release_assets.py verify --dist .\dist\winui
```

### Authenticode 签名

没有证书的日常开发构建保持可用，但 `build-info.json` 会明确写入 `authenticode.status = "unsigned"`。取得受信任的代码签名 PFX 后，使用环境变量避免把证书路径和密码写入脚本：

```powershell
$env:WINDOWS_SIGNING_PFX_PATH = "D:\secure\codesign.pfx"
$env:WINDOWS_SIGNING_PFX_PASSWORD = "<密码>"
.\build_winui.bat -RequireSignature
```

构建脚本固定使用 SHA-256 文件摘要、HTTPS RFC 3161 时间戳和 SHA-256 时间戳摘要，并对每个签名执行 `signtool verify /pa /all /tw` 与 `Get-AuthenticodeSignature` 双重检查。`-RequireSignature` 会在证书或 SignTool 缺失时立即失败；可用 `-TimestampUrl` 显式更换时间戳服务。

证书、密码和临时 PFX 不能提交到仓库。GitHub Actions 使用 `WINDOWS_SIGNING_PFX_BASE64` 与 `WINDOWS_SIGNING_PFX_PASSWORD` Secrets；仓库尚无商业证书时，工作流仍生成校验、SBOM 和来源证明，但会如实发布未签名状态。详见 [发布可信度说明](docs/RELEASE_TRUST.md)。

### 标签发布

`.github\workflows\release.yml` 只响应 `v*` 标签，并在构建前强制要求：

- `APP_VERSION` 是不含 `-dev` 的正式版本；
- 标签严格等于 `v<APP_VERSION>`；
- `docs\releases\v<版本>.md` 存在且包含完整中文说明；
- 标签提交已经存在于远端 `main` 历史中；
- 完整测试、安装器冒烟和四项发布资产验证全部成功。

通过后，工作流解析唯一安装器与 SBOM，使用 GitHub OIDC/Sigstore 生成 SLSA 来源证明和 SBOM 证明，再创建或修复同名 GitHub Release。修复已有 Release 时会删除四项可信资产之外的旧附件，并在上传后复核完整资产集合。所有 Actions 均固定到完整提交 SHA，发布 runner 固定为仍提供 Inno Setup 的 `windows-2022`。

## 安装包体积边界

WinUI 项目直接引用所需的 Windows App SDK 组件，不引用会带入 AI、ML、Widgets 和 DWrite 的完整元包。构建脚本会拒绝这些可选运行文件重新出现，并对含 Sidecar 与许可证的完整暂存目录执行 210 MiB 上限。测量基线、排除列表和复核命令见 [Windows 安装包体积与依赖边界](docs/PACKAGE_SIZE.md)。

## 为什么安装器内部有语言目录

Windows App SDK 自包含发布会携带 WinUI 控件的 `.mui` 本地化资源，例如 `zh-CN`、`en-us`、`ja-JP`。它们每个目录都有实际文件，不是空目录。删除这些资源会破坏不同 Windows 语言下的系统控件文本，因此当前选择保留并封装进安装 EXE。

历史上真正的空目录来自构建脚本过早把中间输出写入 `dist`：版本读取或后续构建失败后，已创建目录不会回收。新脚本只写 `build` 暂存区，并在所有验证成功后替换最终输出，因此失败构建不会污染 `dist`。

## 生成目录

以下目录由 Git 忽略，可重新生成：

- `.venv-build/`：构建虚拟环境。
- `.venv/`：可选源码运行环境。
- `build/`：测试缓存、Sidecar 和临时发布文件。
- `dist/`：最终安装器。
- `native/**/bin/`、`native/**/obj/`：.NET 输出。

旧 WebView 最终版本位于标签 `legacy-webview-final`，早期界面实验保留在远端 `ui` 分支。

## Git 工作流

- 在功能分支完成修改、测试、提交和推送。
- 不提交 `build`、`dist`、虚拟环境、安装器或临时截图。
- 发布版本时从审查通过的分支创建标签和 Release。
- 稳定分支不用于保存实验构建产物。
- 正式 Release 从 `main` 创建；旧架构使用 `legacy/*` 分支和不可变标签归档。

GitHub Actions 会在 Windows 上执行 Python 检查、C# 测试和 WinUI 构建；CodeQL 分析 Python 与 C#。GitHub Actions 均固定到完整提交 SHA，NuGet 使用已提交的锁文件。
