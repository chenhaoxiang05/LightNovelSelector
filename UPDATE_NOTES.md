# LightNovelSelector v2.0.0 更新说明

## 本轮重点

本轮完成从旧 WebView 桌面层到 WinUI 3 的全面收口，并重做 Windows 交付方式。分类语义和 Sidecar 协议保持兼容，下载者从手动解压 ZIP 改为直接运行单个安装 EXE。

## 单 EXE 安装与目录清理

- 新增 Inno Setup 安装器，输出 `LightNovelSelector-v2.0.0-win-x64-setup.exe`。
- 安装器默认按当前用户安装，不要求管理员权限，支持开始菜单、可选桌面快捷方式和卸载。
- 发布改为 `build` 干净暂存区；只有 Sidecar、测试、WinUI 发布、两轮冒烟和安装器编译全部成功后才替换 `dist\winui`。
- 移除时间戳便携目录和 ZIP 双份输出，避免每次构建累计约 325 MiB 重复文件。
- 删除失败构建遗留的 `v0.0.0` 空目录，并消除继续产生此类目录的根因。
- 安装实测包含 516 个文件、0 个空目录；卸载后应用目录和 Sidecar 进程均无残留。

截图中 `pl-PL`、`sl-SI` 等目录实际包含 WinUI `.mui` 多语言资源，并非空目录。新安装器将这些运行细节封装起来，同时保留不同系统语言下的控件兼容性。

## WinUI-only 架构

- 删除 `desktop.py`、`lightnovel_selector/web/` 和 pywebview 依赖。
- `run.bat`、`run_winui.bat` 统一启动 WinUI 3。
- `build_exe.bat`、`build_winui.bat` 统一生成 WinUI 安装器。
- 主程序文件名从 `LightNovelSelector.WinUI.exe` 简化为 `LightNovelSelector.exe`。
- Python CLI 保留给自动化和排错，不再承担桌面界面入口。
- 旧 WebView 最终完整版本已推送到 GitHub 标签 `legacy-webview-final`。
- 本地 `UI_test` worktree 和损坏的旧构建环境已经清理；远端 `ui` 分支保持不变。

## 操作体验

- 恢复上次目录或新选目录后，待机状态正确显示“等待扫描预览”。
- 空预览明确区分“尚未选择目录”和“已经选择、尚未扫描”。
- 新增 `Ctrl+O` 选择目录、`F5` 扫描、`Ctrl+Enter` 打开整理确认。
- 图标按钮、主题/材质选择器、动态效果开关和 Toast 补齐辅助技术名称与动态状态通知。
- 保持既有 100–220ms 非线性动效；高频筛选与键盘操作不新增装饰动画。

## 既有安全与稳定性

- 重复检测使用完整文件内容哈希。
- 文件移动部分失败时仍保存可撤销报告。
- 设置保存采用 best-effort，不阻断扫描。
- Sidecar 支持一次自动恢复和手动重连，重连后不自动重跑扫描或移动。
- 分类筛选使用主集合/可见集合分离，筛选不会缩小实际执行计划。
- 报告使用强类型模型展示移动、跳过、重复、错误和源/目标路径。

## 验证结果

- Python：46 项测试通过。
- C#：14 项测试通过。
- WinUI Debug / Release x64：0 警告、0 错误。
- ruff、vulture、`git diff --check` 通过。
- Sidecar `ping` / `shutdown` 协议通过独立工具验证。
- 暂存发布版启动和外观冒烟通过。
- 安装、安装后启动、关闭、卸载与残留进程检查通过。

## 后续可选工作

- 购买 Windows 代码签名证书，减少下载和安装时的未知发布者提示。
- 在正式发布流程中自动生成并公布 SHA-256。
- 根据真实用户样本继续调整分类规则和元数据命中率。
