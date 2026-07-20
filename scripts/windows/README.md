# Windows 脚本

本目录保存 Windows 启动、调试和打包脚本的实际实现。项目根目录中的同名 `.bat` 文件仅是兼容入口，方便继续双击运行，也避免破坏已有使用方式。

| 脚本 | 用途 |
| --- | --- |
| `run_winui.bat` | 还原依赖并启动 WinUI 3 原生界面 |
| `build_winui.bat` | 构建 Sidecar、执行 C# 测试并生成自包含 WinUI 便携 ZIP |
| `run.bat` | 启动 pywebview 兼容界面 |
| `build_exe.bat` | 构建 pywebview 单文件兼容版 |

脚本会从自身位置解析项目根目录，因此既可以从根目录兼容入口调用，也可以直接在本目录运行。
