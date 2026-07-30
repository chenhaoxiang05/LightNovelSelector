from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from .constants import (
    CLASSIFICATION_CANDIDATE_MAX_COUNT,
    IDENTITY_MAX_AUTHORS,
    IDENTITY_MAX_TAGS,
    IDENTITY_VALUE_MAX_CHARS,
    METADATA_TEXT_MAX_CHARS,
)
from .models import BookIdentity, ClassificationCandidate
from .parsing import (
    collapse_spaces,
    extract_book_lookup_query,
    extract_series_guess,
    infer_language,
    normalize_for_match,
    parse_volume_number,
    safe_folder_name,
)


def normalize_identity_values(values: Iterable[object], *, limit: int) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        clean = collapse_spaces(value)[:IDENTITY_VALUE_MAX_CHARS]
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        result.append(clean)
        if len(result) >= limit:
            break
    return tuple(result)


def identity_from_filename(file_name: str, *, hint: str | None = None) -> BookIdentity:
    title = extract_book_lookup_query(file_name)
    return BookIdentity(
        title=title[:METADATA_TEXT_MAX_CHARS],
        series_name=safe_folder_name(extract_series_guess(file_name)),
        volume_number=parse_volume_number(file_name),
        language=infer_language(file_name, hint),
    )


def merge_book_identities(
    local: BookIdentity,
    *resolved: BookIdentity | None,
    series_name: str | None = None,
) -> BookIdentity:
    title = local.title
    series = local.series_name
    authors = local.authors
    volume_number = local.volume_number
    language = local.language
    tags = local.tags

    for candidate in resolved:
        if candidate is None:
            continue
        title = candidate.title or title
        series = candidate.series_name or series
        authors = normalize_identity_values(
            (*candidate.authors, *authors),
            limit=IDENTITY_MAX_AUTHORS,
        )
        volume_number = candidate.volume_number if candidate.volume_number is not None else volume_number
        language = language or candidate.language
        tags = normalize_identity_values(
            (*candidate.tags, *tags),
            limit=IDENTITY_MAX_TAGS,
        )

    return BookIdentity(
        title=collapse_spaces(title)[:METADATA_TEXT_MAX_CHARS],
        series_name=safe_folder_name(series_name or series),
        authors=authors,
        volume_number=volume_number,
        language=language,
        tags=tags,
    )


def with_series_name(identity: BookIdentity, series_name: str) -> BookIdentity:
    return replace(identity, series_name=safe_folder_name(series_name))


def merge_classification_candidates(
    *groups: Iterable[ClassificationCandidate],
) -> tuple[ClassificationCandidate, ...]:
    result: list[ClassificationCandidate] = []
    positions: dict[str, int] = {}
    for group in groups:
        for candidate in group:
            key = normalize_for_match(candidate.identity.series_name)
            if not key:
                continue
            position = positions.get(key)
            if position is None:
                if len(result) >= CLASSIFICATION_CANDIDATE_MAX_COUNT:
                    continue
                positions[key] = len(result)
                result.append(candidate)
            elif candidate.confidence > result[position].confidence:
                result[position] = candidate
    return tuple(result)


def language_display_name(language: str | None) -> str:
    return {
        "zh": "中文",
        "zh-Hans": "简体中文",
        "zh-Hant": "繁体中文",
        "ja": "日语",
        "en": "英语",
        "ko": "韩语",
    }.get(language or "", language or "未识别")


def volume_display_name(volume_number: int | None) -> str:
    return f"第 {volume_number} 卷" if volume_number is not None else "未识别"
