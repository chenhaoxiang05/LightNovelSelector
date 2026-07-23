# 第三方组件说明

LightNovelSelector 自身采用 [MIT License](LICENSE)。Windows 安装器还会分发以下第三方运行时或构建产物；它们分别受各自许可证约束，本文件不会修改或替代这些条款。

| 组件 | 用途 | 许可文本 |
| --- | --- | --- |
| Python | Python Sidecar 运行时 | `licenses/Python-LICENSE.txt` |
| PyInstaller | Sidecar 引导程序与运行时钩子 | `licenses/PyInstaller-COPYING.txt` |
| defusedxml | 安全解析 EPUB XML | `licenses/defusedxml-LICENSE.txt` |
| .NET | WinUI 托管运行时 | `licenses/dotnet-LICENSE.txt`、`licenses/dotnet-ThirdPartyNotices.txt` |
| Windows App SDK | WinUI 3、窗口与应用生命周期 | `licenses/WindowsAppSDK-LICENSE.txt`、`licenses/WindowsAppSDK-NOTICE.txt` |
| Microsoft Edge WebView2 Loader | Windows App SDK 的传递依赖 | `licenses/WebView2-LICENSE.txt`、`licenses/WebView2-NOTICE.txt` |
| Inno Setup | 生成安装与卸载程序 | `licenses/InnoSetup-LICENSE.txt` |

正式安装器会把上表中的原始许可和 Notice 文件安装到应用目录的 `licenses` 子目录。本次构建实际使用的组件版本记录在同目录的 `COMPONENT_VERSIONS.txt` 中。
