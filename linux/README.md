# Linux 桌面版

LightNovelSelector 使用 Python 3.10+、Tk 和 defusedxml。使用当前用户账号在图形桌面中运行。依赖可以通过发行版的软件仓库安装。

**Fedora KDE / Fedora Workstation**

```sh
sudo dnf install python3 python3-tkinter python3-defusedxml
```

**Debian / Ubuntu**

```sh
sudo apt install python3 python3-tk python3-defusedxml
```

## 启动

在源码仓库根目录运行 `sh linux/run.sh`。使用 Linux 分发包时，先解压再启动：

```sh
tar -xzf LightNovelSelector-linux.tar.gz
cd LightNovelSelector
sh linux/run.sh
```

如需从 KDE 或 GNOME 应用菜单打开，在仓库或解压后的根目录执行以下命令。它以当前用户身份安装一份独立的程序副本及图标；之后可以移动或删除解压目录。更新时在新版目录中重复运行即可。

```sh
python3 linux/install.py
```

选择包含小说的目录，按需关闭联网识别，再扫描并检查每行的系列与目标路径。确认整理后可从历史记录选择批次并撤销。安装好系统依赖后，离线识别可以完全在本机运行。

无头 Linux 主机可以在同一目录调用命令行。把下面的路径替换成自己的书库目录，即可离线生成预览。

```sh
python3 lightnovel_classifier.py "/data/轻小说" --no-network --dry-run
```

## 从源码打包

在仓库根目录运行 `sh linux/package.sh`，生成 `dist/LightNovelSelector-linux.tar.gz`。归档内包含图形界面、命令行入口、共享分类核心和许可证。Python、Tk 与 defusedxml 由目标系统提供。
