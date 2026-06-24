# LightNovelSelector 轻小说自动整理工具

LightNovelSelector 是一个 Windows 桌面工具，用来批量整理轻小说文件。选择一个“大文件夹”后，软件会扫描其中的小说文件，识别作品系列名，预览分类结果，并在你确认后把文件移动到对应系列文件夹。

当前版本：`v1.3.0`

## 适合解决的问题

- 下载的轻小说文件名来源混乱，想按作品系列归档。
- 文件很多，不想手动一个个建文件夹、移动、改名。
- 想先预览分类结果，再决定是否真正移动文件。
- 想保留撤销能力，避免误操作后无法恢复。
- 想看到识别依据、置信度、简介、封面和分类状态。

## 核心能力

- 自动识别系列名：优先查询 Bangumi，必要时结合 AniList/Jikan 和本地文件名规则。
- 本地规则兜底：即使关闭联网识别，也会根据文件名提取系列名。
- 批量扫描和预览：扫描阶段不移动原文件，只生成分类计划。
- 安全执行分类：确认后才移动文件到 `大文件夹\系列名\文件名`。
- 完整文件重复检测：使用文件大小和完整 SHA-256 内容哈希识别重复文件。
- 重复文件保护：重复项默认标记为 `duplicate` 并跳过，不会误移动。
- 分类报告：每次执行后生成 `classification_report.json`。
- 撤销上次分类：可根据报告恢复已经移动的文件。
- 单卷详情：选中条目后显示当前卷或系列的简介、封面、条目链接。
- 本地封面优先：EPUB/ZIP/CBZ 内有封面时优先读取本地封面。
- 自动重命名：可尝试按文件名、电子书内容和单卷信息生成更清楚的新文件名。
- 自定义分类规则：可用 `匹配模式 => 系列名` 覆盖自动识别结果。
- 持久缓存：Bangumi 识别和单卷详情会缓存到本机，减少重复查询。

## UI 与交互

v1.3.0 重点优化了桌面体验：

- 深色现代主题，卡片化布局，左侧导航和主工作区分离。
- 顶部状态胶囊显示当前阶段：待扫描、扫描中、预览完成、分类完成等。
- 底部下一步提示会根据当前状态变化，减少误操作。
- 统计卡片显示文件总数、可执行、重复、错误，并带非线性数字缓动。
- 分类进度条使用自绘胶囊样式和非线性进度动画。
- Toast 提示支持弹性滑入和渐入渐出。
- 详情面板显示文件、状态、目标、来源、简介和封面。
- 表格行可双击修正分类。
- 鼠标悬停滚轮可滚动表格、简介和日志。

快捷键：

| 快捷键 | 功能 |
| --- | --- |
| `Ctrl+O` | 选择大文件夹 |
| `F5` | 扫描并预览 |
| `Ctrl+Enter` | 执行分类 |
| `Ctrl+R` | 打开最近报告 |
| `Ctrl+Z` | 撤销上次分类 |

## 快速开始

### 方式一：运行打包版

从 GitHub Releases 下载最新版 exe：

```text
LightNovelSelector-v1.3.0-构建时间.exe
```

双击即可运行，不需要安装 Python。

### 方式二：源码运行

在项目目录运行：

```powershell
.\run.bat
```

也可以直接运行：

```powershell
py .\lightnovel_classifier.py
```

如果 `py` 不可用，脚本会尝试使用系统 `python`。

## 基本使用流程

1. 点击“选择大文件夹”，或点击“新建大文件夹”创建整理目录。
2. 把 `.txt`、`.epub`、`.pdf`、`.mobi`、`.azw3`、`.docx`、`.zip`、`.cbz` 等文件放进去。
3. 可选：勾选“包含子文件夹”“联网识别系列名”“自动重命名”。
4. 点击“扫描并预览”。
5. 检查右侧分类结果和详情面板。
6. 如果识别不准确，选中行后点击“修正分类”，或双击表格行修正。
7. 确认无误后点击“执行分类”。
8. 分类完成后可打开报告，也可以用“撤销上次”恢复。

默认只扫描大文件夹根目录。勾选“包含子文件夹”后，会连子文件夹里的小说一起扫描。

## 分类安全机制

LightNovelSelector 默认按“先预览、再执行、可撤销”的方式工作：

- 扫描阶段不会修改任何原文件。
- 执行前会提示即将移动的文件数量。
- 重复文件会被标记并跳过。
- 单文件读取失败会标记为错误项，不会轻易中断整个扫描。
- 移动文件时如果中途失败，会写出部分报告，已移动成功的文件仍可撤销。
- 报告会记录实际移动目标，避免重名自动改名后无法恢复。

