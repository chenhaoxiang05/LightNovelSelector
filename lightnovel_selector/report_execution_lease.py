from __future__ import annotations

import ctypes
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .classification_safety import _absolute_path_without_link_resolution

_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_WAIT_TIMEOUT = 0x00000102
_WAIT_FAILED = 0xFFFFFFFF

_CREATE_MUTEX_W: Any = None
_WAIT_FOR_SINGLE_OBJECT: Any = None
_RELEASE_MUTEX: Any = None
_CLOSE_HANDLE: Any = None

if os.name == "nt":
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    _CREATE_MUTEX_W = _KERNEL32.CreateMutexW
    _CREATE_MUTEX_W.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    _CREATE_MUTEX_W.restype = wintypes.HANDLE
    _WAIT_FOR_SINGLE_OBJECT = _KERNEL32.WaitForSingleObject
    _WAIT_FOR_SINGLE_OBJECT.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _WAIT_FOR_SINGLE_OBJECT.restype = wintypes.DWORD
    _RELEASE_MUTEX = _KERNEL32.ReleaseMutex
    _RELEASE_MUTEX.argtypes = (wintypes.HANDLE,)
    _RELEASE_MUTEX.restype = wintypes.BOOL
    _CLOSE_HANDLE = _KERNEL32.CloseHandle
    _CLOSE_HANDLE.argtypes = (wintypes.HANDLE,)
    _CLOSE_HANDLE.restype = wintypes.BOOL


def _report_mutex_name(report_path: Path) -> str:
    canonical_path = _absolute_path_without_link_resolution(report_path)
    normalized_path = os.path.normcase(str(canonical_path))
    digest = hashlib.sha256(normalized_path.encode("utf-8", errors="surrogatepass")).hexdigest()
    return f"Local\\LightNovelSelector.ReportExecution.{digest}"


def _windows_mutex_error(message: str, *, error_code: int | None = None) -> OSError:
    error_code = ctypes.get_last_error() if error_code is None else error_code
    return OSError(error_code, message)


@dataclass(slots=True)
class ReportExecutionLease:
    _handle: int | None
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._handle is None:
            return
        _RELEASE_MUTEX(self._handle)
        _CLOSE_HANDLE(self._handle)


def try_acquire_report_execution_lease(report_path: Path) -> ReportExecutionLease | None:
    if _CREATE_MUTEX_W is None:
        return ReportExecutionLease(_handle=None)

    handle = _CREATE_MUTEX_W(None, False, _report_mutex_name(report_path))
    if not handle:
        raise _windows_mutex_error("无法创建分类报告的跨进程互斥体。")
    wait_result = int(_WAIT_FOR_SINGLE_OBJECT(handle, 0))
    if wait_result in {_WAIT_OBJECT_0, _WAIT_ABANDONED}:
        return ReportExecutionLease(_handle=int(handle))

    wait_error = ctypes.get_last_error() if wait_result == _WAIT_FAILED else None
    _CLOSE_HANDLE(handle)
    if wait_result == _WAIT_TIMEOUT:
        return None
    if wait_result == _WAIT_FAILED:
        raise _windows_mutex_error("无法检查分类报告的跨进程互斥体。", error_code=wait_error)
    raise OSError(f"分类报告的跨进程互斥体返回未知状态：{wait_result}。")


def report_execution_lease_is_active(report_path: Path) -> bool:
    lease = try_acquire_report_execution_lease(report_path)
    if lease is None:
        return True
    lease.release()
    return False
