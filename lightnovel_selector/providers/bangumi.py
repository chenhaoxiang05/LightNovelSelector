from __future__ import annotations

import urllib.parse

from ..constants import (
    BANGUMI_DETAIL_PAGES,
    BANGUMI_SEARCH_LIMIT,
    BANGUMI_SEARCH_URL,
    BANGUMI_SUBJECT_WEB_URL,
    IDENTITY_MAX_AUTHORS,
    IDENTITY_MAX_TAGS,
    METADATA_TEXT_MAX_CHARS,
)
from ..files import http_json, validate_https_url
from ..identity import normalize_identity_values
from ..models import BookIdentity, BookMetadata, ResolveResult
from ..parsing import (
    acceptance_threshold,
    collapse_spaces,
    extract_series_guess,
    normalize_language_code,
    parse_volume_number,
    safe_folder_name,
    score_title,
    title_has_volume,
)
from .base import MetadataProvider
from .common import clean_summary, unique_existing


def flatten_bangumi_value(value: object, *, depth: int = 0) -> list[str]:
    if depth >= 8:
        return []
    if value is None:
        return []
    if isinstance(value, str):
        return [value[:METADATA_TEXT_MAX_CHARS]]
    if isinstance(value, dict):
        return flatten_bangumi_value(
            value.get("v") or value.get("value") or value.get("name"),
            depth=depth + 1,
        )
    if isinstance(value, list):
        result: list[str] = []
        for item in value[:100]:
            result.extend(flatten_bangumi_value(item, depth=depth + 1))
            if len(result) >= 100:
                break
        return result
    return []


def bangumi_title_candidates(item: dict) -> list[str]:
    values: list[object] = [item.get("name_cn"), item.get("name")]
    infobox = item.get("infobox")
    if not isinstance(infobox, list):
        infobox = []
    for row in infobox[:100]:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").casefold()
        if any(label in key for label in ("别名", "alias", "title")):
            values.extend(flatten_bangumi_value(row.get("value")))
    return unique_existing(values)


def bangumi_infobox_values(item: dict, labels: tuple[str, ...]) -> list[str]:
    infobox = item.get("infobox")
    if not isinstance(infobox, list):
        return []
    values: list[str] = []
    for row in infobox[:100]:
        if not isinstance(row, dict):
            continue
        key = collapse_spaces(str(row.get("key") or "")).casefold()
        if key and any(label.casefold() in key for label in labels):
            values.extend(flatten_bangumi_value(row.get("value")))
    return unique_existing(values)


def bangumi_tags(item: dict) -> tuple[str, ...]:
    raw_tags = item.get("tags")
    if not isinstance(raw_tags, list):
        return ()
    values = [tag.get("name") for tag in raw_tags[:100] if isinstance(tag, dict)]
    return normalize_identity_values(values, limit=IDENTITY_MAX_TAGS)


def bangumi_identity_from_item(item: dict, *, query: str) -> BookIdentity:
    candidates = bangumi_title_candidates(item)
    title = candidates[0] if candidates else query[:METADATA_TEXT_MAX_CHARS]
    author_values = bangumi_infobox_values(item, ("作者", "著者", "原作"))
    language_values = bangumi_infobox_values(item, ("语言", "語言"))
    language = next(
        (normalized for value in language_values if (normalized := normalize_language_code(value)) is not None),
        None,
    )
    title_volume = parse_volume_number(title)
    query_volume = parse_volume_number(query)
    return BookIdentity(
        title=title,
        series_name=safe_folder_name(extract_series_guess(title)),
        authors=normalize_identity_values(author_values, limit=IDENTITY_MAX_AUTHORS),
        volume_number=title_volume if title_volume is not None else query_volume,
        language=language,
        tags=bangumi_tags(item),
    )


def bangumi_cover_url(item: dict) -> str | None:
    images = item.get("images")
    if not isinstance(images, dict):
        images = {}
    candidates = (
        images.get("common"),
        images.get("medium"),
        images.get("large"),
        images.get("small"),
        item.get("image"),
    )
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        try:
            return validate_https_url(candidate)
        except ValueError:
            continue
    return None


def bangumi_subject_url(item: dict) -> str | None:
    subject_id = item.get("id")
    if isinstance(subject_id, bool) or not isinstance(subject_id, int) or subject_id <= 0:
        return None
    return BANGUMI_SUBJECT_WEB_URL.format(subject_id=subject_id)


def bangumi_metadata_from_item(item: dict, *, confidence: float, query: str) -> BookMetadata:
    return BookMetadata(
        identity=bangumi_identity_from_item(item, query=query),
        source="Bangumi",
        confidence=confidence,
        query=query,
        summary=clean_summary(item.get("summary")),
        cover_url=bangumi_cover_url(item),
        url=bangumi_subject_url(item),
    )


