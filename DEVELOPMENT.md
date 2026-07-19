# LightNovelSelector 开发说明

本文档面向维护者。普通用户只需要阅读 `README.md` 并下载 Release 中的 EXE。

## 技术栈

- Python 3.10+
- pywebview 6.2.1
- Windows Edge WebView2
- 原生 HTML、CSS、JavaScript
- pytest、ruff、vulture
- PyInstaller

界面没有 React、Electron、Node 运行时或本地服务框架。Node 和 Playwright 只用于可选的界面截图验证，不是软件运行依赖。

## 架构

### 入口与兼容层

- `lightnovel_classifier.py`：保留旧启动方式和旧导入路径。
- `lightnovel_selector/cli.py`：参数解析和命令行工作流。

### 领域核心

- `models.py`：不可变数据模型。
- `parsing.py`：标题清洗、卷号识别、系列名提取。
- `files.py`：电子书提示、封面、文件指纹和重复检测。
- `metadata.py`：Bangumi、AniList、Jikan 查询与缓存。
- `classification.py`：预览计划、手动修正、移动、报告和撤销。
- `storage.py`：设置、元数据缓存和原子 JSON 写入。

### 应用与界面

- `application.py`：线程安全的应用服务、后台任务、进度、日志和 UI 序列化。
- `desktop.py`：仅暴露白名单方法的 pywebview 桥接、原生目录选择和外部打开操作。
- `web/index.html`：语义结构与对话框。
- `web/styles.css`：视觉系统、响应式布局、动效和辅助功能。
- `web/app.js`：界面状态、轮询、筛选和用户交互。

前端不会直接执行路径操作。所有移动、恢复、创建目录和打开路径都经过 Python 桥接。

## 本地运行

普通源码启动：

```powershell
.\run.bat
```

脚本会创建 `.venv` 并安装 `requirements.txt`。

开发环境可使用现有构建虚拟环境：

```powershell
.\.venv-build\Scripts\python.exe .\lightnovel_classifier.py
```

窗口调试：

```powershell
$env:LN_SELECTOR_DEBUG="1"
.\.venv-build\Scripts\python.exe .\lightnovel_classifier.py
```

自动启动并在两秒后关闭，用于冒烟测试：

```powershell
$env:LN_SELECTOR_SMOKE_TEST="1"
.\.venv-build\Scripts\python.exe .\lightnovel_classifier.py
```

## 前端独立预览

界面包含只在 `mock=1` 时启用的演示数据，可脱离 Python 检查布局：

```powershell
py -m http.server 8000 --directory .\lightnovel_selector\web
```

浏览器打开：

```text
http://127.0.0.1:8000/?mock=1
http://127.0.0.1:8000/?mock=1&panel=settings
http://127.0.0.1:8000/?mock=1&panel=confirm
http://127.0.0.1:8000/?mock=1&panel=detail
```

正式 pywebview 页面没有 `mock=1`，始终使用真实 Python API。

## 动效约束

- 按钮按压：130ms，`scale(0.97)`，只在精确指针设备启用。
- 弹窗：进入 220ms，退出 140ms，强 `ease-out`。
- Toast：进入 220ms，退出 150ms，沿同一方向进出。
- 抽屉：240ms，使用适合抽屉的自定义曲线。
- 进度条：只动画 `transform`，未知进度使用线性循环。
- 表格选择、筛选、日志追加和快捷键操作不使用位移动画。
- 禁止 `transition: all`、`scale(0)`、`ease-in` 和布局属性动画。
- `prefers-reduced-motion` 下移除位置变化，保留短透明度反馈。

## 开发验证

完整检查：

```powershell
.\.venv-build\Scripts\python.exe -m py_compile lightnovel_classifier.py lightnovel_selector\*.py tests\test_classifier.py
.\.venv-build\Scripts\python.exe -m pytest -q
.\.venv-build\Scripts\python.exe -m ruff check .
.\.venv-build\Scripts\python.exe -m vulture lightnovel_selector lightnovel_classifier.py tests --min-confidence 80
node --check .\lightnovel_selector\web\app.js
git diff --check
```

当前自动测试共 42 项，覆盖：

- 中英文文件名与卷号解析
- 内容提示与本地封面读取
- 两阶段重复检测和完整 SHA-256 确认
- 在线元数据转换与缓存容错
- 自定义规则与手动修正
- 设置读写和保存失败容错
- 结构化扫描、执行与撤销进度
- 报告预写、部分失败报告和原子写入
- 已分类文件递归扫描幂等性
- 应用服务完整扫描、修正、执行和撤销流程
- 并发扫描拒绝与预览版本一致性
- 在线封面大小限制

## 打包 EXE

运行：

```powershell
.\build_exe.bat
```

脚本会：

1. 检查或重建 `.venv-build`。
2. 安装固定版本的运行与开发依赖。
3. 从 `constants.py` 读取版本号。
4. 把 `lightnovel_selector\web` 静态资源加入单文件包。
5. 生成带时间戳的 Windows EXE。

输出示例：

```text
dist\LightNovelSelector-v2.0.0-构建时间.exe
```

打包后冒烟：

```powershell
$env:LN_SELECTOR_SMOKE_TEST="1"
& ".\dist\LightNovelSelector-v2.0.0-构建时间.exe"
```

PyInstaller 的 `pycparser.lextab` 和 `pycparser.yacctab` 可选隐藏模块警告不影响 WebView2 运行；最终判断以 EXE 冒烟结果为准。

## Git 工作流

主分支为 `main`。提交前检查差异，避免加入 `.venv`、`build`、`dist` 和本地缓存：

```powershell
git status
git diff --check
git add README.md DEVELOPMENT.md UPDATE_NOTES.md lightnovel_classifier.py lightnovel_selector requirements.txt requirements-dev.txt pyproject.toml run.bat build_exe.bat tests
git commit -m "..."
git push origin main
```

发布版本时再创建 tag 和 Release，不把测试构建目录提交到仓库。

## 文档约定

- `README.md` 面向使用者。
- `UPDATE_NOTES.md` 面向 Release 页面。
- `DEVELOPMENT.md` 面向维护者。
- 公开文档使用中文，示例路径不得包含真实用户隐私数据。
