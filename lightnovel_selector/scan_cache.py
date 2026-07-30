from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, cast

from .constants import (
    METADATA_TEXT_MAX_CHARS,
    SCAN_CACHE_FILE_NAME,
    SCAN_CACHE_MAX_BYTES,
    SCAN_CACHE_MAX_ENTRIES,
    SCAN_CACHE_VERSION,
)
from .models import BookIdentity
from .storage import (
    app_data_dir,
    book_identity_from_dict,
    book_identity_to_dict,
    read_json_bounded,
    write_json_atomic,
)

_GET_FILE_INFORMATION_BY_HANDLE_EX: Any = None

if os.name == "nt":
    import msvcrt
    from ctypes import wintypes

    class _WindowsFileBasicInfo(ctypes.Structure):
        _fields_ = [
            ("CreationTime", ctypes.c_longlong),
            ("LastAccessTime", ctypes.c_longlong),
            ("LastWriteTime", ctypes.c_longlong),
            ("ChangeTime", ctypes.c_longlong),
            ("FileAttributes", wintypes.DWORD),
        ]

    class _WindowsFileId128(ctypes.Structure):
        _fields_ = [("Identifier", ctypes.c_ubyte * 16)]

    class _WindowsFileIdInfo(ctypes.Structure):
        _fields_ = [
            ("VolumeSerialNumber", ctypes.c_ulonglong),
            ("FileId", _WindowsFileId128),
        ]

    _GET_FILE_INFORMATION_BY_HANDLE_EX = ctypes.WinDLL(  # type: ignore[attr-defined]
        "kernel32",
        use_last_error=True,
    ).GetFileInformationByHandleEx
    _GET_FILE_INFORMATION_BY_HANDLE_EX.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _GET_FILE_INFORMATION_BY_HANDLE_EX.restype = wintypes.BOOL


@dataclass(frozen=True)
class FileSnapshot:
    size: int
    mtime_ns: int
    change_token: int | None
    device: int
    inode: int

    @property
    def cacheable(self) -> bool:
        return self.change_token is not None

    def to_dict(self) -> dict[str, int | None]:
        return {
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "change_token": self.change_token,
            "device": self.device,
            "inode": self.inode,
        }

    @classmethod
    def from_dict(cls, value: object) -> FileSnapshot | None:
        if not isinstance(value, dict):
            return None
        fields: dict[str, int | None] = {}
        for name in ("size", "mtime_ns", "change_token", "device", "inode"):
            item = value.get(name)
            if name == "change_token" and item is None:
                fields[name] = None
                continue
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                return None
            fields[name] = item
        return cls(
            size=int(fields["size"] or 0),
            mtime_ns=int(fields["mtime_ns"] or 0),
            change_token=fields["change_token"],
            device=int(fields["device"] or 0),
            inode=int(fields["inode"] or 0),
        )


@dataclass(frozen=True)
class LocalFileAnalysis:
    identity: BookIdentity
    identity_query: str
    used_content_hint: bool


@dataclass(frozen=True)
class ScanCacheStats:
    entries: int = 0
    reused_files: int = 0
    updated_files: int = 0
    invalidated_files: int = 0
    quick_signature_hits: int = 0
    fingerprint_hits: int = 0
    local_analysis_hits: int = 0
    uncacheable_files: int = 0
    write_warning: str | None = None

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "entries": self.entries,
            "reused_files": self.reused_files,
            "updated_files": self.updated_files,
            "invalidated_files": self.invalidated_files,
            "quick_signature_hits": self.quick_signature_hits,
            "fingerprint_hits": self.fingerprint_hits,
            "local_analysis_hits": self.local_analysis_hits,
            "uncacheable_files": self.uncacheable_files,
            "write_warning": self.write_warning,
        }


def scan_cache_path() -> Path:
    return app_data_dir() / SCAN_CACHE_FILE_NAME