报告文件位置：

```text
大文件夹\classification_report.json
```

CLI 撤销示例：

```powershell
.\.venv-build\Scripts\python.exe .\lightnovel_classifier.py --undo-report "D:\你的大文件夹\classification_report.json"
```

## 自定义规则与设置

设置保存位置：

```text
%LOCALAPPDATA%\LightNovelSelector\settings.json
```

设置页可保存：

- 联网识别系列名
- 是否包含子文件夹
- 是否自动重命名
- 自定义分类规则

自定义规则格式：

```text
匹配模式 => 系列名
```

示例：

```text
*SAO* => Sword Art Online
*无职转生* => 无职转生
```

规则命中时会优先于联网识别。设置保存采用容错策略：如果设置目录不可写或文件被锁定，会提示并写入日志，但不会阻断扫描流程。

## 命令行用法

只预览，不移动文件：

```powershell
py .\lightnovel_classifier.py "D:\你的轻小说大文件夹" --dry-run
```

关闭联网识别：

```powershell
py .\lightnovel_classifier.py "D:\你的轻小说大文件夹" --dry-run --no-network
```

包含子文件夹：

```powershell
py .\lightnovel_classifier.py "D:\你的轻小说大文件夹" --dry-run --recursive
```

启用自动重命名预览：

```powershell
py .\lightnovel_classifier.py "D:\你的轻小说大文件夹" --dry-run --auto-rename
```

按报告撤销：

```powershell
py .\lightnovel_classifier.py --undo-report "D:\你的轻小说大文件夹\classification_report.json"
```

## 支持的文件类型

常见支持格式包括：

```text
.txt .epub .pdf .mobi .azw .azw3 .fb2 .doc .docx .rtf .md .html .htm .cbz .cbr .zip .rar .7z
```

封面读取目前优先支持 EPUB、ZIP、CBZ。PDF 封面提取暂未启用。

## 打包 EXE

运行：

```powershell
.\build_exe.bat
```

脚本会自动创建或修复 `.venv-build` 构建环境，安装 PyInstaller 和 Pillow，然后生成：

```text
dist\LightNovelSelector-v1.3.0-构建时间.exe
```

每次构建都会生成带时间戳的新文件，不会覆盖旧版本。

如果重装系统或更换用户名导致 `.venv-build` 指向旧 Python，`build_exe.bat` 会检测虚拟环境是否可运行。坏环境会移动到 `archive_old_code`，然后用当前可用 Python 自动重建。

## 开发与验证

推荐验证命令：

```powershell
.\.venv-build\Scripts\python.exe -m py_compile lightnovel_classifier.py tests\test_classifier.py
.\.venv-build\Scripts\python.exe -m pytest -q
.\.venv-build\Scripts\python.exe -m ruff check .
.\.venv-build\Scripts\python.exe -m vulture lightnovel_classifier.py tests --min-confidence 80
```

当前测试覆盖重点：

- 文件名解析
- 系列名提取
- 重复文件检测
- 自定义规则优先级
- 设置读写和保存失败容错
- 分类报告生成
- 分类失败时部分报告写入
- 按报告撤销
- UI 使用的状态统计逻辑

## Git 工作流

本项目已经连接 GitHub 仓库：

```text
https://github.com/chenhaoxiang05/LightNovelSelector
```

后续维护改动默认执行：

```powershell
git add .
git commit -m "..."
git push origin main
```

这样每次改动都能在 GitHub 上回档。

## 版本历史

### v1.3.0

- 深色现代 UI 和更完整的交互反馈。
- 状态胶囊、下一步提示、详情状态面板、统计数字缓动。
- 完整文件哈希重复检测，降低重复误判风险。
- 文件移动中途失败时写出部分报告，方便撤销。
- 设置保存失败不阻断扫描。
- 修复 `run.bat` fallback Python 路径含空格时启动失败的问题。
- README 和更新说明改为中文并重写。

### v1.2.0

- 初版现代化工作台。
- 分类报告、撤销、自定义规则、持久设置。
- Windows 构建脚本自动修复损坏虚拟环境。

## 已知限制

- 主程序仍集中在 `lightnovel_classifier.py`，后续扩展建议逐步拆分模块。
- Bangumi 不一定每一本都有独立单卷条目；无匹配时会回退显示系列简介。
- 自动重命名只会在执行分类时移动或改名，扫描预览阶段不会修改原文件。
- 拖拽导入和 HTML 报告尚未实现。

