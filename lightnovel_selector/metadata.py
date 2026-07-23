from __future__ import annotations

import json
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Iterable

from .constants import (
    BANGUMI_DETAIL_PAGES,
    BANGUMI_SEARCH_LIMIT,
    BANGUMI_SEARCH_URL,
    BANGUMI_SUBJECT_WEB_URL,
    METADATA_SUMMARY_MAX_CHARS,
    METADATA_TEXT_MAX_CHARS,
)
from .files import http_json, validate_https_url
from .models import BookMetadata, ResolveResult
from .parsing import (
    acceptance_threshold,
    collapse_spaces,
    extract_book_lookup_query,
    extract_series_guess,
    normalize_for_match,
    parse_volume_number,
    safe_folder_name,
    score_title,
    title_has_volume,
)
from .storage import (
    PersistentMetadataCache,
    book_metadata_from_dict,
    book_metadata_to_dict,
    get_persistent_metadata_cache,
    resolve_result_from_dict,
    resolve_result_to_dict,
)


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
    values: list[str | None] = [item.get("name_cn"), item.get("name")]
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


def clean_summary(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    lines = [line.strip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    summary = "\n".join(line for line in lines if line).strip()
    return summary[:METADATA_SUMMARY_MAX_CHARS] or None


def bangumi_subject_url(item: dict) -> str | None:
    subject_id = item.get("id")
    if isinstance(subject_id, bool) or not isinstance(subject_id, int) or subject_id <= 0:
        return None
    return BANGUMI_SUBJECT_WEB_URL.format(subject_id=subject_id)


def bangumi_metadata_from_item(item: dict, *, confidence: float, query: str) -> BookMetadata:
    candidates = bangumi_title_candidates(item)
    title = candidates[0] if candidates else query[:METADATA_TEXT_MAX_CHARS]
    return BookMetadata(
        title=title,
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
                {"limit": BANGUMI_SEARCH_LIMIT, "offset": page * BANGUMI_SEARCH_LIMIT}
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
        base = max(base, max(score_title(series_name, candidate) for candidate in candidates) * 0.92)

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


def suggest_renamed_filename(
    original_path: Path,
    *,
    series_name: str,
    metadata: BookMetadata | None,
    identity_query: str,
) -> str:
    volume_number = None
    if metadata is not None:
        volume_number = parse_volume_number(metadata.title) or parse_volume_number(metadata.query)
    if volume_number is None:
        volume_number = parse_volume_number(identity_query) or parse_volume_number(original_path.name)

    if series_name and volume_number is not None:
        base = f"{series_name} 第{volume_number:02d}卷"
    elif metadata is not None and metadata.title:
        base = metadata.title
    else:
        base = extract_series_guess(identity_query or original_path.name)

    return safe_folder_name(base) + original_path.suffix


class SeriesResolver:
    def __init__(
        self,
        use_network: bool = True,
        timeout: float = 10.0,
        persistent_cache: PersistentMetadataCache | None = None,
    ) -> None:
        self.use_network = use_network
        self.timeout = timeout
        self._cache: dict[str, ResolveResult] = {}
        self.persistent_cache = persistent_cache if persistent_cache is not None else get_persistent_metadata_cache()
        self.last_network_error: str | None = None

    def resolve(self, file_name: str) -> ResolveResult:
        local_guess = extract_series_guess(file_name)
        cache_key = normalize_for_match(local_guess)
        if cache_key in self._cache:
            return self._cache[cache_key]

        result: ResolveResult | None = None
        if self.use_network:
            persistent_key = "series:" + cache_key
            cached_payload = self.persistent_cache.get(persistent_key)
            result = resolve_result_from_dict(cached_payload) if cached_payload else None
            if result is None:
                self.last_network_error = None
                result = self._resolve_with_network(local_guess)
                if result is not None:
                    self.persistent_cache.set(persistent_key, resolve_result_to_dict(result))

        if result is None:
            suffix = "（联网失败）" if self.last_network_error else ""
            result = ResolveResult(
                series_name=local_guess,
                source=f"本地规则{suffix}",
                confidence=0.55,
                local_guess=local_guess,
            )

        self._cache[cache_key] = result
        return result

    def resolve_book_metadata(self, file_name: str, series_name: str = "") -> BookMetadata | None:
        return self.resolve_book_metadata_for_query(extract_book_lookup_query(file_name), series_name=series_name)

    def resolve_book_metadata_for_query(self, query: str, series_name: str = "") -> BookMetadata | None:
        if not self.use_network:
            return None

        query = collapse_spaces(query)
        if not query:
            return None
        cache_key = "book:" + normalize_for_match(query)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return BookMetadata(
                title=cached.metadata_title or cached.series_name,
                source=cached.source,
                confidence=cached.confidence,
                query=query,
                summary=cached.metadata_summary,
                cover_url=cached.metadata_cover_url,
                url=cached.metadata_url,
            )
        cached_payload = self.persistent_cache.get(cache_key)
        cached_metadata = book_metadata_from_dict(cached_payload) if cached_payload else None
        if cached_metadata is not None:
            self._cache[cache_key] = ResolveResult(
                series_name=cached_metadata.title,
                source=cached_metadata.source,
                confidence=cached_metadata.confidence,
                local_guess=query,
                metadata_title=cached_metadata.title,
                metadata_summary=cached_metadata.summary,
                metadata_cover_url=cached_metadata.cover_url,
                metadata_url=cached_metadata.url,
            )
            return cached_metadata

        volume_number = parse_volume_number(query)
        self.last_network_error = None
        try:
            items = bangumi_search_items(query, timeout=self.timeout, pages=BANGUMI_DETAIL_PAGES)
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            RuntimeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            self.last_network_error = f"resolve_book_metadata: {exc}"
            return None

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

        metadata = bangumi_metadata_from_item(best[1], confidence=best[0], query=query)
        self.persistent_cache.set(cache_key, book_metadata_to_dict(metadata))
        self._cache[cache_key] = ResolveResult(
            series_name=metadata.title,
            source=metadata.source,
            confidence=metadata.confidence,
            local_guess=query,
            metadata_title=metadata.title,
            metadata_summary=metadata.summary,
            metadata_cover_url=metadata.cover_url,
            metadata_url=metadata.url,
        )
        return metadata

    def _resolve_with_network(self, query: str) -> ResolveResult | None:
        for provider in (self._search_bangumi, self._search_anilist, self._search_jikan):
            try:
                result = provider(query)
            except (
                urllib.error.URLError,
                TimeoutError,
                OSError,
                RuntimeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ) as exc:
                self.last_network_error = f"{provider.__name__}: {exc}"
                result = None
            if result is not None:
                return result
        return None

    def _search_bangumi(self, query: str) -> ResolveResult | None:
        items = bangumi_search_items(query, timeout=self.timeout)
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
        return ResolveResult(
            series_name=safe_folder_name(display_title),
            source="Bangumi",
            confidence=best[0],
            local_guess=query,
            metadata_title=display_title,
            metadata_summary=clean_summary(item.get("summary")),
            metadata_cover_url=bangumi_cover_url(item),
            metadata_url=bangumi_subject_url(item),
        )

    def _search_anilist(self, query: str) -> ResolveResult | None:
        graphql = """
        query ($search: String) {
          Page(page: 1, perPage: 8) {
            media(search: $search, type: MANGA, format_in: [NOVEL]) {
              id
              format
              title {
                romaji
                english
                native
              }
              synonyms
            }
          }
        }
        """
        data = http_json(
            "https://graphql.anilist.co",
            payload={"query": graphql, "variables": {"search": query}},
            timeout=self.timeout,
        )
        data_node = data.get("data")
        page_node = data_node.get("Page") if isinstance(data_node, dict) else None
        media_items = page_node.get("media") if isinstance(page_node, dict) else None
        if not isinstance(media_items, list):
            raise RuntimeError("AniList 接口返回的媒体列表格式无效。")
        best: tuple[float, str, dict] | None = None
        for item in media_items:
            if not isinstance(item, dict):
                continue
            titles = item.get("title")
            if not isinstance(titles, dict):
                titles = {}
            synonyms = item.get("synonyms")
            if not isinstance(synonyms, list):
                synonyms = []
            candidates = unique_existing(
                [
                    titles.get("english"),
                    titles.get("romaji"),
                    titles.get("native"),
                    *synonyms,
                ]
            )
            for candidate in candidates:
                score = score_title(query, candidate)
                if best is None or score > best[0]:
                    best = (score, candidate, item)

        if best is None or best[0] < acceptance_threshold(query):
            return None

        titles = best[2].get("title")
        if not isinstance(titles, dict):
            titles = {}
        canonical_candidates = unique_existing(
            [
                titles.get("english"),
                titles.get("romaji"),
                titles.get("native"),
                best[1],
            ]
        )
        canonical = canonical_candidates[0]
        return ResolveResult(
            series_name=safe_folder_name(canonical),
            source="AniList",
            confidence=best[0],
            local_guess=query,
        )

    def _search_jikan(self, query: str) -> ResolveResult | None:
        url = "https://api.jikan.moe/v4/manga?" + urllib.parse.urlencode(
            {"q": query, "limit": 8, "type": "lightnovel"}
        )
        data = http_json(url, timeout=self.timeout)
        media_items = data.get("data")
        if not isinstance(media_items, list):
            raise RuntimeError("Jikan 接口返回的 data 不是数组。")
        best: tuple[float, str, dict] | None = None
        for item in media_items:
            if not isinstance(item, dict):
                continue
            title_values = [
                item.get("title_english"),
                item.get("title"),
                item.get("title_japanese"),
            ]
            titles = item.get("titles")
            if not isinstance(titles, list):
                titles = []
            for title in titles[:100]:
                if isinstance(title, dict):
                    title_values.append(title.get("title"))
            candidates = unique_existing(title_values)
            for candidate in candidates:
                score = score_title(query, candidate)
                if best is None or score > best[0]:
                    best = (score, candidate, item)

        if best is None or best[0] < acceptance_threshold(query):
            return None

        canonical_candidates = unique_existing(
            [
                best[2].get("title_english"),
                best[2].get("title"),
                best[1],
            ]
        )
        canonical = canonical_candidates[0]
        return ResolveResult(
            series_name=safe_folder_name(canonical),
            source="Jikan",
            confidence=best[0],
            local_guess=query,
        )
