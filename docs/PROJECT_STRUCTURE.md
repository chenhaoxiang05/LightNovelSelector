# 项目结构

LightNovelSelector 采用“WinUI 3 原生界面 + Python 分类核心”的双进程结构。桌面层只有 WinUI 3；Python CLI 仅用于自动化与排错。

```text
LightNovelSelector/
├─ lightnovel_selector/
│  ├─ application.py             应用状态、后台任务与快照
│  ├─ classification.py          历史分类 API 的稳定兼容门面
│  ├─ classification_discovery.py 文件发现与扫描边界
│  ├─ classification_planning.py 分类计划生成、分组与人工修正
│  ├─ classification_reporting.py 报告序列化与有界读取
│  ├─ classification_recovery.py 移动意图日志与中断恢复
│  ├─ classification_execution.py 安全校验后的文件移动事务
│  ├─ classification_undo.py     报告驱动的可恢复撤销
│  ├─ classification_safety.py   路径、快照与报告安全校验
│  ├─ corrections.py             本地人工修正别名与持久化
│  ├─ recognition.py             置信度校准与分类依据
│  ├─ report_history.py          报告历史、指定批次解析与撤销状态
│  ├─ scan_cache.py              增量扫描、可靠文件快照与哈希缓存
│  ├─ scan_session.py            单次扫描、取消、缓存与进度编排
│  ├─ cli.py                     命令行入口
│  ├─ constants.py               版本与公共常量
│  ├─ files.py                   文件扫描、完整哈希、内容提示与封面读取
│  ├─ identity.py                书籍身份归一化、合并与显示标签
│  ├─ metadata.py                提供器协调、异常隔离与元数据缓存
│  ├─ providers/                 公开扩展接口及独立在线书库实现
│  ├─ provider_reliability.py    来源限流、冷却、负缓存与健康状态
│  ├─ models.py                  Python 数据模型
│  ├─ parsing.py                 文件名与卷号解析
│  ├─ sidecar.py                 JSON Lines Sidecar 服务
│  └─ storage.py                 设置、缓存及 JSON/JSON Lines 持久化
├─ native/
│  ├─ LightNovelSelector.WinUI/  WinUI 3 应用
│  │  ├─ Appearance/             主题和窗口材质
│  │  ├─ Helpers/                动效辅助
│  │  ├─ Models/                 C# 协议与界面模型
│  │  ├─ Security/               外部 URI 等系统边界校验
│  │  ├─ Services/               Sidecar 客户端
│  │  ├─ Styles/                 语义设计令牌
│  │  ├─ ViewModels/             筛选、连接状态与自适应布局策略
│  │  └─ Views/                  主窗口和分职责页面 partial
│  └─ LightNovelSelector.WinUI.Tests/
├─ scripts/windows/
│  ├─ run_winui.bat              源码模式启动
│  ├─ build_winui.bat            PowerShell 构建包装
│  ├─ build_winui.ps1            完整验证与安装器流水线
│  └─ LightNovelSelector.iss     Inno Setup 安装脚本
├─ tests/                         Python 核心、脱敏识别语料与 Sidecar 测试
├─ benchmarks/
│  └─ performance_budget.json     1 万文件 CI 性能预算
├─ tools/
│  ├─ benchmark_large_library.py  合成大型书库性能与取消基准
│  ├─ generate_native_assets.py  生成原生应用图标
│  ├─ release_assets.py          生成并验证 SBOM、构建信息与校验清单
│  └─ verify_sidecar.py          验证打包 Sidecar 协议
├─ .config/dotnet-tools.json      固定 Microsoft SBOM Tool 版本
├─ .github/workflows/release.yml  标签构建、来源证明与 Release 发布
├─ docs/                          架构、截图与维护说明
├─ LICENSE                        MIT 开源许可证
├─ THIRD_PARTY_NOTICES.md         第三方运行时与许可索引
├─ Directory.Build.props          NuGet 锁定、审计与确定性构建
├─ requirements-runtime.txt       Python 运行依赖
├─ lightnovel_classifier.py      Python CLI/API 兼容入口
├─ lightnovel_sidecar.py         PyInstaller Sidecar 入口
├─ run.bat / run_winui.bat       WinUI 启动入口
└─ build_exe.bat / build_winui.bat WinUI 安装器构建入口
```

## 生成目录

以下目录不属于源码，已由 Git 忽略：

- `.venv-build/`、`.venv/`：Python 虚拟环境。
- `build/`：测试缓存、Sidecar、WinUI 暂存发布和安装器临时输出。
- `dist/`：最终可分发安装器。
- `native/**/bin/`、`native/**/obj/`：.NET 构建输出。
- `__pycache__/`、`.pytest_cache/`、`.ruff_cache/`：工具缓存。

正常构建完成后，`dist\winui` 只包含当前安装 EXE、SPDX SBOM、构建信息和 `SHA256SUMS.txt`。构建中间目录不会直接写入正式输出，四项资产全部验证成功后才原子替换 `dist\winui`，因此失败构建不会留下半套发布文件。

## 历史恢复点

- `legacy-webview-final`：最后一个包含 pywebview/WebView 桌面层的完整版本。
- 远端 `legacy/webview-v2` 分支：可直接检出和维护的旧 WebView 版本。
- 远端 `ui` 分支：早期隔离 UI 试验分支。

当前源码不保留旧 WebView 静态资源或损坏虚拟环境归档。
