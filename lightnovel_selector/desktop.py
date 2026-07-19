from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .application import ApplicationService
from .constants import APP_NAME, APP_VERSION
from .parsing import collapse_spaces, safe_folder_name


def _resource_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "lightnovel_selector" / "web"
    return Path(__file__).resolve().parent / "web"


def _open_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"路径不存在：{path}")
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    subprocess.Popen(command)


class DesktopBridge:
    def __init__(self, service: ApplicationService | None = None) -> None:
        self._service = service or ApplicationService()
        self._window: Any | None = None

    def _attach_window(self, window: Any) -> None:
        self._window = window

    @staticmethod
    def _response(call: Callable[[], Any]) -> dict[str, Any]:
        try:
            return {"ok": True, "data": call()}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}

    def bootstrap(self) -> dict[str, Any]:
        return self._response(lambda: self._service.snapshot())

    def poll(self, log_cursor: int = 0, plans_revision: int = -1) -> dict[str, Any]:
        return self._response(lambda: self._service.snapshot(int(log_cursor), int(plans_revision)))

    def choose_folder(self) -> dict[str, Any]:
        def choose() -> dict[str, Any]:
            if self._window is None:
                raise RuntimeError("窗口尚未准备好。")
            import webview

            current = self._service.current_folder()
            result = self._window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=str(current or Path.home()),
            )
            if not result:
                return {"cancelled": True}
            selected = result[0] if isinstance(result, (tuple, list)) else result
            return {"cancelled": False, "state": self._service.set_folder(str(selected))}

        return self._response(choose)

    def create_folder(self, name: str) -> dict[str, Any]:
        def create() -> dict[str, Any]:
            if self._window is None:
                raise RuntimeError("窗口尚未准备好。")
            import webview

            clean_name = collapse_spaces(name)
            if not clean_name:
                raise ValueError("新目录名称不能为空。")
            folder_name = safe_folder_name(clean_name)
            result = self._window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=str(self._service.current_folder() or Path.home()),
            )
            if not result:
                return {"cancelled": True}
            parent_value = result[0] if isinstance(result, (tuple, list)) else result
            new_folder = Path(str(parent_value)) / folder_name
            new_folder.mkdir(parents=False, exist_ok=False)
            return {"cancelled": False, "state": self._service.set_folder(str(new_folder))}

        return self._response(create)

    def set_folder(self, value: str) -> dict[str, Any]:
        return self._response(lambda: self._service.set_folder(value))

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._response(lambda: self._service.save_settings(payload))

    def start_scan(self) -> dict[str, Any]:
        return self._response(self._service.start_scan)

    def cancel_operation(self) -> dict[str, Any]:
        return self._response(self._service.cancel_operation)

    def start_apply(self) -> dict[str, Any]:
        return self._response(self._service.start_apply)

    def start_undo(self) -> dict[str, Any]:
        return self._response(self._service.start_undo)

    def edit_plan(self, index: int, series_name: str) -> dict[str, Any]:
        return self._response(lambda: self._service.edit_plan(int(index), series_name))

    def get_detail(self, index: int) -> dict[str, Any]:
        return self._response(lambda: self._service.get_detail(int(index)))

    def get_report(self) -> dict[str, Any]:
        return self._response(self._service.report_summary)

    def open_folder(self) -> dict[str, Any]:
        def open_current() -> bool:
            folder = self._service.current_folder()
            if folder is None:
                raise FileNotFoundError("尚未选择目录。")
            _open_path(folder)
            return True

        return self._response(open_current)

    def open_report(self) -> dict[str, Any]:
        def open_current() -> bool:
            report = self._service.current_report()
            if report is None:
                raise FileNotFoundError("当前目录没有分类报告。")
            _open_path(report)
            return True

        return self._response(open_current)

    def reveal_plan(self, index: int) -> dict[str, Any]:
        def reveal() -> bool:
            path = self._service.plan_path(int(index))
            _open_path(path.parent)
            return True

        return self._response(reveal)

    def open_subject(self, url: str) -> dict[str, Any]:
        def open_url() -> bool:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("详情链接无效。")
            if not webbrowser.open(url):
                raise OSError("系统未能打开浏览器。")
            return True

        return self._response(open_url)


def launch_desktop() -> None:
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError("缺少桌面界面依赖，请运行 run.bat 自动安装运行环境。") from exc

    service = ApplicationService()
    bridge = DesktopBridge(service)
    window = webview.create_window(
        f"{APP_NAME} {APP_VERSION}",
        url=str(_resource_root() / "index.html"),
        js_api=bridge,
        width=1440,
        height=900,
        min_size=(1080, 700),
        background_color="#101114",
        text_select=True,
        zoomable=False,
    )
    bridge._attach_window(window)

    def on_closing() -> bool:
        if service.is_critical_operation():
            try:
                window.run_js("window.LightNovelApp && window.LightNovelApp.notifyCriticalClose()")
            except Exception:
                pass
            return False
        if service.is_operation_running():
            service.cancel_operation()
        return True

    window.events.closing += on_closing
    if os.environ.get("LN_SELECTOR_SMOKE_TEST") == "1":
        window.events.loaded += lambda: threading.Timer(2.0, window.destroy).start()
    gui = "edgechromium" if os.name == "nt" else None
    webview.start(gui=gui, debug=os.environ.get("LN_SELECTOR_DEBUG") == "1")
