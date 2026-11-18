"""Install a self-contained copy of the Python source and a per-user menu entry."""

from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

APP_ID = "io.github.chenhaoxiang05.LightNovelSelector"
ICON = Path("native/LightNovelSelector.WinUI/Assets/Square150x150Logo.scale-200.png")


def desktop_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def exec_argument(path: Path) -> str:
    # The desktop parser unescapes the string, unquotes the argument, then expands field codes.
    escaped = "".join("\\" + ch if ch in {"\\", "`", '"', "$"} else ch for ch in str(path))
    return '"' + desktop_value(escaped.replace("%", "%%")) + '"'


def atomic_write(path: Path, content: bytes):
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        name = Path(temp.name)
        try:
            temp.write(content)
            temp.flush()
            os.replace(name, path)
        finally:
            name.unlink(missing_ok=True)


def install(source: Path, data_home: Path):
    app_dir = data_home / APP_ID
    buffer = io.BytesIO()
    # Hash-addressed copies keep an open window working during an upgrade.
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo("__main__.py"), "from linux.app import main\nmain()\n")
        paths = [
            Path("LICENSE"),
            Path("THIRD_PARTY_NOTICES.md"),
            Path("linux/__init__.py"),
            Path("linux/app.py"),
            Path("linux/history.py"),
            *(p.relative_to(source) for p in (source / "lightnovel_selector").rglob("*.py")),
        ]
        for path in sorted(paths):
            entry = zipfile.ZipInfo(path.as_posix())
            archive.writestr(entry, (source / path).read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    content = buffer.getvalue()
    bundle = app_dir / (hashlib.sha256(content).hexdigest() + ".pyz")
    atomic_write(bundle, content)
    icon = app_dir / "icon.png"
    atomic_write(icon, (source / ICON).read_bytes())
    entry = data_home / "applications" / f"{APP_ID}.desktop"
    application = (
        "[Desktop Entry]\nType=Application\nVersion=1.0\n"
        "Name=LightNovelSelector\nGenericName=Light novel organizer\nGenericName[zh_CN]=轻小说整理工具\n"
        f"Exec=python3 {exec_argument(bundle)}\nIcon={desktop_value(str(icon))}\n"
        "Terminal=false\nCategories=Utility;FileTools;\nStartupWMClass=LightNovelSelector\n"
    )
    atomic_write(entry, application.encode("utf-8"))
    return entry


if __name__ == "__main__":
    if sys.version_info < (3, 10):  # noqa: UP036 - installer runs under the user's system Python.
        sys.exit("需要 Python 3.10 或更高版本。")
    try:
        import tkinter  # noqa: F401

        import defusedxml  # noqa: F401
    except ImportError:
        sys.exit("请先按 linux/README.md 安装 Tk 和 defusedxml。")
    data_home = Path(os.environ.get("XDG_DATA_HOME") or "")
    if not data_home.is_absolute():
        data_home = Path.home() / ".local" / "share"
    print(f"已添加到当前用户的应用菜单：{install(Path(__file__).resolve().parents[1], data_home)}")
