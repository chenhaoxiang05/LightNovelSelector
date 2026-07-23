# 参与贡献

感谢你愿意帮助改进 LightNovelSelector。项目优先保证文件安全、Windows 可用性和可解释的分类结果，再考虑扩大功能范围。

## 开始之前

提交代码前请先搜索现有 [Issues](https://github.com/chenhaoxiang05/LightNovelSelector/issues)，避免重复工作。较大的功能或会改变文件移动语义的修改，建议先创建功能建议并说明使用场景、预期行为和潜在风险。

请勿在 Issue、日志或测试数据中提交：

- 真实用户名、绝对目录和账户信息；
- 受版权保护的小说正文或整本电子书；
- API 密钥、访问令牌或私人分类报告；
- 未经许可复制的第三方源码与素材。

## 开发环境

- Windows 10 1809 或更高版本，推荐 Windows 11；
- Python 3.10 或更高版本；
- .NET 10 SDK；
- 构建安装器时需要 Inno Setup 6 或更高版本。

启动原生界面：

```powershell
.\run_winui.bat
```

## 修改原则

- 保持 Python 分类核心与 WinUI 3 表现层的职责边界。
- 不绕过“扫描预览、用户确认、执行移动、报告撤销”的安全流程。
- 不改变 Sidecar JSON Lines 字段含义，除非同步更新协议兼容逻辑与测试。
- 文件冲突默认跳过，禁止静默覆盖或删除用户文件。
- UI 状态不能只靠颜色表达，并应尊重 Windows 的减少动态效果设置。
- 动画服务于状态变化，避免在筛选、表格浏览等高频操作中增加等待。
- 公共文档和用户可见文案使用清晰中文，技术标识保留原名。

## 验证修改

提交前至少执行：

```powershell
python -m pytest -q
python -m ruff check .
python -m vulture lightnovel_classifier.py lightnovel_selector tests --min-confidence 80
dotnet test native\LightNovelSelector.WinUI.Tests\LightNovelSelector.WinUI.Tests.csproj -c Release
dotnet build native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj -c Release -p:Platform=x64 -p:WindowsPackageType=None
git diff --check
```

涉及安装或运行时依赖时，还应执行 `build_winui.bat`，验证安装、启动、关闭与卸载后没有残留进程。

## Pull Request

1. 从最新目标分支创建独立功能分支。
2. 让每个提交只表达一个清楚的修改目的。
3. 在 PR 中说明修改内容、原因、用户影响、文件安全影响和验证结果。
4. UI 修改请附浅色与深色截图；交互修改请说明减少动态效果时的行为。
5. 不要提交 `build\`、`dist\`、虚拟环境、真实分类报告或本地 IDE 配置。

维护者会优先检查行为回归、文件安全、异常恢复、Windows 兼容性和测试覆盖。

## 贡献许可

除非你在提交时明确说明其他兼容条款，否则向本仓库提交的贡献将按项目的 [MIT License](LICENSE) 许可。请确保你有权提交相关代码、文档和素材。
