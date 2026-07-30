from __future__ import annotations

import urllib.parse

from ..constants import IDENTITY_MAX_AUTHORS, IDENTITY_MAX_TAGS
from ..files import http_json, validate_https_url
from ..identity import normalize_identity_values
from ..models import BookIdentity, BookMetadata, ResolveResult
from ..parsing import (
    acceptance_threshold,
    extract_series_guess,
    parse_volume_number,
    safe_folder_name,
    score_title,
)
from .base import MetadataProvider
from .common import clean_summary, unique_existing

JIKAN_SEARCH_URL = "https://api.jikan.moe/v4/manga"


class JikanProvider(MetadataProvider):
    provider_id = "jikan"
    display_name = "Jikan"
    priority = 30
    cache_version = "2"

    def resolve_series(self, query: str, *, timeout: float) -> ResolveResult | None:
        best = self._best_match(query, timeout=timeout)
        if best is None:
            return None
        confidence, canonical, item = best
        return ResolveResult(
            identity=_identity_from_item(item, query=query, canonical=canonical),
            source=self.display_name,
            confidence=confidence,
            local_guess=query,
        )

    def resolve_book(
        self,
        query: str,
        *,
        series_name: str,
        timeout: float,
    ) -> BookMetadata | None:
        best = self._best_match(query, timeout=timeout)
        if best is None:
            return None
        confidence, canonical, item = best
        return BookMetadata(
            identity=_identity_from_item(item, query=query, canonical=canonical),
            source=self.display_name,
            confidence=confidence,
            query=query,
            summary=clean_summary(item.get("synopsis")),
            cover_url=_cover_url(item),
            url=_safe_url(item.get("url")),
        )

    @staticmethod
    def _best_match(
        query: str,
        *,
        timeout: float,
    ) -> tuple[float, str, dict] | None:
        url = (
            JIKAN_SEARCH_URL
            + "?"
            + urllib.parse.urlencode(
                {
                    "q": query,
                    "limit": 8,
                    "type": "lightnovel",
                }
            )
        )
        data = http_json(url, timeout=timeout)
        media_items = data.get("data")
        if not isinstance(media_items, list):
            raise RuntimeError("Jikan 接口返回的 data 不是数组。")

        best: tuple[float, str, dict] | None = None
        for item in media_items:
            if not isinstance(item, dict):
                continue
            for candidate in _title_candidates(item):
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
        if not canonical_candidates:
            return None
        return best[0], canonical_candidates[0], best[2]


def _title_candidates(item: dict) -> list[str]:
    title_values: list[object] = [
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
    return unique_existing(title_values)


def _identity_from_item(item: dict, *, query: str, canonical: str) -> BookIdentity:
    author_values = (
        [author.get("name") for author in item.get("authors", [])[:20] if isinstance(author, dict)]
        if isinstance(item.get("authors"), list)
        else []
    )
    tag_values: list[object] = []
    for key in ("genres", "themes", "demographics"):
        values = item.get(key)
        if isinstance(values, list):
            tag_values.extend(value.get("name") for value in values[:40] if isinstance(value, dict))
    return BookIdentity(
        title=canonical,
        series_name=safe_folder_name(extract_series_guess(canonical)),
        authors=normalize_identity_values(author_values, limit=IDENTITY_MAX_AUTHORS),
        volume_number=parse_volume_number(query),
        tags=normalize_identity_values(tag_values, limit=IDENTITY_MAX_TAGS),
    )


def _cover_url(item: dict) -> str | None:
    images = item.get("images")
    if not isinstance(images, dict):
        return None
    for format_name in ("jpg", "webp"):
        format_images = images.get(format_name)
        if not isinstance(format_images, dict):
            continue
        for key in ("large_image_url", "image_url", "small_image_url"):
            url = _safe_url(format_images.get(key))
            if url:
                return url
    return None


def _safe_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return validate_https_url(value)
    except ValueError:
        return None