def _windows_change_token(file_descriptor: int) -> int | None:
    if os.name != "nt" or _GET_FILE_INFORMATION_BY_HANDLE_EX is None:
        return None
    try:
        info = _WindowsFileBasicInfo()
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(file_descriptor))
        succeeded = _GET_FILE_INFORMATION_BY_HANDLE_EX(
            handle,
            0,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
    except (OSError, ValueError):
        return None
    return int(info.ChangeTime) if succeeded and info.ChangeTime > 0 else None


def _windows_file_identity(file_descriptor: int) -> tuple[int, int] | None:
    if os.name != "nt" or _GET_FILE_INFORMATION_BY_HANDLE_EX is None:
        return None
    try:
        info = _WindowsFileIdInfo()
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(file_descriptor))
        succeeded = _GET_FILE_INFORMATION_BY_HANDLE_EX(
            handle,
            18,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
    except (OSError, ValueError):
        return None
    if not succeeded:
        return None
    file_id = int.from_bytes(bytes(info.FileId.Identifier), byteorder="little")
    volume_serial = int(info.VolumeSerialNumber)
    if file_id <= 0 or volume_serial <= 0:
        return None
    return volume_serial, file_id


def capture_open_file_snapshot(handle: BinaryIO) -> FileSnapshot:
    stat = os.fstat(handle.fileno())
    if os.name == "nt":
        change_token = _windows_change_token(handle.fileno())
        file_identity = _windows_file_identity(handle.fileno())
        device, inode = file_identity or (0, 0)
    else:
        change_token = stat.st_ctime_ns
        device, inode = stat.st_dev, stat.st_ino
    return FileSnapshot(
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        change_token=change_token,
        device=device,
        inode=inode,
    )


def capture_file_snapshot(path: Path) -> FileSnapshot:
    with path.open("rb") as handle:
        return capture_open_file_snapshot(handle)


def _is_hex_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _valid_fingerprint(value: object, *, size: int) -> bool:
    if not isinstance(value, str):
        return False
    prefix, separator, digest = value.partition(":")
    return separator == ":" and prefix == str(size) and _is_hex_digest(digest)


def _valid_entry_key(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 160:
        return False
    if value.startswith("file:"):
        parts = value.split(":")
        return (
            len(parts) == 3
            and bool(parts[1])
            and bool(parts[2])
            and all(character in "0123456789abcdef" for part in parts[1:] for character in part)
        )
    return value.startswith("path:") and _is_hex_digest(value[5:])


def _entry_key(path: Path, snapshot: FileSnapshot) -> str:
    if snapshot.inode > 0:
        return f"file:{snapshot.device:x}:{snapshot.inode:x}"
    normalized = os.path.normcase(os.path.abspath(path))
    digest = hashlib.sha256(os.fsencode(normalized)).hexdigest()
    return f"path:{digest}"


class PersistentScanCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or scan_cache_path()
        self._lock = threading.RLock()
        self._dirty = False
        self._entries = self._load()
        self._loaded_quick_keys = {key for key, entry in self._entries.items() if "quick_signature" in entry}
        self._loaded_fingerprint_keys = {key for key, entry in self._entries.items() if "fingerprint" in entry}
        self._loaded_analysis_keys = {key for key, entry in self._entries.items() if "identity" in entry}
        self._reused_keys: set[str] = set()
        self._updated_keys: set[str] = set()
        self._invalidated_keys: set[str] = set()
        self._quick_hit_keys: set[str] = set()
        self._fingerprint_hit_keys: set[str] = set()
        self._analysis_hit_keys: set[str] = set()
        self._uncacheable_keys: set[str] = set()
        self.last_save_error: OSError | None = None

    def __enter__(self) -> PersistentScanCache:  # noqa: PYI034
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.flush()

    @staticmethod
    def _sanitized_entry(value: object) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        snapshot = FileSnapshot.from_dict(value.get("snapshot"))
        if snapshot is None or not snapshot.cacheable:
            return None
        last_used_at = value.get("last_used_at")
        if (
            isinstance(last_used_at, bool)
            or not isinstance(last_used_at, (int, float))
            or not math.isfinite(float(last_used_at))
            or float(last_used_at) <= 0
        ):
            return None
        result: dict[str, object] = {
            "snapshot": snapshot.to_dict(),
            "last_used_at": float(last_used_at),
        }
        quick_signature = value.get("quick_signature")
        if _valid_fingerprint(quick_signature, size=snapshot.size):
            result["quick_signature"] = quick_signature
        fingerprint = value.get("fingerprint")
        if _valid_fingerprint(fingerprint, size=snapshot.size):
            result["fingerprint"] = fingerprint

        identity = book_identity_from_dict(value.get("identity"))
        analysis_name = value.get("analysis_name")
        identity_query = value.get("identity_query")
        used_content_hint = value.get("used_content_hint")
        if (
            identity is not None
            and isinstance(analysis_name, str)
            and 0 < len(analysis_name) <= METADATA_TEXT_MAX_CHARS
            and "/" not in analysis_name
            and "\\" not in analysis_name
            and isinstance(identity_query, str)
            and 0 < len(identity_query) <= METADATA_TEXT_MAX_CHARS
            and isinstance(used_content_hint, bool)
        ):
            result.update(
                {
                    "analysis_name": analysis_name,
                    "identity": book_identity_to_dict(identity),
                    "identity_query": identity_query,
                    "used_content_hint": used_content_hint,
                }
            )
        if len(result) == 2:
            return None
        return result

    def _load(self) -> dict[str, dict[str, object]]:
        raw = read_json_bounded(self.path, max_bytes=SCAN_CACHE_MAX_BYTES)
        if not isinstance(raw, dict) or raw.get("version") != SCAN_CACHE_VERSION:
            return {}
        entries = raw.get("entries")
        if not isinstance(entries, dict):
            return {}
        valid: list[tuple[str, dict[str, object], float]] = []
        for key, value in entries.items():
            if not _valid_entry_key(key):
                continue
            entry = self._sanitized_entry(value)
            if entry is None:
                continue
            valid.append((key, entry, float(cast(int | float, entry["last_used_at"]))))
        valid.sort(key=lambda item: item[2], reverse=True)
        trimmed = valid[:SCAN_CACHE_MAX_ENTRIES]
        if len(trimmed) != len(entries):
            self._dirty = True
        return {key: entry for key, entry, _ in trimmed}

    def _mark_uncacheable(self, path: Path) -> None:
        normalized = os.path.normcase(os.path.abspath(path))
        self._uncacheable_keys.add(hashlib.sha256(os.fsencode(normalized)).hexdigest())

    def _matching_entry(
        self,
        path: Path,
        snapshot: FileSnapshot,
    ) -> tuple[str, dict[str, object]] | None:
        if not snapshot.cacheable:
            self._mark_uncacheable(path)
            return None
        key = _entry_key(path, snapshot)
        entry = self._entries.get(key)
        if entry is None:
            return None
        cached_snapshot = FileSnapshot.from_dict(entry.get("snapshot"))
        if entry is None or cached_snapshot != snapshot:
            self._entries.pop(key, None)
            self._loaded_quick_keys.discard(key)
            self._loaded_fingerprint_keys.discard(key)
            self._loaded_analysis_keys.discard(key)
            self._invalidated_keys.add(key)
            self._dirty = True
            return None
        entry["last_used_at"] = time.time()
        self._dirty = True
        return key, entry

    def _entry_for_update(self, path: Path, snapshot: FileSnapshot) -> tuple[str, dict[str, object]] | None:
        if not snapshot.cacheable:
            self._mark_uncacheable(path)
            return None
        key = _entry_key(path, snapshot)
        entry = self._entries.get(key)
        cached_snapshot = FileSnapshot.from_dict(entry.get("snapshot")) if entry is not None else None
        if entry is None or cached_snapshot != snapshot:
            entry = {
                "snapshot": snapshot.to_dict(),
                "last_used_at": time.time(),
            }
            self._entries[key] = entry
            self._loaded_quick_keys.discard(key)
            self._loaded_fingerprint_keys.discard(key)
            self._loaded_analysis_keys.discard(key)
        else:
            entry["last_used_at"] = time.time()
        active_entry = cast(dict[str, object], entry)
        self._updated_keys.add(key)
        self._dirty = True
        return key, active_entry

    def get_quick_signature(self, path: Path, snapshot: FileSnapshot) -> str | None:
        with self._lock:
            matched = self._matching_entry(path, snapshot)
            if matched is None:
                return None
            key, entry = matched
            value = entry.get("quick_signature")
            if not _valid_fingerprint(value, size=snapshot.size):
                return None
            if key in self._loaded_quick_keys:
                self._quick_hit_keys.add(key)
                self._reused_keys.add(key)
            return str(value)

    def remember_quick_signature(self, path: Path, snapshot: FileSnapshot, value: str) -> None:
        if not _valid_fingerprint(value, size=snapshot.size):
            raise ValueError("快速签名格式无效。")
        with self._lock:
            updated = self._entry_for_update(path, snapshot)
            if updated is not None:
                _, entry = updated
                entry["quick_signature"] = value

    def get_fingerprint(self, path: Path, snapshot: FileSnapshot) -> str | None:
        with self._lock:
            matched = self._matching_entry(path, snapshot)
            if matched is None:
                return None
            key, entry = matched
            value = entry.get("fingerprint")
            if not _valid_fingerprint(value, size=snapshot.size):
                return None
            if key in self._loaded_fingerprint_keys:
                self._fingerprint_hit_keys.add(key)
                self._reused_keys.add(key)
            return str(value)

    def remember_fingerprint(self, path: Path, snapshot: FileSnapshot, value: str) -> None:
        if not _valid_fingerprint(value, size=snapshot.size):
            raise ValueError("完整文件指纹格式无效。")
        with self._lock:
            updated = self._entry_for_update(path, snapshot)
            if updated is not None:
                _, entry = updated
                entry["fingerprint"] = value

    def get_local_analysis(self, path: Path, snapshot: FileSnapshot) -> LocalFileAnalysis | None:
        with self._lock:
            matched = self._matching_entry(path, snapshot)
            if matched is None:
                return None
            key, entry = matched
            if entry.get("analysis_name") != path.name:
                return None
            identity = book_identity_from_dict(entry.get("identity"))
            identity_query = entry.get("identity_query")
            used_content_hint = entry.get("used_content_hint")
            if (
                identity is None
                or not isinstance(identity_query, str)
                or not identity_query
                or not isinstance(used_content_hint, bool)
            ):
                return None
            if key in self._loaded_analysis_keys:
                self._analysis_hit_keys.add(key)
                self._reused_keys.add(key)
            return LocalFileAnalysis(
                identity=identity,
                identity_query=identity_query,
                used_content_hint=used_content_hint,
            )

    def remember_local_analysis(
        self,
        path: Path,
        snapshot: FileSnapshot,
        analysis: LocalFileAnalysis,
    ) -> None:
        if not analysis.identity_query or len(analysis.identity_query) > METADATA_TEXT_MAX_CHARS:
            raise ValueError("本地识别查询格式无效。")
        with self._lock:
            updated = self._entry_for_update(path, snapshot)
            if updated is not None:
                _, entry = updated
                entry.update(
                    {
                        "analysis_name": path.name,
                        "identity": book_identity_to_dict(analysis.identity),
                        "identity_query": analysis.identity_query,
                        "used_content_hint": analysis.used_content_hint,
                    }
                )

    def _payload_for_save(self) -> dict[str, object]:
        ordered = sorted(
            self._entries.items(),
            key=lambda item: float(cast(int | float, item[1].get("last_used_at") or 0)),
            reverse=True,
        )[:SCAN_CACHE_MAX_ENTRIES]

        def payload(count: int) -> dict[str, object]:
            return {
                "version": SCAN_CACHE_VERSION,
                "entries": dict(ordered[:count]),
            }

        def encoded_size(value: dict[str, object]) -> int:
            return len((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

        if encoded_size(payload(len(ordered))) <= SCAN_CACHE_MAX_BYTES:
            return payload(len(ordered))
        low = 0
        high = len(ordered)
        while low < high:
            middle = (low + high + 1) // 2
            if encoded_size(payload(middle)) <= SCAN_CACHE_MAX_BYTES:
                low = middle
            else:
                high = middle - 1
        return payload(low)

    def flush(self) -> OSError | None:
        with self._lock:
            if not self._dirty:
                return self.last_save_error
            payload = self._payload_for_save()
            try:
                write_json_atomic(self.path, payload)
            except OSError as exc:
                self.last_save_error = exc
                return exc
            entries = payload.get("entries")
            self._entries = dict(entries) if isinstance(entries, dict) else {}
            self._dirty = False
            self.last_save_error = None
            return None

    @property
    def stats(self) -> ScanCacheStats:
        with self._lock:
            return ScanCacheStats(
                entries=len(self._entries),
                reused_files=len(self._reused_keys),
                updated_files=len(self._updated_keys),
                invalidated_files=len(self._invalidated_keys),
                quick_signature_hits=len(self._quick_hit_keys),
                fingerprint_hits=len(self._fingerprint_hit_keys),
                local_analysis_hits=len(self._analysis_hit_keys),
                uncacheable_files=len(self._uncacheable_keys),
                write_warning=str(self.last_save_error)[:2000] if self.last_save_error else None,
            )
