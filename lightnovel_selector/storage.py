from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from pathlib import Path

from .constants import (
    CUSTOM_RULE_MAX_COUNT,
    CUSTOM_RULE_PATTERN_MAX_CHARS,
    LOCAL_PATH_MAX_CHARS,
    METADATA_CACHE_MAX_BYTES,
    METADATA_CACHE_MAX_ENTRIES,
    METADATA_CACHE_TTL_SECONDS,
    METADATA_CACHE_VERSION,
    METADATA_SUMMARY_MAX_CHARS,
    METADATA_TEXT_MAX_CHARS,
    REMOTE_URL_MAX_CHARS,
    SERIES_NAME_MAX_CHARS,
    SETTINGS_FILE_NAME,
    SETTINGS_MAX_BYTES,
)
from .models import AppSettings, BookMetadata, CustomRule, ResolveResult
from .parsing import collapse_spaces


def _required_text(value: object, *, max_chars: int) -> str:
    if not isinstance(value, str):
        raise TypeError("字段必须是字符串。")
    text = collapse_spaces(value)[:max_chars]
    if not text:
        raise ValueError("字段不能为空。")
    return text


def _optional_text(value: object, *, max_chars: int, preserve_lines: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip() if preserve_lines else collapse_spaces(value)
    return text[:max_chars] or None


def _confidence(value: object) -> float:
    if isinstance(value, bool):
        raise TypeError("置信度不能是布尔值。")
    if not isinstance(value, (int, float, str)):
        raise TypeError("置信度必须是数值。")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("置信度必须是有限数值。")
    return max(0.0, min(result, 1.0))


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
            title=_required_text(data["title"], max_chars=METADATA_TEXT_MAX_CHARS),
            source=_required_text(data.get("source") or "Bangumi", max_chars=80),
            confidence=_confidence(data.get("confidence") or 0.0),
            query=_required_text(data.get("query") or data["title"], max_chars=METADATA_TEXT_MAX_CHARS),
            summary=_optional_text(
                data.get("summary"),
                max_chars=METADATA_SUMMARY_MAX_CHARS,
                preserve_lines=True,
            ),
            cover_url=_optional_text(data.get("cover_url"), max_chars=REMOTE_URL_MAX_CHARS),
            url=_optional_text(data.get("url"), max_chars=REMOTE_URL_MAX_CHARS),
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
            series_name=_required_text(data["series_name"], max_chars=SERIES_NAME_MAX_CHARS),
            source=_required_text(data.get("source") or "缓存", max_chars=80),
            confidence=_confidence(data.get("confidence") or 0.0),
            local_guess=_required_text(
                data.get("local_guess") or data["series_name"],
                max_chars=METADATA_TEXT_MAX_CHARS,
            ),
            metadata_title=_optional_text(data.get("metadata_title"), max_chars=METADATA_TEXT_MAX_CHARS),
            metadata_summary=_optional_text(
                data.get("metadata_summary"),
                max_chars=METADATA_SUMMARY_MAX_CHARS,
                preserve_lines=True,
            ),
            metadata_cover_url=_optional_text(
                data.get("metadata_cover_url"),
                max_chars=REMOTE_URL_MAX_CHARS,
            ),
            metadata_url=_optional_text(data.get("metadata_url"), max_chars=REMOTE_URL_MAX_CHARS),
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


def read_json_bounded(path: Path, *, max_bytes: int) -> object | None:
    if max_bytes < 1:
        raise ValueError("max_bytes 必须大于 0。")
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            return None
        return json.loads(data.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        return None


def settings_path() -> Path:
    return app_data_dir() / SETTINGS_FILE_NAME


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def app_settings_from_dict(data: dict) -> AppSettings:
    rules = []
    raw_rules = data.get("custom_rules")
    if not isinstance(raw_rules, list):
        raw_rules = []
    for item in raw_rules[:CUSTOM_RULE_MAX_COUNT]:
        if not isinstance(item, dict):
            continue
        pattern_value = item.get("pattern")
        series_value = item.get("series")
        if not isinstance(pattern_value, str) or not isinstance(series_value, str):
            continue
        pattern = collapse_spaces(pattern_value)
        series = collapse_spaces(series_value)
        if (
            pattern
            and series
            and len(pattern) <= CUSTOM_RULE_PATTERN_MAX_CHARS
            and len(series) <= SERIES_NAME_MAX_CHARS
        ):
            rules.append(CustomRule(pattern=pattern, series=series))
    last_folder = data.get("last_folder")
    use_network = data.get("use_network")
    recursive = data.get("recursive")
    auto_rename = data.get("auto_rename")
    return AppSettings(
        use_network=use_network if isinstance(use_network, bool) else True,
        recursive=recursive if isinstance(recursive, bool) else False,
        auto_rename=auto_rename if isinstance(auto_rename, bool) else False,
        custom_rules=tuple(rules),
        last_folder=(
            last_folder
            if isinstance(last_folder, str) and len(last_folder) <= LOCAL_PATH_MAX_CHARS
            else ""
        ),
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
    raw = read_json_bounded(path, max_bytes=SETTINGS_MAX_BYTES)
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
        raw = read_json_bounded(self.path, max_bytes=METADATA_CACHE_MAX_BYTES)
        if not isinstance(raw, dict):
            raw = {}
        if raw.get("version") != METADATA_CACHE_VERSION:
            return {"version": METADATA_CACHE_VERSION, "entries": {}}
        entries = raw.get("entries")
        if not isinstance(entries, dict):
            entries = {}
        return {"version": METADATA_CACHE_VERSION, "entries": self._prune_entries(entries)}

    @staticmethod
    def _prune_entries(entries: dict) -> dict:
        now = time.time()
        valid_entries: list[tuple[str, dict, float]] = []
        for key, entry in entries.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                continue
            payload = entry.get("payload")
            try:
                cached_at = float(entry.get("cached_at") or 0)
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict) or cached_at <= 0 or now - cached_at > METADATA_CACHE_TTL_SECONDS:
                continue
            valid_entries.append((key, entry, cached_at))
        valid_entries.sort(key=lambda item: item[2], reverse=True)
        return {
            key: entry
            for key, entry, _ in valid_entries[:METADATA_CACHE_MAX_ENTRIES]
        }

    def _save(self) -> None:
        entries = self._prune_entries(self.data.get("entries", {}))
        items = list(entries.items())

        def payload_for(count: int) -> dict:
            return {
                "version": METADATA_CACHE_VERSION,
                "entries": dict(items[:count]),
            }

        def encoded_size(payload: dict) -> int:
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            return len(text.encode("utf-8"))

        if encoded_size(payload_for(len(items))) > METADATA_CACHE_MAX_BYTES:
            low = 0
            high = len(items)
            while low < high:
                middle = (low + high + 1) // 2
                if encoded_size(payload_for(middle)) <= METADATA_CACHE_MAX_BYTES:
                    low = middle
                else:
                    high = middle - 1
            self.data = payload_for(low)
        else:
            self.data = payload_for(len(items))
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
            self.data["entries"] = self._prune_entries(self.data["entries"])
            self._save()


_PERSISTENT_METADATA_CACHE: PersistentMetadataCache | None = None
_PERSISTENT_METADATA_CACHE_LOCK = threading.Lock()


def get_persistent_metadata_cache() -> PersistentMetadataCache:
    global _PERSISTENT_METADATA_CACHE
    with _PERSISTENT_METADATA_CACHE_LOCK:
        if _PERSISTENT_METADATA_CACHE is None:
            _PERSISTENT_METADATA_CACHE = PersistentMetadataCache()
        return _PERSISTENT_METADATA_CACHE
