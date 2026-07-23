from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import Any, TextIO

from .application import ApplicationService
from .constants import APP_NAME, APP_VERSION


PROTOCOL_VERSION = 1
MAX_REQUEST_CHARS = 1024 * 1024


class ProtocolError(ValueError):
    pass


class SidecarServer:
    """Expose ApplicationService through a line-delimited JSON protocol."""

    def __init__(
        self,
        service: ApplicationService | None = None,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ) -> None:
        self._service = service or ApplicationService()
        self._input = input_stream or sys.stdin
        self._output = output_stream or sys.stdout
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "ping": self._ping,
            "bootstrap": lambda params: self._service.snapshot(),
            "poll": self._poll,
            "set_folder": self._set_folder,
            "save_settings": self._save_settings,
            "start_scan": lambda params: self._service.start_scan(),
            "cancel_operation": lambda params: self._service.cancel_operation(),
            "start_apply": lambda params: self._service.start_apply(),
            "start_undo": lambda params: self._service.start_undo(),
            "edit_plan": self._edit_plan,
            "get_detail": self._get_detail,
            "get_report": lambda params: self._service.report_summary(),
        }

    @staticmethod
    def _ping(params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "process_id": os.getpid(),
        }

    def _poll(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._service.snapshot(
            log_cursor=self._integer(params, "log_cursor", default=0),
            plans_revision=self._integer(params, "plans_revision", default=-1),
        )

    def _set_folder(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._service.set_folder(self._string(params, "path"))

    def _save_settings(self, params: dict[str, Any]) -> dict[str, Any]:
        settings = params.get("settings")
        if not isinstance(settings, dict):
            raise ProtocolError("settings 必须是 JSON 对象。")
        return self._service.save_settings(settings)

    def _edit_plan(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._service.edit_plan(
            self._integer(params, "index"),
            self._string(params, "series_name"),
        )

    def _get_detail(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._service.get_detail(self._integer(params, "index"))

    @staticmethod
    def _integer(params: dict[str, Any], name: str, *, default: int | None = None) -> int:
        if name not in params:
            if default is not None:
                return default
            raise ProtocolError(f"缺少参数：{name}")
        value = params[name]
        if isinstance(value, bool):
            raise ProtocolError(f"参数 {name} 必须是整数。")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ProtocolError(f"参数 {name} 必须是整数。") from exc

    @staticmethod
    def _string(params: dict[str, Any], name: str) -> str:
        value = params.get(name)
        if not isinstance(value, str):
            raise ProtocolError(f"参数 {name} 必须是字符串。")
        return value

    def _dispatch(self, request: Any) -> tuple[dict[str, Any], bool]:
        if not isinstance(request, dict):
            raise ProtocolError("请求必须是 JSON 对象。")

        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(method, str) or not method:
            raise ProtocolError("method 必须是非空字符串。")
        if not isinstance(params, dict):
            raise ProtocolError("params 必须是 JSON 对象。")

        if method == "shutdown":
            return {"id": request_id, "ok": True, "result": {"accepted": True}}, True

        handler = self._handlers.get(method)
        if handler is None:
            raise ProtocolError(f"不支持的方法：{method}")
        return {"id": request_id, "ok": True, "result": handler(params)}, False

    @staticmethod
    def _error_response(request_id: Any, exc: Exception) -> dict[str, Any]:
        return {
            "id": request_id,
            "ok": False,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc) or type(exc).__name__,
            },
        }

    def _write(self, response: dict[str, Any]) -> None:
        self._output.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n")
        self._output.flush()

    def serve_forever(self) -> int:
        while True:
            raw_line = self._input.readline(MAX_REQUEST_CHARS + 2)
            if not raw_line:
                break
            if not raw_line.strip():
                continue

            request_id: Any = None
            try:
                if len(raw_line) > MAX_REQUEST_CHARS:
                    while raw_line and not raw_line.endswith("\n"):
                        raw_line = self._input.readline(MAX_REQUEST_CHARS + 2)
                    raise ProtocolError("请求超过允许大小。")
                request = json.loads(raw_line)
                if isinstance(request, dict):
                    request_id = request.get("id")
                response, should_stop = self._dispatch(request)
            except (json.JSONDecodeError, ProtocolError, OSError, RuntimeError, ValueError, TypeError, IndexError) as exc:
                response = self._error_response(request_id, exc)
                should_stop = False
            except Exception as exc:
                response = self._error_response(request_id, exc)
                should_stop = False

            self._write(response)
            if should_stop:
                return 0
        return 0


def configure_sidecar_stdio() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict", line_buffering=True, write_through=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True, write_through=True)


def main() -> int:
    configure_sidecar_stdio()
    try:
        return SidecarServer().serve_forever()
    except Exception as exc:
        print(f"Sidecar 启动失败：{exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
