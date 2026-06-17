# 轻小说联网分类工具

这是一个我和Codex5.5xhigh编写的 Python/Tkinter 桌面工具，是一个本人自用的demoplay用来整理轻小说文件，欢迎大家提出问题或者需求，让我和C大哥修复（bushi，也可以commit一些自己的分支😋，使用方法如下。选择一个“大文件夹”后，软件会扫描其中的小说文件，自动识别系列名，把同系列小说移动到同一个系列文件夹里，并在界面左侧显示封面、简介和 Bangumi 条目信息。

## 启动

开发运行：

```powershell
.\run.bat
```

或直接运行：

```powershell
py .\lightnovel_classifier.py
```

打包后的程序在：

```text
D:\selector\dist\LightNovelSelector-v1.2.0-20260612-最新构建时间.exe
```

## 基本使用

1. 点击“选择大文件夹”，或点击“新建大文件夹”创建一个整理目录。
2. 把 `.txt`、`.epub`、`.pdf`、`.mobi`、`.azw3`、`.docx`、`.zip`、`.cbz` 等小说文件放进去。
3. 点击“扫描并预览”。
4. 在右侧列表选择某一本，左侧会显示该卷的简介和封面。
5. 确认无误后点击“执行分类”，文件会移动到 `大文件夹\系列名\文件名`。

默认只扫描大文件夹根目录。勾选“包含子文件夹”后，会连子文件夹里的小说一起扫描。

## 主要功能

- 联网识别系列名：优先查询 Bangumi，必要时使用 AniList/Jikan 辅助识别。
- 单卷详情：选中某一本时显示该卷简介、封面和条目链接。
- 本地封面优先：EPUB/ZIP/CBZ 中有封面时优先读取本地封面，没有时再加载 Bangumi 封面。
- 自动重命名：勾选“自动重命名”后，会尝试根据文件名、电子书内容和 Bangumi 单卷信息生成更清楚的新文件名。
- 系列筛选：可以按系列过滤右侧列表。
- 系列介绍：点击“系列介绍”可查看整个作品的简介。
- 持久缓存：Bangumi 识别和单卷详情会缓存到 `%LOCALAPPDATA%\LightNovelSelector\metadata_cache.json`，默认 30 天有效。

## 性能与体验优化

- 扫描后会自动预加载单卷详情，切换选中项时更少等待。
- 单卷详情预加载使用小并发队列，默认 4 路并发，比逐本串行查询更快。
- 右侧列表、左侧简介、底部日志都支持鼠标悬停滚轮滚动。
- 底部日志限制为最近 300 行，避免大量扫描记录拖慢界面。
- 重新扫描时使用令牌隔离旧后台任务，避免旧结果覆盖新列表。

## 命令行预览

只预览，不移动文件：

```powershell
py .\lightnovel_classifier.py "D:\你的轻小说大文件夹" --dry-run
```

启用自动重命名预览：

```powershell
py .\lightnovel_classifier.py "D:\你的轻小说大文件夹" --dry-run --auto-rename
```

关闭联网识别：

```powershell
py .\lightnovel_classifier.py "D:\你的轻小说大文件夹" --dry-run --no-network
```

包含子文件夹：

```powershell
py .\lightnovel_classifier.py "D:\你的轻小说大文件夹" --dry-run --recursive
```

## 打包 EXE

双击：

```text
build_exe.bat
```

脚本会自动创建 `.venv-build` 构建环境，安装/更新 PyInstaller 和 Pillow，然后生成带版本号和时间戳的 exe：

```text
dist\LightNovelSelector-v1.2.0-20260612-最新构建时间.exe
```

每次构建都会生成新文件，不会直接覆盖上一个版本。把最新的 exe 发给没有 Python 环境的人即可。使用者不需要安装 Python；只有打包电脑需要联网安装依赖。

## Git

本目录已经初始化为 Git 仓库。常用命令：

```powershell
git status
git add .
git commit -m "Update light novel selector"
git push origin main
```

之后每次由 Codex 完成修改并验证后，会默认提交到本地 Git 并推送到 GitHub，方便随时回档。

## 说明与限制

- 分类文件夹名使用“系列名”，单卷详情则按当前文件名或电子书内容单独查询。
- Bangumi 不一定每一本都有独立单卷条目；没有匹配时会回退显示系列简介。
- 自动重命名只会在执行分类时移动/改名，扫描预览阶段不会修改原文件。
- PDF 封面提取暂未启用，优先支持 EPUB、ZIP、CBZ。

## 最近优化

- 扫描时会基于文件大小和完整 SHA-256 内容哈希检测重复文件，重复项默认跳过，避免误移动重复副本。
- 执行分类后会在目标大文件夹生成 `classification_report.json`，记录移动、跳过、重复、错误和识别置信度。
- 界面增加深色现代主题、左侧导航、状态胶囊、下一步提示、详情状态面板、Toast 提示、非线性进度动画和手动修正分类入口。
- 如果自动识别结果不准确，可以在预览表格选择条目后点击“修正分类”，手动指定系列名。
- 也可以双击表格行快速修正分类。
- 设置页会保存联网识别、递归扫描、自动重命名和自定义规则到 `%LOCALAPPDATA%\LightNovelSelector\settings.json`。
- 设置保存失败不会阻断扫描主流程，会提示并写入日志。
- 自定义规则格式为 `匹配模式 => 系列名`，例如 `*SAO* => Sword Art Online`，命中后优先于联网识别。
- 可以用报告撤销一次分类移动：

```powershell
.\.venv-build\Scripts\python.exe .\lightnovel_classifier.py --undo-report "D:\你的大文件夹\classification_report.json"
```

## 环境修复

如果重装系统或更换用户名导致 `.venv-build` 指向旧 Python，`build_exe.bat` 会检测虚拟环境是否可运行。坏环境会被移动到 `archive_old_code`，然后用当前可用 Python 自动重建。

## 开发验证

```powershell
.\.venv-build\Scripts\python.exe -m py_compile lightnovel_classifier.py tests\test_classifier.py
.\.venv-build\Scripts\python.exe -m pytest -q
.\.venv-build\Scripts\python.exe -m ruff check .
.\.venv-build\Scripts\python.exe -m vulture lightnovel_classifier.py tests --min-confidence 80
```
