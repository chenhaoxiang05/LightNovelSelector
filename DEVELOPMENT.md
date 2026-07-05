# LightNovelSelector 开发说明

本文档面向维护者，普通用户只需要阅读 `README.md` 并下载 Release 中的 exe。

## 本地运行

在项目目录运行：

```powershell
.\run.bat
```

或直接运行：

```powershell
py .\lightnovel_classifier.py
```

## 开发验证

推荐在提交前执行：

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

## 近期维护记录

### 2026-07-03

- 重复检测增加两阶段策略：唯一文件只计算快速签名，只有可能重复的候选组才计算完整 SHA-256。
- GUI 同一扫描批次只启动一次详情预加载，避免筛选或重渲染导致重复后台任务。
- 结果表增加 ready 行交替底色，改善大列表可读性。

### 2026-07-05

- UI 从深色石墨风格调整为 Apple/macOS 启发的浅色工作台。
- 主题色改为系统蓝，背景改为浅灰，侧栏使用灰白层级，卡片改为白底和柔和分隔线。
- 统一 UI 字体、卡片间距、按钮 padding、表格行高、Toast 和进度文字样式。

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

## UI_test 实验版打包

UI_test 分支使用独立打包脚本：

```powershell
.\build_ui_test_exe.bat
```

输出目录固定为：

```text
dlist\
```

这样不会和 main 分支常规 `dist\` 产物混淆。`dlist/` 已加入 `.gitignore`，只保留本地构建结果。

## Git 工作流

本项目主分支为 `main`。维护改动默认按以下顺序处理：

```powershell
git status
git add .
git commit -m "..."
git push origin main
```

发布新版本时：

```powershell
git tag -a v版本号 -m "LightNovelSelector v版本号"
git push origin v版本号
gh release create v版本号 "dist\LightNovelSelector-v版本号-构建时间.exe" --title "LightNovelSelector v版本号" --notes-file UPDATE_NOTES.md --latest
```

## 发布说明

- `README.md` 面向下载和使用软件的人。
- `UPDATE_NOTES.md` 面向 Release 页面。
- `DEVELOPMENT.md` 面向维护者。
- 对外文档默认使用中文，避免写入内部工作流和工具使用痕迹。
