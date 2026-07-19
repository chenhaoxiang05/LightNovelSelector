from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .constants import METADATA_CACHE_TTL_SECONDS, METADATA_CACHE_VERSION, SETTINGS_FILE_NAME
from .models import AppSettings, BookMetadata, CustomRule, ResolveResult
from .parsing import collapse_spaces


def book_metadata_to_dict(metadata: BookMetadata) -> dict:
    return {
        "title": metadata.title,
        "source": metadata.source,
        "confidence": metadata.confidence,
        "query": metadata.query,
        "summary": metadata.summary,
        "cover_url": metadata.cover_url,
        "url": metadata.url,
    }


def book_metadata_from_dict(data: dict) -> BookMetadata | None:
    try:
        return BookMetadata(
            title=str(data["title"]),
            source=str(data.get("source") or "Bangumi"),
            confidence=float(data.get("confidence") or 0.0),
            query=str(data.get("query") or data["title"]),
            summary=data.get("summary"),
            cover_url=data.get("cover_url"),
            url=data.get("url"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def resolve_result_to_dict(result: ResolveResult) -> dict:
    return {
        "series_name": result.series_name,
        "source": result.source,
        "confidence": result.confidence,
        "local_guess": result.local_guess,
        "metadata_title": result.metadata_title,
        "metadata_summary": result.metadata_summary,
        "metadata_cover_url": result.metadata_cover_url,
        "metadata_url": result.metadata_url,
    }


def resolve_result_from_dict(data: dict) -> ResolveResult | None:
    try:
        return ResolveResult(
            series_name=str(data["series_name"]),
            source=str(data.get("source") or "缓存"),
            confidence=float(data.get("confidence") or 0.0),
            local_guess=str(data.get("local_guess") or data["series_name"]),
            metadata_title=data.get("metadata_title"),
            metadata_summary=data.get("metadata_summary"),
            metadata_cover_url=data.get("metadata_cover_url"),
            metadata_url=data.get("metadata_url"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def metadata_cache_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        root = Path(base) / "LightNovelSelector"
    else:
        root = Path.home() / ".lightnovel_selector"
    return root / "metadata_cache.json"


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "LightNovelSelector"
    return Path.home() / ".lightnovel_selector"


def settings_path() -> Path:
    return app_data_dir() / SETTINGS_FILE_NAME


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def app_settings_from_dict(data: dict) -> AppSettings:
    rules = []
    for item in data.get("custom_rules") or []:
        if not isinstance(item, dict):
            continue
        pattern = collapse_spaces(str(item.get("pattern") or ""))
        series = collapse_spaces(str(item.get("series") or ""))
        if pattern and series:
            rules.append(CustomRule(pattern=pattern, series=series))
    return AppSettings(
        use_network=bool(data.get("use_network", True)),
        recursive=bool(data.get("recursive", False)),
        auto_rename=bool(data.get("auto_rename", False)),
        custom_rules=tuple(rules),
        last_folder=str(data.get("last_folder") or ""),
    )


def app_settings_to_dict(settings: AppSettings) -> dict:
    return {
        "use_network": settings.use_network,
        "recursive": settings.recursive,
        "auto_rename": settings.auto_rename,
        "last_folder": settings.last_folder,
        "custom_rules": [
            {"pattern": rule.pattern, "series": rule.series}
            for rule in settings.custom_rules
        ],
    }


def load_app_settings(path: Path | None = None) -> AppSettings:
    path = path or settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()
    if not isinstance(raw, dict):
        return AppSettings()
    return app_settings_from_dict(raw)


def save_app_settings(settings: AppSettings, path: Path | None = None) -> None:
    path = path or settings_path()
    write_json_atomic(path, app_settings_to_dict(settings))


def try_save_app_settings(settings: AppSettings, path: Path | None = None) -> OSError | None:
    try:
        save_app_settings(settings, path)
    except OSError as exc:
        return exc
    return None


class PersistentMetadataCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or metadata_cache_path()
        self.lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        if raw.get("version") != METADATA_CACHE_VERSION:
            return {"version": METADATA_CACHE_VERSION, "entries": {}}
        entries = raw.get("entries")
        if not isinstance(entries, dict):
            entries = {}
        return {"version": METADATA_CACHE_VERSION, "entries": entries}

    def _save(self) -> None:
        try:
            write_json_atomic(self.path, self.data)
        except OSError:
            pass

    def get(self, key: str) -> dict | None:
        with self.lock:
            entry = self.data.get("entries", {}).get(key)
            if not isinstance(entry, dict):
                return None
            try:
                cached_at = float(entry.get("cached_at") or 0)
            except (TypeError, ValueError):
                self.data["entries"].pop(key, None)
                self._save()
                return None
            if time.time() - cached_at > METADATA_CACHE_TTL_SECONDS:
                self.data["entries"].pop(key, None)
                self._save()
                return None
            payload = entry.get("payload")
            return payload if isinstance(payload, dict) else None

    def set(self, key: str, payload: dict) -> None:
        with self.lock:
            self.data.setdefault("entries", {})[key] = {
                "cached_at": time.time(),
                "payload": payload,
            }
            self._save()


_PERSISTENT_METADATA_CACHE: PersistentMetadataCache | None = None
_PERSISTENT_METADATA_CACHE_LOCK = threading.Lock()


def get_persistent_metadata_cache() -> PersistentMetadataCache:
    global _PERSISTENT_METADATA_CACHE
    with _PERSISTENT_METADATA_CACHE_LOCK:
        if _PERSISTENT_METADATA_CACHE is None:
            _PERSISTENT_METADATA_CACHE = PersistentMetadataCache()
        return _PERSISTENT_METADATA_CACHE
