from __future__ import annotations

from ..constants import IDENTITY_MAX_AUTHORS, IDENTITY_MAX_TAGS
from ..files import http_json, validate_https_url
from ..identity import normalize_identity_values
from ..models import BookIdentity, BookMetadata, ResolveResult
from ..parsing import (
    acceptance_threshold,
    extract_series_guess,
    normalize_language_code,
    parse_volume_number,
    safe_folder_name,
    score_title,
)
from .base import MetadataProvider
from .common import clean_summary, unique_existing

ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"
ANILIST_SEARCH_QUERY = """
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
      genres
      description(asHtml: false)
      siteUrl
      countryOfOrigin
      coverImage {
        extraLarge
        large
        medium
      }
      staff(perPage: 12) {
        edges {
          role
          node {
            name {
              full
              native
            }
          }
        }
      }
    }
  }
}
"""


class AniListProvider(MetadataProvider):
    provider_id = "anilist"
    display_name = "AniList"
    priority = 20
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
            summary=clean_summary(item.get("description")),
            cover_url=_cover_url(item),
            url=_safe_url(item.get("siteUrl")),
        )

    @staticmethod
    def _best_match(
        query: str,
        *,
        timeout: float,
    ) -> tuple[float, str, dict] | None:
        data = http_json(
            ANILIST_GRAPHQL_URL,
            payload={
                "query": ANILIST_SEARCH_QUERY,
                "variables": {"search": query},
            },
            timeout=timeout,
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
            for candidate in _title_candidates(item):
                score = score_title(query, candidate)
                if best is None or score > best[0]:
                    best = (score, candidate, item)

        if best is None or best[0] < acceptance_threshold(query):
            return None
        canonical_candidates = _canonical_titles(best[2], fallback=best[1])
        if not canonical_candidates:
            return None
        return best[0], canonical_candidates[0], best[2]


def _title_candidates(item: dict) -> list[str]:
    titles = item.get("title")
    if not isinstance(titles, dict):
        titles = {}
    synonyms = item.get("synonyms")
    if not isinstance(synonyms, list):
        synonyms = []
    return unique_existing(
        [
            titles.get("english"),
            titles.get("romaji"),
            titles.get("native"),
            *synonyms,
        ]
    )


def _canonical_titles(item: dict, *, fallback: str) -> list[str]:
    titles = item.get("title")
    if not isinstance(titles, dict):
        titles = {}
    return unique_existing(
        [
            titles.get("english"),
            titles.get("romaji"),
            titles.get("native"),
            fallback,
        ]
    )


def _identity_from_item(item: dict, *, query: str, canonical: str) -> BookIdentity:
    genres = item.get("genres")
    if not isinstance(genres, list):
        genres = []
    country = item.get("countryOfOrigin")
    language = (
        normalize_language_code({"JP": "ja", "CN": "zh", "KR": "ko"}.get(country, ""))
        if isinstance(country, str)
        else None
    )
    return BookIdentity(
        title=canonical,
        series_name=safe_folder_name(extract_series_guess(canonical)),
        authors=normalize_identity_values(
            _author_values(item),
            limit=IDENTITY_MAX_AUTHORS,
            kind="author",
        ),
        volume_number=parse_volume_number(query),
        language=language,
        tags=normalize_identity_values(genres, limit=IDENTITY_MAX_TAGS),
    )


def _author_values(item: dict) -> list[object]:
    staff = item.get("staff")
    edges = staff.get("edges") if isinstance(staff, dict) else None
    if not isinstance(edges, list):
        return []
    result: list[object] = []
    for edge in edges[:20]:
        if not isinstance(edge, dict):
            continue
        role = str(edge.get("role") or "").casefold()
        if not any(label in role for label in ("story", "original", "creator", "writer")):
            continue
        node = edge.get("node")
        name = node.get("name") if isinstance(node, dict) else None
        if isinstance(name, dict):
            result.extend((name.get("full"), name.get("native")))
    return result


def _cover_url(item: dict) -> str | None:
    cover = item.get("coverImage")
    if not isinstance(cover, dict):
        return None
    for value in (cover.get("extraLarge"), cover.get("large"), cover.get("medium")):
        url = _safe_url(value)
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
