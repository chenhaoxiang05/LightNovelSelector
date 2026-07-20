# LightNovelSelector 开发说明

本文档面向维护者。普通用户只需要阅读 `README.md` 并使用发布 ZIP 中的 `LightNovelSelector.WinUI.exe`。

## 技术栈

推荐桌面界面：

- C#、.NET 10、WinUI 3、Windows App SDK 2.3
- XAML、Windows Composition、Desktop Acrylic、Mica
- Python 3.10+ Sidecar
- 标准输入输出上的 JSON Lines 通信

兼容界面：

- Python 3.10+
- pywebview 6.2.1、Windows Edge WebView2
- 原生 HTML、CSS、JavaScript

测试与打包：

- pytest、ruff、vulture
- PyInstaller 6.21
- Pillow 12.3，用于确定性生成原生应用图标
- `dotnet publish` 自包含发布

WinUI 运行和打包不依赖 Node、Electron、React、Qt 或本地 Web 服务器。

## 环境准备

Windows 10 1809 或更高版本：

```powershell
winget install Python.Python.3.13
winget install Microsoft.DotNet.SDK.10
```

创建 Python 开发环境：

```powershell
py -3 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-dev.txt
```

NuGet 依赖由项目文件固定并通过 `dotnet restore` 自动还原。开发者模式可改善未打包应用调试体验，但最终便携包不要求用户开启开发者模式。

## 架构

### Python 核心

- `lightnovel_classifier.py`：保留旧启动方式和旧导入路径。
- `lightnovel_selector/cli.py`：参数解析和命令行工作流。
- `models.py`：不可变数据模型。
- `parsing.py`：标题清洗、卷号识别、系列名提取。
- `files.py`：电子书提示、封面、完整内容哈希和重复检测。
- `metadata.py`：Bangumi、AniList、Jikan 查询与缓存。
- `classification.py`：预览计划、手动修正、移动、报告和撤销。
- `storage.py`：设置、元数据缓存和原子 JSON 写入。
- `application.py`：线程安全的应用服务、任务、进度、日志和 UI 序列化。

### Sidecar 协议

- `lightnovel_selector/sidecar.py`：请求分派、结构化错误和生命周期管理。
- `lightnovel_sidecar.py`：PyInstaller 的最小入口。
- 每行只包含一个 UTF-8 JSON 对象。
- 每个请求带整数 `id`，响应使用同一 `id` 关联并发调用。
- 标准输出只传协议；诊断只写标准错误。
- `ping` 返回协议版本，C# 启动阶段会拒绝不兼容版本。
- `shutdown` 负责优雅退出，父进程退出时仍会终止整个子进程树。

完整边界见 [WinUI 架构说明](docs/WINUI_ARCHITECTURE.md)。

### WinUI 原生界面

- `App.xaml`：全局资源与转换器。
- `Views/MainWindow.xaml`：透明窗口根节点、原生标题栏和页面宿主。
- `Views/MainWindow.xaml.cs`：窗口尺寸、关闭保护和外观控制器入口。
- `Appearance/WindowAppearanceController.cs`：Desktop Acrylic、Mica、实色切换，标题栏同步，以及系统透明和高对比度回退。
- `Appearance/AppearancePreferences.cs`：主题、材质和动态偏好的共享容错存储。
- `Views/MainPage.xaml`：导航、工作台、活动报告、设置、Toast 和对话框。
- `Views/MainPage.xaml.cs`：界面状态映射、轮询、拖放、确认和用户操作。
- `Views/MainPage.Appearance.cs`、`MainPage.Notifications.cs`、`MainPage.Workflow.cs`：外观设置、通知和安全流程视觉状态。
- `Services/PythonSidecarClient.cs`：进程发现、请求关联、超时和错误传播。
- `Helpers/Motion.cs`：Composition 动效和减少动态效果策略。
- `Styles/DesignTokens.xaml`：浅色、深色、高对比度语义令牌。
- `Models/` 与 `Converters/`：协议模型和纯视觉转换。

文件移动规则只存在于 Python 核心。C# 不直接执行移动、删除、重命名或报告写入。

## 本地运行

一键启动 WinUI 调试版：

```powershell
.\run_winui.bat
```

直接使用 .NET CLI：

```powershell
$env:LN_SELECTOR_PYTHON=(Resolve-Path .\.venv-build\Scripts\python.exe)
dotnet run --project .\native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj `
  -c Debug -p:Platform=x64 -p:WindowsPackageType=None
```

WinUI 自动启动并关闭的冒烟测试：

```powershell
dotnet run --project .\native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj `
  -c Debug -p:Platform=x64 -p:WindowsPackageType=None -- --smoke-test
```

兼容界面仍可运行：

```powershell
.\run.bat
```

## 设计与动效约束

