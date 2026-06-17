# Light Novel Selector 更新说明

更新日期：2026-06-18

## 概览

本次更新继续围绕“安全整理轻小说文件”和“更高级的桌面交互体验”展开。核心变化包括：深色现代 UI、完整文件哈希重复检测、分类失败时保留可撤销报告、设置保存容错、Windows 启动脚本路径修复，以及更明确的操作状态反馈。

## UI 与交互

- 将主界面升级为深色石墨风格，使用低噪声卡片、深色表格、青色强调色和更高对比度文本。
- 顶部增加运行状态胶囊，例如“待扫描”“扫描中”“预览完成”“分类完成”。
- 底部增加下一步操作提示，减少用户不知道下一步该点哪里的问题。
- 统计卡片增加说明文字、悬停反馈和 `easeOutCubic` 数字缓动。
- 初始界面使用 `easeOutBack` 小幅进入动画，避免生硬跳变。
- 进度条继续使用 Canvas 自绘胶囊样式：
  - 扫描中显示非线性滑块动画。
  - 预取和完成阶段使用缓动填充。
- Toast 提示使用弹性滑入、渐入渐出和左侧状态色条。
- 详情面板新增当前文件、状态、目标、来源，选中行后更容易判断分类依据。
- 表格支持双击修正分类。
- 新增快捷键：
  - `Ctrl+O`：选择目录
  - `F5`：扫描并预览
  - `Ctrl+Enter`：执行分类
  - `Ctrl+R`：打开报告
  - `Ctrl+Z`：撤销上次分类

## 分类与文件处理

- 重复文件检测改为完整文件 SHA-256 哈希，不再只依赖“前 1 MiB + 后 1 MiB + 文件大小”。
- 重复文件默认标记为 `duplicate` 并跳过，避免误移动重复副本。
- 分类计划保留 `ready`、`duplicate`、`error` 状态，并在表格和报告中显示。
- 如果文件移动到一半失败，会立即写出部分 `classification_report.json`，已经移动成功的文件仍可通过报告撤销。
- 分类完成后生成 `classification_report.json`，记录移动、跳过、重复、错误、识别置信度和实际目标路径。
- 支持 GUI“撤销上次”和 CLI `--undo-report` 两种撤销方式。

CLI 撤销示例：

```powershell
.\.venv-build\Scripts\python.exe .\lightnovel_classifier.py --undo-report "D:\你的大文件夹\classification_report.json"
```

## 设置与自定义规则

- 设置保存采用 best-effort 策略：如果设置目录不可写或文件被锁定，会记录日志并继续扫描，不阻断主流程。
- 设置页保存失败时会显示提示，不会让界面线程异常退出。
- 设置保存位置：

```text
%LOCALAPPDATA%\LightNovelSelector\settings.json
```

- 设置页可保存：
  - 联网识别系列名
  - 是否包含子文件夹
  - 是否自动重命名
  - 自定义分类规则

- 自定义规则格式：

```text
匹配模式 => 系列名
```

示例：

```text
*SAO* => Sword Art Online
*无职转生* => 无职转生
```

规则命中时会优先于联网识别。

## Windows 环境修复

- 修复 `run.bat` 中 fallback Python 路径未加引号的问题，用户名或路径包含空格时也能正常启动。
- 修复旧系统路径或重装系统后 `.venv-build` 指向不存在 Python 的问题。
- `build_exe.bat` 会检查虚拟环境 Python 是否真实可运行：
  - 不可运行时移动到 `archive_old_code`。
  - 然后使用当前可用 Python 自动重建构建环境。
- 支持通过 `LN_SELECTOR_NO_PAUSE=1` 跳过打包脚本末尾暂停，便于自动化验证。

## 代码质量

- 增加 `try_save_app_settings()`，设置保存失败时不影响扫描和 UI 主流程。
- 增加 `count_plan_statuses()`，让 UI 统计逻辑脱离界面代码并可测试。
- 分类执行失败时在异常抛出前写入部分报告，提高可恢复性。
- 保留 Tkinter 单文件架构，暂不引入重型 UI 依赖，降低 Windows 打包风险。

## 验证结果

已执行并通过：

```text
py_compile: 通过
pytest: 27 passed
ruff: All checks passed
vulture: 无高置信度无用代码
UI smoke: 通过
```

注意：当前 `.pytest_cache` 目录有权限限制，pytest 会提示不能写缓存，但不影响测试结果。

## 最新发布资产

当前 GitHub Release v1.2.0 资产：

```text
LightNovelSelector-v1.2.0-20260612-165140.exe
```

当前 `main` 分支包含 v1.2.0 之后的 UI 和安全性改进。重新打包或发布新版本时，应基于最新 `main` 构建新的 exe。

## 后续可继续优化

- 将 `lightnovel_classifier.py` 逐步拆分为 `core`、`ui`、`services`、`storage` 等模块。
- 增加拖拽导入支持。
- 给分类历史增加独立查看页。
- 给报告增加更适合普通用户阅读的 HTML 或 Markdown 输出。
