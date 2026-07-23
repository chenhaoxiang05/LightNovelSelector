# Windows 脚本

本目录保存 Windows 启动、验证和安装器脚本。项目根目录中的 `.bat` 文件是方便双击使用的轻量入口。

| 脚本 | 用途 |
| --- | --- |
| `run_winui.bat` | 还原 .NET 依赖并启动 WinUI 3 原生界面 |
| `build_winui.bat` | 调用 PowerShell 构建器 |
| `build_winui.ps1` | 构建 Sidecar、执行测试、发布 WinUI、冒烟并生成安装 EXE |
| `LightNovelSelector.iss` | Inno Setup 安装器定义 |

根目录映射：

- `run.bat` 与 `run_winui.bat` 都启动 WinUI。
- `build_exe.bat` 与 `build_winui.bat` 都生成 WinUI 安装器。

最终输出：

```text
dist\winui\LightNovelSelector-v<版本>-win-x64-setup.exe
```

脚本会从自身位置解析项目根目录。构建中间文件只进入 `build\`，验证全部通过后才替换 `dist\winui`。
