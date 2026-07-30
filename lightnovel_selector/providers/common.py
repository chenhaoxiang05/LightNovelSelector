from __future__ import annotations

from collections.abc import Iterable

from ..constants import METADATA_SUMMARY_MAX_CHARS, METADATA_TEXT_MAX_CHARS
from ..parsing import collapse_spaces


def unique_existing(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        clean = collapse_spaces(value)[:METADATA_TEXT_MAX_CHARS]
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
        if len(result) >= 100:
            break
    return result


def clean_summary(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    lines = [line.strip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    summary = "\n".join(line for line in lines if line).strip()
    return summary[:METADATA_SUMMARY_MAX_CHARS] or None
