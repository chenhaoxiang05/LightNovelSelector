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
- 已分类文件的递归扫描幂等性
- 执行与撤销的结构化进度回调

## 近期维护记录

### 2026-07-03

- 重复检测增加两阶段策略：唯一文件只计算快速签名，只有可能重复的候选组才计算完整 SHA-256。
- GUI 同一扫描批次只启动一次详情预加载，避免筛选或重渲染导致重复后台任务。
- 结果表增加 ready 行交替底色，改善大列表可读性。

### 2026-07-05

- UI 从深色石墨风格调整为 Apple/macOS 启发的浅色工作台。
- 主题色改为系统蓝，背景改为浅灰，侧栏使用灰白层级，卡片改为白底和柔和分隔线。
- 统一 UI 字体、卡片间距、按钮 padding、表格行高、Toast 和进度文字样式。

### 2026-07-10

- 主线 UI 重整为中性石墨深色控制台，使用语义色区分识别、执行、成功、警告、错误和手动修正。
- 关键按钮改为自绘控件，复选框固定显示 `✓/□`，并补齐空状态、横向滚动和稳定禁用态。
- 新增 `LN_SELECTOR_REDUCED_MOTION=1`，可关闭非必要的数字、进度、Toast 和入场动画。
- 扫描线程改为使用主线程快照，不再从后台读取 Tk 变量。
- 扫描、执行、撤销事件增加操作令牌，过期日志和结果不会覆盖当前任务。
- 撤销改为后台执行；忙碌期间锁定冲突控件，文件移动或恢复期间阻止直接关窗。
- 目录或识别设置变化时自动作废旧预览；执行完成后条目标记为“已移动”，防止二次执行。
- 修复递归扫描已分类文件时可能生成 `(1)` 文件名的问题，新增“无需移动”状态。
- 设置、缓存和分类报告改为原子 JSON 写入；执行前先写入 0 进度报告，报告不可写时不会移动文件。
- 测试增至 33 项，并增加完整扫描、执行、报告和撤销 UI smoke。

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
