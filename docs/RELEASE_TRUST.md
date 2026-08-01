# 发布可信度与下载验证

本文说明正式 Windows Release 如何证明文件完整性、组件构成和构建来源。三类验证解决的问题不同，不能互相替代。

## 每个正式版本包含什么

从新版可信发布流水线生成的 Release 会包含四个文件：

```text
LightNovelSelector-v<版本>-win-x64-setup.exe
LightNovelSelector-v<版本>-win-x64-sbom.spdx.json
LightNovelSelector-v<版本>-win-x64-build-info.json
SHA256SUMS.txt
```

- 安装器：面向 Windows x64 用户的完整自包含版本。
- `SHA256SUMS.txt`：列出安装器、SBOM 和构建信息的 SHA-256，可发现下载损坏或文件被替换。
- SPDX SBOM：列出构建时检测到的 Python、PyInstaller、.NET、Windows App SDK Base/Foundation/InteractiveExperiences/WinUI、WebView2 等实际分发组件。
- 构建信息：记录源码提交、标签、安装器大小与哈希，以及 Authenticode 是否经过验证和时间戳。

GitHub Actions 还会为安装器生成两份不依赖 Release 文本的签名证明：SLSA 构建来源证明和 SBOM 证明。证明绑定安装器的 SHA-256，因此不能挪用到另一个文件。

## 1. 验证 SHA-256

把四个文件下载到同一目录，在 PowerShell 中执行：

```powershell
$expected = Get-Content .\SHA256SUMS.txt
$expected
Get-FileHash .\LightNovelSelector-v<版本>-win-x64-setup.exe -Algorithm SHA256
Get-FileHash .\LightNovelSelector-v<版本>-win-x64-sbom.spdx.json -Algorithm SHA256
Get-FileHash .\LightNovelSelector-v<版本>-win-x64-build-info.json -Algorithm SHA256
```

每个计算结果都应与 `SHA256SUMS.txt` 对应行完全一致。哈希只能证明当前文件与清单一致；清单也必须从本仓库同一个 GitHub Release 下载。

维护者或源码用户还可以使用仓库内置验证器一次检查资产集合、哈希、构建信息和 SBOM：

```powershell
py .\tools\release_assets.py verify --dist .\dist\winui
```

验证器会拒绝路径穿越、重复清单项、未列入清单的调试文件、篡改后的安装器、版本不一致和缺少关键运行组件的 SBOM。

## 2. 验证 Authenticode

当构建环境配置了受信任的代码签名证书时，项目自有的 WinUI EXE、主程序集、Python Sidecar 和最终安装器都会使用 SHA-256 签名并通过 RFC 3161 服务加盖时间戳。构建脚本随后同时使用 SignTool 和 PowerShell 验证签名；任一验证失败都会停止发布。

用户可以检查安装器：

```powershell
Get-AuthenticodeSignature .\LightNovelSelector-v<版本>-win-x64-setup.exe |
  Format-List Status,StatusMessage,SignerCertificate,TimeStamperCertificate
```

只有 `Status` 为 `Valid`、签名者与 Release 构建信息一致时，才应视为已签名版本。当前项目尚未配置商业代码签名证书；无证书构建会在构建信息中明确记录 `authenticode.status = "unsigned"`，不会使用自签名证书冒充可信发布者。

## 3. 验证 GitHub 构建来源证明

安装 [GitHub CLI](https://cli.github.com/) 后执行：

```powershell
gh attestation verify .\LightNovelSelector-v<版本>-win-x64-setup.exe `
  --repo chenhaoxiang05/LightNovelSelector
```

成功结果表明安装器哈希与本仓库某次 GitHub Actions 构建证明匹配。它不会替代 Authenticode 的 Windows 发布者身份提示，但即使项目暂时没有商业证书，也能验证文件确实来自仓库的标签构建流程。

## 维护者构建

普通开发构建不要求证书：

```powershell
.\build_winui.bat
```

配置 PFX 后可以生成并强制验证签名构建：

```powershell
$env:WINDOWS_SIGNING_PFX_PATH = "D:\secure\codesign.pfx"
$env:WINDOWS_SIGNING_PFX_PASSWORD = "<密码>"
.\build_winui.bat -RequireSignature
```

也可使用 `-SigningCertificatePath`、SecureString 类型的 `-SigningCertificatePassword` 和 `-TimestampUrl` 参数。PFX、密码、临时解码文件、安装器和 `dist` 内容都不得提交到 Git。GitHub 仓库使用 `WINDOWS_SIGNING_PFX_BASE64` 与 `WINDOWS_SIGNING_PFX_PASSWORD` Actions Secrets；证书存在时签名失败会阻断 Release，证书不存在时构建会明确产出未签名状态。

正式标签只接受不含 `-dev` 的版本，并要求存在 `docs\releases\v<版本>.md` 中文说明。标签、应用版本、发布说明、测试和四项资产全部通过后，工作流才会创建或修复 GitHub Release。
