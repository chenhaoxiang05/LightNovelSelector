from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .constants import (
    CORRECTION_ALIAS_MAX_CHARS,
    CORRECTION_MEMORY_FILE_NAME,
    CORRECTION_MEMORY_MAX_BYTES,
    CORRECTION_MEMORY_MAX_ENTRIES,
    CORRECTION_MEMORY_VERSION,
    SERIES_NAME_MAX_CHARS,
)
from .models import ClassificationPlan
from .parsing import (
    collapse_spaces,
    extract_series_guess,
    normalize_for_match,
    safe_folder_name,
)
from .storage import app_data_dir, read_json_bounded, write_json_atomic


@dataclass(frozen=True, slots=True)
class SeriesAlias:
    alias: str
    canonical_series: str
    updated_at: str


def correction_memory_path() -> Path:
    return app_data_dir() / CORRECTION_MEMORY_FILE_NAME


def series_alias_key(value: str) -> str:
    clean = collapse_spaces(value)[:CORRECTION_ALIAS_MAX_CHARS]
    if not clean:
        return ""
    key = normalize_for_match(extract_series_guess(clean))
    if len(key) < 2 or key.isdecimal():
        return ""
    return key


def correction_aliases_for_plan(plan: ClassificationPlan) -> tuple[str, ...]:
    values = (
        plan.series_name,
        plan.source_path.name,
        plan.identity.title,
    )
    aliases: list[str] = []
    keys: set[str] = set()
    for value in values:
        clean = collapse_spaces(extract_series_guess(value))[:CORRECTION_ALIAS_MAX_CHARS]
        key = series_alias_key(clean)
        if not key or key in keys:
            continue
        keys.add(key)
        aliases.append(clean)
    return tuple(aliases)


class RecognitionCorrectionMemory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or correction_memory_path()
        self._lock = threading.RLock()
        self._entries = self._load()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def lookup(self, *values: str | None) -> SeriesAlias | None:
        with self._lock:
            for value in values:
                if not value:
                    continue
                key = series_alias_key(value)
                if key and key in self._entries:
                    return self._entries[key]
        return None

    def remember(
        self,
        aliases: tuple[str, ...],
        canonical_series: str,
    ) -> int:
        canonical = safe_folder_name(collapse_spaces(canonical_series)[:SERIES_NAME_MAX_CHARS])
        canonical_key = series_alias_key(canonical)
        if not canonical_key:
            return 0

        now = datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
        with self._lock:
            revised = dict(self._entries)
            changed = 0
            for alias in aliases:
                clean_alias = collapse_spaces(alias)[:CORRECTION_ALIAS_MAX_CHARS]
                key = series_alias_key(clean_alias)
                if not key or key == canonical_key:
                    continue
                entry = SeriesAlias(
                    alias=clean_alias,
                    canonical_series=canonical,
                    updated_at=now,
                )
                if revised.get(key) != entry:
                    revised[key] = entry
                    changed += 1
            if not changed:
                return 0

            if len(revised) > CORRECTION_MEMORY_MAX_ENTRIES:
                ordered = sorted(
                    revised.items(),
                    key=lambda item: (item[1].updated_at, item[0]),
                    reverse=True,
                )
                revised = dict(ordered[:CORRECTION_MEMORY_MAX_ENTRIES])
            revised = self._fit_to_size_limit(revised)
            write_json_atomic(self.path, self._payload(revised))
            self._entries = revised
            return changed

    def remember_plans(
        self,
        plans: tuple[ClassificationPlan, ...],
        canonical_series: str,
    ) -> int:
        aliases = tuple(alias for plan in plans for alias in correction_aliases_for_plan(plan))
        return self.remember(aliases, canonical_series)

    def try_remember_plans(
        self,
        plans: tuple[ClassificationPlan, ...],
        canonical_series: str,
    ) -> tuple[int, OSError | None]:
        try:
            return self.remember_plans(plans, canonical_series), None
        except OSError as exc:
            return 0, exc

    def clear(self) -> None:
        with self._lock:
            write_json_atomic(self.path, self._payload({}))
            self._entries = {}

    def _load(self) -> dict[str, SeriesAlias]:
        raw = read_json_bounded(self.path, max_bytes=CORRECTION_MEMORY_MAX_BYTES)
        if not isinstance(raw, dict) or raw.get("version") != CORRECTION_MEMORY_VERSION:
            return {}
        raw_entries = raw.get("entries")
        if not isinstance(raw_entries, list):
            return {}

        entries: dict[str, SeriesAlias] = {}
        for item in raw_entries[:CORRECTION_MEMORY_MAX_ENTRIES]:
            if not isinstance(item, dict):
                continue
            alias_value = item.get("alias")
            canonical_value = item.get("canonical_series")
            updated_value = item.get("updated_at")
            if not isinstance(alias_value, str) or not isinstance(canonical_value, str):
                continue
            alias = collapse_spaces(alias_value)[:CORRECTION_ALIAS_MAX_CHARS]
            canonical = safe_folder_name(collapse_spaces(canonical_value)[:SERIES_NAME_MAX_CHARS])
            key = series_alias_key(alias)
            canonical_key = series_alias_key(canonical)
            updated_at = updated_value[:64] if isinstance(updated_value, str) else ""
            if not key or not canonical_key or key == canonical_key:
                continue
            entries[key] = SeriesAlias(
                alias=alias,
                canonical_series=canonical,
                updated_at=updated_at,
            )
        return entries

    @staticmethod
    def _payload(entries: dict[str, SeriesAlias]) -> dict:
        ordered = sorted(
            entries.items(),
            key=lambda item: (item[1].updated_at, item[0]),
            reverse=True,
        )
        return {
            "version": CORRECTION_MEMORY_VERSION,
            "entries": [
                {
                    "alias": entry.alias,
                    "canonical_series": entry.canonical_series,
                    "updated_at": entry.updated_at,
                }
                for _, entry in ordered
            ],
        }

    @classmethod
    def _fit_to_size_limit(
        cls,
        entries: dict[str, SeriesAlias],
    ) -> dict[str, SeriesAlias]:
        ordered = sorted(
            entries.items(),
            key=lambda item: (item[1].updated_at, item[0]),
            reverse=True,
        )
        low = 0
        high = len(ordered)
        while low < high:
            middle = (low + high + 1) // 2
            candidate = dict(ordered[:middle])
            encoded_size = len(
                (
                    json.dumps(
                        cls._payload(candidate),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            if encoded_size <= CORRECTION_MEMORY_MAX_BYTES:
                low = middle
            else:
                high = middle - 1
        return dict(ordered[:low])
