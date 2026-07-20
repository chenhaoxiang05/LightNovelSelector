# 项目结构

LightNovelSelector 采用“WinUI 3 原生界面 + Python 分类核心”的双进程结构。桌面层只有 WinUI 3；Python CLI 仅用于自动化与排错。

```text
LightNovelSelector/
├─ lightnovel_selector/
│  ├─ application.py             应用状态、后台任务与快照
│  ├─ classification.py          分类计划、完整哈希、执行、报告与撤销
│  ├─ cli.py                     命令行入口
│  ├─ constants.py               版本与公共常量
│  ├─ files.py                   文件扫描、内容提示与封面读取
│  ├─ metadata.py                系列解析、联网元数据与缓存
│  ├─ models.py                  Python 数据模型
│  ├─ parsing.py                 文件名与卷号解析
│  ├─ sidecar.py                 JSON Lines Sidecar 服务
│  └─ storage.py                 设置、缓存和 JSON 持久化
├─ native/
│  ├─ LightNovelSelector.WinUI/  WinUI 3 应用
│  │  ├─ Appearance/             主题和窗口材质
│  │  ├─ Helpers/                动效辅助
│  │  ├─ Models/                 C# 协议与界面模型
│  │  ├─ Services/               Sidecar 客户端
│  │  ├─ Styles/                 语义设计令牌
│  │  ├─ ViewModels/             筛选与连接状态逻辑
│  │  └─ Views/                  主窗口和分职责页面 partial
│  └─ LightNovelSelector.WinUI.Tests/
├─ scripts/windows/
│  ├─ run_winui.bat              源码模式启动
│  ├─ build_winui.bat            PowerShell 构建包装
│  ├─ build_winui.ps1            完整验证与安装器流水线
│  └─ LightNovelSelector.iss     Inno Setup 安装脚本
├─ tests/                         Python 核心与 Sidecar 测试
├─ tools/
│  ├─ generate_native_assets.py  生成原生应用图标
│  └─ verify_sidecar.py          验证打包 Sidecar 协议
├─ docs/                          架构、截图与维护说明
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

正常构建完成后，`dist\winui` 只包含一个安装 EXE。构建中间目录不会直接写入 `dist`，因此失败构建不会留下空发布目录。

## 历史恢复点

- `legacy-webview-final`：最后一个包含 pywebview/WebView 桌面层的完整版本。
- 远端 `ui` 分支：早期隔离 UI 试验分支。

当前源码不保留 `UI_test` worktree、WebView 静态资源或损坏虚拟环境归档。
