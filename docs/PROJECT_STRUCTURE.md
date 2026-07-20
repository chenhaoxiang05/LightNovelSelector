# 项目结构

LightNovelSelector 采用“Python 分类核心 + 可替换桌面界面”的分层结构。WinUI 3 与 pywebview 共用同一套 Python 业务逻辑，原生界面通过 JSON Lines Sidecar 协议调用它。

```text
LightNovelSelector/
├─ lightnovel_selector/          Python 识别、分类、文件与存储核心
│  └─ web/                       pywebview 兼容界面
├─ native/LightNovelSelector.WinUI/
│  ├─ Appearance/                主题、材质与外观偏好
│  ├─ Views/                     主窗口与按职责拆分的主页面 partial
│  ├─ Services/                  Python Sidecar 客户端
│  ├─ Models/                    原生界面数据模型
│  ├─ ViewModels/                纯筛选与连接状态派生
│  ├─ Styles/                    设计令牌与控件样式
│  └─ Assets/                    图标与应用资源
├─ native/LightNovelSelector.WinUI.Tests/
│                                C# 筛选、报告与连接状态测试
├─ .github/workflows/            Windows 持续集成
├─ scripts/windows/              Windows 启动和构建脚本实现
├─ tests/                        Python 核心与 Sidecar 测试
├─ tools/                        开发期资源生成工具
├─ docs/                         架构、截图与维护文档
├─ run_winui.bat                 WinUI 双击兼容入口
├─ build_winui.bat               WinUI 打包兼容入口
├─ run.bat                       pywebview 双击兼容入口
└─ build_exe.bat                 pywebview 打包兼容入口
```

## 生成目录

以下目录不属于源码，已由 Git 忽略：

- `.venv/`、`.venv-build/`：Python 运行与构建环境。
- `build/`：测试缓存、PyInstaller 中间产物和 Sidecar 构建结果。
- `dist/`：可分发程序、便携目录与 ZIP。
- `native/**/bin/`、`native/**/obj/`：.NET 编译中间产物。
- `UI_test/`：历史隔离 worktree，不参与当前分支构建。
- `archive_old_code/`：无法确认用途或损坏环境的保留区。

这些目录可以在关闭程序和开发工具后按需清理，下一次运行或构建会自动重建必要内容。`UI_test/` 是 Git worktree，不应直接移动或删除。
