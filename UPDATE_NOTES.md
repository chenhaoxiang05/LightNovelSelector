# Light Novel Selector 更新说明

更新日期：2026-06-12

## 概览

本次更新围绕“更稳的轻小说自动分类”和“更现代的桌面体验”展开。核心目标是减少误操作风险、提升批量整理可控性，并把原本偏传统的 Tkinter 界面调整成浅色、卡片化、反馈更明确的工作台。

## UI 与交互

- 将界面从深色试验版调整为浅色现代风格：浅灰背景、白色卡片、蓝紫强调色和低噪声状态色。
- 重构主工作区层级，增加标题区、副标题、文件导入卡片和结果概览卡片。
- 新增 4 个扫描概览卡片：文件总数、可执行、重复、错误。
- 分类结果表格增加状态色：
  - 可执行：普通白色行。
  - 重复：浅黄色行。
  - 错误：浅红色行。
  - 手动修正：浅蓝色行。
- Toast 提示改为右侧滑入，并带有 `easeOutBack` 回弹动画。
- 进度条改为 Canvas 自绘胶囊样式：
  - 扫描中显示非线性滑块动画。
  - 预取和完成阶段使用 `easeOutCubic` 缓动填充。
- 修复 Windows/Tcl 下字体名包含空格导致的 UI 启动错误。

## 分类与文件处理

- 新增重复文件检测，基于文件大小和首尾内容指纹识别重复项。
- 重复文件默认跳过，避免批量移动时误整理副本。
- 分类计划增加 `ready`、`duplicate`、`error` 状态，并附带备注说明。
- 单文件读取异常会被标记为错误项，不再轻易中断整批扫描。
- 分类完成后生成 `classification_report.json`，记录移动、跳过、重复、错误、置信度和实际目标路径。
- 新增撤销能力，可通过 GUI“撤销上次”或 CLI 根据报告恢复移动过的文件。

CLI 撤销示例：

```powershell
.\.venv-build\Scripts\python.exe .\lightnovel_classifier.py --undo-report "D:\你的大文件夹\classification_report.json"
```

## 设置与自定义规则

- 新增持久设置，保存位置：

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

- 修复 `run.bat` 中旧用户路径写死的问题。
- 修复 `build_exe.bat` 对损坏 `.venv-build` 的处理：
  - 会先检查虚拟环境 Python 是否真实可运行。
  - 如果不可运行，会把坏环境移动到 `archive_old_code`。
  - 然后使用当前可用 Python 自动重建构建环境。
- 支持通过 `LN_SELECTOR_NO_PAUSE=1` 跳过打包脚本末尾暂停，便于自动化验证。

## 代码质量

- 增加 `AppSettings`、`CustomRule` 等配置模型。
- 增加分类报告和撤销相关的纯函数边界。
- 抽出 `plan_status_label()`，减少 UI 内联状态映射。
- 补充测试覆盖：
  - 重复文件检测
  - 自定义规则优先级
  - 设置读写
  - 分类报告撤销
  - 状态标签

## 验证结果

已执行并通过：

```text
pytest: 23 passed
ruff: All checks passed
vulture: 无高置信度无用代码
py_compile: 通过
CLI --help: 通过
UI smoke: 通过
PyInstaller build: 通过
```

最新打包文件：

```text
dist\LightNovelSelector-v1.1.0-20260612-144909.exe
```

## 注意事项

- 当前 `.pytest_cache` 目录存在权限限制，`pytest` 会提示不能写缓存，但不影响测试结果。
- `gh` GitHub CLI 当前未安装；本次发布优先使用本地 Git 和已配置的 GitHub 远程仓库。
- 项目主程序仍然集中在 `lightnovel_classifier.py`，后续如果继续扩展，建议逐步拆分为 `core`、`ui`、`services` 等模块。
