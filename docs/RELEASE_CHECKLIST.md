# 发布检查清单

本文档用于正式发布前的可重复验收。任何涉及文件移动、报告或撤销的版本都不应跳过核心检查。

## 代码与仓库

- 工作树干净，版本号在 Python、WinUI 项目和清单中一致。
- 当前提交已经通过 Pull Request，不直接从未审查的本地状态打标签。
- `git diff --check`、Ruff lint/format、Mypy、Bandit、Vulture、pytest 和 MSTest 全部通过。
- pip-audit、NuGet audit、CodeQL、Secret scanning 没有未处理的高影响结果。
- GitHub Actions 只使用固定的完整提交 SHA；NuGet 锁文件与项目引用一致。
- 当前源码不包含令牌、真实用户名、绝对本机路径、小说正文、私人报告或临时截图。

## 文件安全

- 验证预览阶段不移动文件。
- 验证重复内容使用完整哈希确认，不仅依赖快速签名。
- 连续扫描同一批未变化文件，确认快速签名、完整哈希和本地识别缓存命中，分类结果保持一致。
- 修改文件中部并恢复原最后写入时间，确认 ChangeTime 仍使完整哈希缓存失效且不会误判重复。
- 模拟不支持可靠变更令牌、缓存损坏、超限、初始化失败和写入失败，确认自动实时重算且扫描不中断。
- 验证同名目标不会覆盖，扫描后被改写的源文件会拒绝执行。
- 验证源文件被替换为目录或符号链接时会拒绝执行。
- 验证部分移动失败后报告仍能撤销已完成项。
- 模拟进程在移动之间强制中断，确认恢复日志能重建已移动项并在成功恢复后删除。
- 模拟源和目标同时存在、日志目标越界及日志被篡改，确认自动恢复停止并保留现场。
- 验证多文件批处理只在任务边界重写完整报告，不会每移动一个文件就重写全部条目。
- 验证恶意或被移出原目录的报告无法越过分类根目录。
- 验证分类后被编辑或替换的目标文件不会被旧报告撤销。
- 验证撤销时源和目标同时存在、同时缺失或已恢复文件被修改会在整批移动前停止。
- 模拟撤销在部分文件后强制中断，确认重新执行只跳过已验证的恢复项并继续其余文件。
- 模拟跨卷撤销复制完成但源文件清理失败，确认保留两份文件并拒绝自动判断。
- 验证超大报告只截断活动页明细，不影响打开完整 JSON 或执行撤销。
- 验证设置保存失败不会阻断扫描。
- 连续启动两次应用，确认只保留一个主进程并唤回已有窗口。
- 使用弱文件名与正文提示测试，确认正文提示不会进入任何联网查询。
- 验证重复指纹计算可取消，超过 10,000 个受支持文件时会在移动前拒绝扫描。

## 构建与安装

```powershell
.\build_winui.bat
```

- Sidecar 协议验证、Python/C# 检查、WinUI 发布和两轮冒烟全部成功。
- `dist\winui` 不包含暂存目录、语言资源散文件、旧版本副本或未列入校验清单的文件。
- 安装器内容不包含 `.pdb`、开发期 runtime 配置、源码、本机绝对路径或其他调试产物。
- 完整暂存目录不超过 210 MiB，且不包含 ONNX Runtime、DirectML、Windows AI、Windows ML、Widgets 或 Workloads 可选组件。
- 安装目录包含项目 `LICENSE`、第三方组件索引和全部必需的运行时许可证/Notice 原文。
- 安装器按当前用户安装，不请求管理员权限。
- 安装、首次启动、扫描预览、关闭、卸载和残留进程检查通过。
- 使用 Windows Defender 扫描最终安装器。
- `dist\winui` 只包含当前安装器、SPDX SBOM、构建信息和 `SHA256SUMS.txt` 四个普通文件。
- 执行 `tools\release_assets.py verify --dist dist\winui`，确认资产集合、三项 SHA-256、版本、源码提交和关键组件全部一致。
- 检查构建信息中的 `source.dirty`；正式标签构建必须为 `false`。
- 记录 Authenticode 状态；配置证书时安装器必须通过 SignTool 与 PowerShell 验证并带时间戳，没有证书时在 README 与 Release 明确说明“未签名”。
- 查看 SPDX SBOM，确认至少包含 CPython、defusedxml、PyInstaller、.NET Runtime、Windows App SDK Base/Foundation/InteractiveExperiences/WinUI、WebView2 和 Inno Setup。

## Release

- 为目标版本提交 `docs\releases\v<版本>.md` 中文说明，再从 `main` 的已验证提交创建带注释标签。
- Release 标题、正文、文件名和应用内版本一致。
- 标签工作流的版本检查、完整构建、SLSA 来源证明和 SBOM 证明全部成功。
- 上传完成后重新下载四项资产并计算 SHA-256，不能只校验 runner 内的原文件。
- 使用 `gh attestation verify <安装器> --repo chenhaoxiang05/LightNovelSelector` 验证下载后的安装器来源证明。
- Release 正文使用中文，列出主要修复、兼容性、已知限制、验证结果，并引导用户使用随附 `SHA256SUMS.txt`。
- 发布后再次检查安装器链接、README 徽章、CodeQL、规则集、Dependabot 和私密漏洞报告入口。