def bangumi_search_items(query: str, *, timeout: float, pages: int = 1) -> list[dict]:
    payload = {
        "keyword": query,
        "sort": "match",
        "filter": {"type": [1]},
    }
    items: list[dict] = []
    seen_ids: set[int] = set()
    for page in range(max(1, pages)):
        url = BANGUMI_SEARCH_URL
        if pages > 1:
            url += "?" + urllib.parse.urlencode(
                {
                    "limit": BANGUMI_SEARCH_LIMIT,
                    "offset": page * BANGUMI_SEARCH_LIMIT,
                }
            )
        data = http_json(url, payload=payload, timeout=timeout)
        page_items = data.get("data", [])
        if not isinstance(page_items, list):
            raise RuntimeError("Bangumi 接口返回的 data 不是数组。")
        for item in page_items[:BANGUMI_SEARCH_LIMIT]:
            if not isinstance(item, dict):
                continue
            subject_id = item.get("id")
            if isinstance(subject_id, int):
                if subject_id in seen_ids:
                    continue
                seen_ids.add(subject_id)
            items.append(item)
        if len(page_items) < BANGUMI_SEARCH_LIMIT:
            break
    return items


def score_bangumi_item_for_detail(
    item: dict,
    *,
    query: str,
    series_name: str,
    volume_number: int | None,
) -> float:
    candidates = bangumi_title_candidates(item)
    if not candidates:
        return 0.0

    base = max(score_title(query, candidate) for candidate in candidates)
    if series_name:
        base = max(
            base,
            max(score_title(series_name, candidate) for candidate in candidates) * 0.92,
        )

    candidate_text = " ".join(candidates)
    has_volume = title_has_volume(candidate_text, volume_number)
    platform = str(item.get("platform") or "")

    if volume_number is not None:
        if has_volume:
            base += 0.28
        else:
            base -= 0.18
    if platform == "小说":
        base += 0.08
    elif platform:
        base -= 0.08

    return max(0.0, min(base, 1.0))


def item_matches_volume(item: dict, volume_number: int | None) -> bool:
    if volume_number is None:
        return False
    return title_has_volume(" ".join(bangumi_title_candidates(item)), volume_number)


class BangumiProvider(MetadataProvider):
    provider_id = "bangumi"
    display_name = "Bangumi"
    priority = 10
    cache_version = "1"

    def resolve_series(self, query: str, *, timeout: float) -> ResolveResult | None:
        items = bangumi_search_items(query, timeout=timeout)
        best: tuple[float, str, dict] | None = None

        for item in items:
            if item.get("type") != 1:
                continue
            candidates = bangumi_title_candidates(item)
            for candidate in candidates:
                score = score_title(query, candidate)
                if str(item.get("platform") or "") == "小说":
                    score = min(1.0, score + 0.02)
                if best is None or score > best[0]:
                    best = (score, candidate, item)

        if best is None or best[0] < acceptance_threshold(query):
            return None

        item = best[2]
        display_titles = bangumi_title_candidates(item)
        display_title = display_titles[0] if display_titles else best[1]
        identity = bangumi_identity_from_item(item, query=query)
        identity = BookIdentity(
            title=display_title,
            series_name=safe_folder_name(extract_series_guess(display_title)),
            authors=identity.authors,
            volume_number=identity.volume_number,
            language=identity.language,
            tags=identity.tags,
        )
        return ResolveResult(
            identity=identity,
            source=self.display_name,
            confidence=best[0],
            local_guess=query,
            metadata_summary=clean_summary(item.get("summary")),
            metadata_cover_url=bangumi_cover_url(item),
            metadata_url=bangumi_subject_url(item),
        )

    def resolve_book(
        self,
        query: str,
        *,
        series_name: str,
        timeout: float,
    ) -> BookMetadata | None:
        volume_number = parse_volume_number(query)
        items = bangumi_search_items(
            query,
            timeout=timeout,
            pages=BANGUMI_DETAIL_PAGES,
        )
        candidate_items = [item for item in items if item.get("type") == 1]
        if volume_number is not None:
            exact_volume_items = [item for item in candidate_items if item_matches_volume(item, volume_number)]
            if exact_volume_items:
                candidate_items = exact_volume_items

        best: tuple[float, dict] | None = None
        for item in candidate_items:
            score = score_bangumi_item_for_detail(
                item,
                query=query,
                series_name=series_name,
                volume_number=volume_number,
            )
            if volume_number is not None and item_matches_volume(item, volume_number):
                score = max(score, 0.88)
                if str(item.get("platform") or "") == "小说":
                    score = max(score, 0.96)
            if best is None or score > best[0]:
                best = (score, item)

        if best is None:
            return None
        if volume_number is None and best[0] < acceptance_threshold(query):
            return None
        if volume_number is not None and best[0] < 0.68:
            return None
        return bangumi_metadata_from_item(best[1], confidence=best[0], query=query)
