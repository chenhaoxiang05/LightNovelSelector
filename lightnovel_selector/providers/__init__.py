from __future__ import annotations

from .anilist import AniListProvider
from .bangumi import (
    BangumiProvider,
    bangumi_cover_url,
    bangumi_identity_from_item,
    bangumi_infobox_values,
    bangumi_metadata_from_item,
    bangumi_search_items,
    bangumi_subject_url,
    bangumi_tags,
    bangumi_title_candidates,
    flatten_bangumi_value,
    item_matches_volume,
    score_bangumi_item_for_detail,
)
from .base import (
    MetadataProvider,
    MetadataProviderRegistry,
    ProviderContractError,
    normalize_provider_book_metadata,
    normalize_provider_resolve_result,
    provider_error_message,
)
from .common import clean_summary, unique_existing
from .jikan import JikanProvider


def builtin_metadata_providers() -> tuple[MetadataProvider, ...]:
    return (BangumiProvider(), AniListProvider(), JikanProvider())


__all__ = [
    "AniListProvider",
    "BangumiProvider",
    "JikanProvider",
    "MetadataProvider",
    "MetadataProviderRegistry",
    "ProviderContractError",
    "bangumi_cover_url",
    "bangumi_identity_from_item",
    "bangumi_infobox_values",
    "bangumi_metadata_from_item",
    "bangumi_search_items",
    "bangumi_subject_url",
    "bangumi_tags",
    "bangumi_title_candidates",
    "builtin_metadata_providers",
    "clean_summary",
    "flatten_bangumi_value",
    "item_matches_volume",
    "normalize_provider_book_metadata",
    "normalize_provider_resolve_result",
    "provider_error_message",
    "score_bangumi_item_for_detail",
    "unique_existing",
]
