# Windows 安装包体积与依赖边界

LightNovelSelector 的 Windows 版本同时携带 WinUI 3、.NET 和 Python Sidecar，目标是下载后不要求用户另装 Python、.NET 或 Windows App SDK。本页记录在保留这一体验前提下的体积边界、测量方法和防回归约束。

## 为什么可以缩小

Windows App SDK 2.x 采用组件化 NuGet 结构。完整 `Microsoft.WindowsAppSDK` 元包会引用 WinUI 之外的 AI、Windows ML、Widgets 和 DWrite 等组件；本项目没有调用这些 API，只需要：

- `Microsoft.WindowsAppSDK.Base`：自包含部署基础；
- `Microsoft.WindowsAppSDK.Foundation`：窗口、应用生命周期和系统背景；
- `Microsoft.WindowsAppSDK.InteractiveExperiences`：输入与交互支持；
- `Microsoft.WindowsAppSDK.WinUI`：WinUI 3、XAML 控件和 WebView2 Loader 传递依赖。

项目因此直接引用所需组件，不再引用完整元包。这个做法符合微软的[组件化 SDK 说明](https://learn.microsoft.com/windows/apps/windows-app-sdk/use-windows-app-sdk-in-existing-project)，Windows App SDK 与 .NET 仍保持[自包含部署](https://learn.microsoft.com/windows/apps/package-and-deploy/self-contained-deploy/deploy-self-contained-apps)。

## 可复现结果

以下数据来自同一台 Windows x64 机器、同一源码和相同 `dotnet publish` 参数；MiB 按 1,048,576 字节计算：

| 对比项 | 文件数 | 字节 | MiB | 变化 |
| --- | ---: | ---: | ---: | ---: |
| 完整 Windows App SDK 元包 | 512 | 232,268,518 | 221.51 | 基线 |
| 仅 WinUI 必需组件 | 450 | 178,176,859 | 169.92 | -23.3% |
| 完整发布暂存区，含 Sidecar 与许可证 | 468 | 188,745,228 | 180.00 | 当前结果 |

同一轮可信构建中，Inno Setup 安装器从上一版本的 72,482,903 字节降到 56,360,775 字节，减少 16,122,128 字节（22.2%）。安装器压缩率会随版本和文件内容变化，因此长期回归判断以未压缩暂存目录和依赖集合为主。

移除的主要文件包括 `onnxruntime.dll`、`DirectML.dll`、Windows AI、Windows ML、Widgets、独立 DWrite 组件及其资源，总计减少 54,091,659 个未压缩字节。语言目录仍保留，因为其中包含 WinUI 控件真实使用的 `.mui` 本地化资源。

## 保留的交付能力

- 用户仍不需要预装 Python、.NET 或 Windows App SDK。
- Python Sidecar、启动/外观冒烟、分类协议和文件整理逻辑保持不变。
- 每个实际分发组件仍进入 SPDX SBOM、`COMPONENT_VERSIONS.txt` 和安装目录许可证集合。
- `PublishTrimmed` 保持关闭，避免破坏 XAML 与 JSON 反射；不通过手工删除 DLL 获取表面体积收益。

## 自动防回归

1. 项目元数据测试拒绝重新引入完整 Windows App SDK 元包、AI、ML、Widgets、DWrite 和相关张量依赖。
2. 构建脚本拒绝发布目录出现 ONNX Runtime、DirectML、Windows AI、Widgets 或 Workloads 文件。
3. 完整发布暂存区上限为 210 MiB，为 .NET 和 WinUI 正常维护更新保留余量，同时拦截组件集合意外膨胀。
4. SBOM 验证器强制要求 Base、Foundation、InteractiveExperiences、WinUI、WebView2、.NET、CPython、PyInstaller、defusedxml 和 Inno Setup。
5. 任何正式安装器仍须通过启动、外观、Sidecar 协议、SBOM、哈希和最终四资产验证。

## 本地复核

```powershell
.\build_winui.bat -KeepStaging

$files = Get-ChildItem .\build\winui-package -Recurse -File
$bytes = ($files | Measure-Object Length -Sum).Sum
"{0:N2} MiB，{1} 个文件" -f ($bytes / 1MB), $files.Count
```

构建日志也会直接打印暂存目录大小；超过预算或发现被禁止组件时，构建会在签名和生成安装器之前停止。
