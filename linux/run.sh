#!/bin/sh
set -eu

app_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    echo '请使用 Python 3.10 或更高版本启动 Linux 桌面版。' >&2
    exit 1
fi
if ! python3 -c 'import tkinter, defusedxml' 2>/dev/null; then
    echo '请安装 Tk 和 defusedxml。Fedora 使用 python3-tkinter、python3-defusedxml，Debian/Ubuntu 使用 python3-tk、python3-defusedxml。' >&2
    exit 1
fi
exec python3 "$app_dir/app.py" "$@"