- 专业工具中的高频操作保持即时，不为键盘操作增加动效。
- 指针按压缩放为 `0.975`，按下 100ms、释放 160ms。
- 工作区进入使用 8px、220ms 强 ease-out，卡片间隔 24ms。
- 页面切换使用 4px、160ms reveal，不重复播放整组卡片动画。
- Toast 进入 180 至 220ms，退出 140ms，并沿同一方向进出。
- 只动画 Composition 的 `Opacity`、`Scale` 和 `Translation`。
- 不从 `scale(0)` 开始，不使用慢启动的 ease-in。
- 减少动态效果时取消位移和缩放，只保留 90ms 透明度反馈或控件原生颜色变化。
- 统计数字直接更新，不在后台轮询时反复缩放。
- 状态不得只靠颜色表达，图标、文字和 AutomationProperties 必须同时可用。
- 控件优先使用 WinUI 原生实现，不手绘常见系统图标。

## 开发验证

Python 检查：

```powershell
.\.venv-build\Scripts\python.exe -m py_compile `
  lightnovel_classifier.py lightnovel_sidecar.py `
  lightnovel_selector\*.py tests\*.py tools\generate_native_assets.py
.\.venv-build\Scripts\python.exe -m pytest -q
.\.venv-build\Scripts\python.exe -m ruff check .
.\.venv-build\Scripts\python.exe -m vulture `
  lightnovel_selector lightnovel_classifier.py lightnovel_sidecar.py tests `
  --min-confidence 80
```

WinUI 检查：

```powershell
dotnet build .\native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj `
  -c Debug -p:Platform=x64 -p:WindowsPackageType=None
dotnet build .\native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj `
  -c Release -p:Platform=x64 -p:WindowsPackageType=None
```

深色启动与外观矩阵回归：

```powershell
$env:LN_SELECTOR_WINUI_TEST_THEME = "dark"
$env:LN_SELECTOR_WINUI_TEST_MATERIAL = "acrylic"
$env:LN_SELECTOR_WINUI_APPEARANCE_SMOKE_TEST = "1"
dotnet run --project .\native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj `
  -c Debug -p:Platform=x64 -p:WindowsPackageType=None
```

该测试会轮换浅色、深色、跟随系统与 Acrylic、Mica、实色组合，并切换工作台、活动页和设置页。测试变量只影响当前进程，不写入用户外观偏好。

仓库检查：

```powershell
node --check .\lightnovel_selector\web\app.js
git diff --check
```

当前 Python 测试共 45 项，覆盖解析、重复检测、规则、设置容错、扫描、手动修正、执行、部分失败报告、撤销、并发任务、封面限制和 Sidecar 协议。

外观偏好优先使用 Windows `ApplicationData.LocalSettings`，并同步写入 `%LOCALAPPDATA%\LightNovelSelector\appearance.json`。后备文件不可读或损坏时按默认值启动，并在下一次保存时自动重建。

## 生成原生图标

图标由脚本按固定色值和几何规则生成，避免模板占位图和不同机器上的手工差异：

```powershell
.\.venv-build\Scripts\python.exe .\tools\generate_native_assets.py
```

生成内容包括多尺寸 PNG、未铺底任务栏资源、启动图和 `AppIcon.ico`。生成后需检查 24px 与 300px 两种尺寸，并重新构建确认 EXE 文件图标已嵌入。

## 打包 WinUI 便携版

运行：

```powershell
.\build_winui.bat
```

脚本依次执行：

1. 安装固定版本的 Python 构建依赖。
2. 生成原生应用图标。
3. 使用 PyInstaller 生成单文件 Python Sidecar。
4. 通过真实 `ping` 和 `shutdown` 请求验证协议。
5. 自包含发布 Windows x64 WinUI 应用。
6. 执行深色 Acrylic 启动、主题/材质/页面矩阵回归，再生成 ZIP。

输出示例：

```text
dist\winui\LightNovelSelector-v2.0.0-win-x64-构建时间\
dist\winui\LightNovelSelector-v2.0.0-win-x64-构建时间.zip
```

自包含目录约 231 MiB，压缩包约 95 MiB。体积主要来自 .NET、Windows App SDK 和 Python 运行时，换来下载者无需额外安装环境。`build`、`dist`、虚拟环境和 PyInstaller spec 均被 `.gitignore` 排除。

## 兼容界面打包

`build_exe.bat` 继续生成 pywebview 单文件兼容版：

```powershell
.\build_exe.bat
```

该产物较小，但目标机器需要 WebView2 Runtime。它用于兼容和回退，不是本分支推荐的原生体验。

## Git 工作流

原生界面在独立开发分支维护，不直接提交到稳定分支。提交前应确认没有加入构建产物和用户数据：

```powershell
git status --short
git diff --check
git add README.md DEVELOPMENT.md UPDATE_NOTES.md docs native `
  lightnovel_selector lightnovel_sidecar.py run_winui.bat build_winui.bat scripts `
  requirements-dev.txt tools tests
git commit -m "..."
git push origin <当前开发分支>
```

发布版本时再由稳定分支创建 tag 和 Release，不把实验构建目录提交到仓库。

## 文档约定

- `README.md` 面向使用者。
- `UPDATE_NOTES.md` 面向版本更新与评审。
- `DEVELOPMENT.md` 面向维护者。
- `docs/WINUI_ARCHITECTURE.md` 记录跨进程协议和打包边界。
- 公开文档统一使用中文，示例路径不得包含真实用户隐私数据。
