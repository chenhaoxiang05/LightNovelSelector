# Windows 脚本

本目录保存 Windows 启动、验证和安装器脚本。项目根目录中的 `.bat` 文件是方便双击使用的轻量入口。

| 脚本 | 用途 |
| --- | --- |
| `run_winui.bat` | 还原 .NET 依赖并启动 WinUI 3 原生界面 |
| `build_winui.bat` | 调用 PowerShell 构建器 |
| `build_winui.ps1` | 构建 Sidecar、执行完整检查、发布 WinUI、签名、冒烟并生成可信发布资产 |
| `LightNovelSelector.iss` | Inno Setup 安装器定义 |

根目录映射：

- `run.bat` 与 `run_winui.bat` 都启动 WinUI。
- `build_exe.bat` 与 `build_winui.bat` 都生成 WinUI 安装器。

最终输出固定为四个文件：

```text
dist\winui\LightNovelSelector-v<版本>-win-x64-setup.exe
dist\winui\LightNovelSelector-v<版本>-win-x64-sbom.spdx.json
dist\winui\LightNovelSelector-v<版本>-win-x64-build-info.json
dist\winui\SHA256SUMS.txt
```

脚本会从自身位置解析项目根目录。构建中间文件只进入 `build\`；安装器、SPDX SBOM、构建信息和校验清单全部验证通过后才原子替换 `dist\winui`，替换后验证失败会恢复上一份完整输出。

默认开发构建允许没有代码签名证书，但会在构建信息中明确记录 `unsigned`。正式签名可通过 `WINDOWS_SIGNING_PFX_PATH` 和安全密码参数启用；使用 `-RequireSignature` 时，缺少证书、时间戳或签名验证失败都会立即终止构建。完整参数和下载验证方式见 `DEVELOPMENT.md` 与 `docs\RELEASE_TRUST.md`。
