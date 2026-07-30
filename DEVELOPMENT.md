# LightNovelSelector 开发说明

本文档面向维护者。普通用户只需要下载 `LightNovelSelector-v2.0.2-win-x64-setup.exe`。

## 技术栈

- Python 3.10+：识别、解析、分类计划、文件移动、报告和撤销。
- WinUI 3 / Windows App SDK 2.3：唯一桌面界面。
- .NET 10：WinUI 应用和 C# 测试。
- PyInstaller：把 Python Sidecar 构建为独立 EXE。
- Inno Setup 6+：把 WinUI 运行文件封装为单个安装 EXE。
- defusedxml：安全读取 EPUB XML。
- pytest、ruff、mypy、bandit、vulture、pip-audit、MSTest：自动验证。

## 环境准备

```powershell
winget install Python.Python.3.12
winget install Microsoft.DotNet.SDK.10
winget install JRSoftware.InnoSetup
```

构建脚本优先使用 `.venv-build\Scripts\python.exe`。不存在时会从 `py -3` 或 `python` 创建该环境。

```powershell
py -3 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-dev.txt
```

运行时依赖固定在 `requirements-runtime.txt`；开发、测试和打包依赖固定在 `requirements-dev.txt`。

## 架构边界

### Python 核心

- `classification.py`：分类计划、完整哈希重复检测、线性恢复日志、报告和撤销。
- `parsing.py`：文件名清洗、卷号与系列名解析。
- `files.py`：文件扫描、内容提示、封面和网络字节读取。
- `metadata.py`：本地/在线系列解析与缓存。
- `storage.py`：设置、缓存、原子 JSON 和持久化 JSON Lines。
- `application.py`：线程安全应用状态、异步任务和快照。
- `sidecar.py`：JSON Lines 请求分发。
- `cli.py`：自动化命令行；不再启动桌面界面。

### WinUI 原生界面

- `Views/MainWindow.*`：标题栏、窗口尺寸、主题与窗口材质。
- `Views/MainPage.*`：按状态、筛选、详情、报告、设置、通知和连接职责拆分。
- `Services/PythonSidecarClient.cs`：进程生命周期、请求关联、超时与安全重连。
- `ViewModels/`：连接状态、筛选等可独立测试的纯逻辑。
- `Appearance/` 与 `Styles/`：主题、Acrylic/Mica 回退和语义设计令牌。
- `Helpers/Motion.cs`：按压、页面 reveal、Toast 与减少动态效果。

Sidecar 协议见 [WinUI 架构说明](docs/WINUI_ARCHITECTURE.md)。WinUI 不复制分类规则；Python 不操作窗口控件。

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
.\.venv-build\Scripts\python.exe -m pip_audit -r requirements-dev.txt --strict

dotnet restore native\LightNovelSelector.WinUI.Tests\LightNovelSelector.WinUI.Tests.csproj --locked-mode
dotnet test native\LightNovelSelector.WinUI.Tests\LightNovelSelector.WinUI.Tests.csproj -c Release --no-restore
dotnet build native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj -c Debug -p:Platform=x64 -p:WindowsPackageType=None
dotnet build native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj -c Release -p:Platform=x64 -p:WindowsPackageType=None

git diff --check
```

测试数量会随回归覆盖增长，不在文档中固定；以命令输出和 GitHub Actions 为准。

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

`build_exe.bat` 指向相同入口。实际实现位于 `scripts\windows\build_winui.ps1`，共九步：

1. 安装固定版本的开发依赖。
2. 生成原生图标。
3. 生成 `LightNovelSelector.Sidecar.exe`。
4. 使用独立 Python 工具验证 `ping` / `shutdown` 协议。
5. 执行 Python 测试、类型检查、静态安全扫描和依赖漏洞审计。
6. 执行 C# 测试。
7. 发布自包含 WinUI 到 `build\winui-package` 暂存区，剔除调试产物并收集第三方许可证全文。
8. 执行启动和外观两轮冒烟。
9. 使用 Inno Setup 编译安装器，成功后原子式替换 `dist\winui`。

最终只保留：

```text
dist\winui\LightNovelSelector-v<版本>-win-x64-setup.exe
```

安装器会在安装前显示根目录中的 MIT `LICENSE`，并把项目许可证、`THIRD_PARTY_NOTICES.md` 以及 Python、PyInstaller、defusedxml、.NET、Windows App SDK、WebView2 和 Inno Setup 的原始许可文本保留在应用安装目录。

可选参数：

```powershell
.\build_winui.bat -SkipDependencyInstall
.\build_winui.bat -SkipTests
.\build_winui.bat -KeepStaging
```

默认不保留发布暂存区。`-KeepStaging` 仅用于检查内部 WinUI 运行文件；正式暂存区不应包含 `.pdb` 或 `*.runtimeconfig.dev.json`。

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
