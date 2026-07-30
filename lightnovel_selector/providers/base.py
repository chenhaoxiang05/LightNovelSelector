from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from ..constants import (
    IDENTITY_MAX_AUTHORS,
    IDENTITY_MAX_TAGS,
    METADATA_TEXT_MAX_CHARS,
    VOLUME_NUMBER_MAX,
)
from ..files import validate_https_url
from ..identity import normalize_identity_values
from ..models import BookIdentity, BookMetadata, ResolveResult
from ..parsing import (
    collapse_spaces,
    normalize_language_code,
    safe_folder_name,
)
from .common import clean_summary

PROVIDER_ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,47}")
PROVIDER_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
PROVIDER_DISPLAY_NAME_MAX_CHARS = 80
PROVIDER_ERROR_MAX_CHARS = 400


class ProviderContractError(ValueError):
    """Raised when a provider returns data outside the public contract."""


class MetadataProvider(ABC):
    provider_id = ""
    display_name = ""
    priority = 100
    cache_version = "1"

    @abstractmethod
    def resolve_series(self, query: str, *, timeout: float) -> ResolveResult | None:
        """Return the best series match, or None when the provider has no match."""

    def resolve_book(
        self,
        query: str,
        *,
        series_name: str,
        timeout: float,
    ) -> BookMetadata | None:
        """Return book-level metadata when supported by the provider."""

        return None


@dataclass(frozen=True, slots=True, init=False)
class MetadataProviderRegistry:
    _providers: tuple[MetadataProvider, ...]
    cache_namespace: str

    def __init__(self, providers: Iterable[MetadataProvider]) -> None:
        collected: list[tuple[int, int, MetadataProvider]] = []
        provider_ids: set[str] = set()
        for position, provider in enumerate(providers):
            if not isinstance(provider, MetadataProvider):
                raise TypeError("元数据提供器必须继承 MetadataProvider。")
            _validate_provider_descriptor(provider)
            if provider.provider_id in provider_ids:
                raise ValueError(f"元数据提供器 ID 重复：{provider.provider_id}")
            provider_ids.add(provider.provider_id)
            collected.append((provider.priority, position, provider))

        ordered = tuple(item[2] for item in sorted(collected))
        signature = ";".join(f"{provider.provider_id}@{provider.cache_version}" for provider in ordered)
        namespace = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
        object.__setattr__(self, "_providers", ordered)
        object.__setattr__(self, "cache_namespace", namespace)

    @property
    def providers(self) -> tuple[MetadataProvider, ...]:
        return self._providers

    def __iter__(self) -> Iterator[MetadataProvider]:
        return iter(self._providers)

    def __len__(self) -> int:
        return len(self._providers)

    def get(self, provider_id: str) -> MetadataProvider | None:
        if not isinstance(provider_id, str):
            return None
        return next(
            (provider for provider in self._providers if provider.provider_id == provider_id),
            None,
        )


def provider_error_message(provider: MetadataProvider, exc: Exception) -> str:
    try:
        raw_message = str(exc)
    except MemoryError:
        raise
    except Exception:  # noqa: BLE001 - provider exceptions may implement a broken __str__.
        raw_message = exc.__class__.__name__
    message = collapse_spaces(raw_message)[:PROVIDER_ERROR_MAX_CHARS] or exc.__class__.__name__
    return f"{provider.display_name}: {message}"


def normalize_provider_resolve_result(
    provider: MetadataProvider,
    result: ResolveResult,
    *,
    query: str,
) -> ResolveResult:
    if not isinstance(result, ResolveResult):
        raise ProviderContractError("resolve_series 必须返回 ResolveResult 或 None。")
    return ResolveResult(
        identity=_normalize_identity(result.identity),
        source=provider.display_name,
        confidence=_normalize_confidence(result.confidence),
        local_guess=collapse_spaces(query)[:METADATA_TEXT_MAX_CHARS],
        metadata_summary=clean_summary(result.metadata_summary),
        metadata_cover_url=_safe_optional_https_url(result.metadata_cover_url),
        metadata_url=_safe_optional_https_url(result.metadata_url),
    )


def normalize_provider_book_metadata(
    provider: MetadataProvider,
    metadata: BookMetadata,
    *,
    query: str,
) -> BookMetadata:
    if not isinstance(metadata, BookMetadata):
        raise ProviderContractError("resolve_book 必须返回 BookMetadata 或 None。")
    return BookMetadata(
        identity=_normalize_identity(metadata.identity),
        source=provider.display_name,
        confidence=_normalize_confidence(metadata.confidence),
        query=collapse_spaces(query)[:METADATA_TEXT_MAX_CHARS],
        summary=clean_summary(metadata.summary),
        cover_url=_safe_optional_https_url(metadata.cover_url),
        url=_safe_optional_https_url(metadata.url),
    )


def _validate_provider_descriptor(provider: MetadataProvider) -> None:
    if not isinstance(provider.provider_id, str) or PROVIDER_ID_PATTERN.fullmatch(provider.provider_id) is None:
        raise ValueError("元数据提供器 ID 必须是小写字母开头的字母、数字、下划线或连字符。")
    if not isinstance(provider.display_name, str):
        raise ValueError(f"提供器 {provider.provider_id} 缺少显示名称。")
    clean_name = collapse_spaces(provider.display_name)
    if not clean_name or clean_name != provider.display_name or len(clean_name) > PROVIDER_DISPLAY_NAME_MAX_CHARS:
        raise ValueError(f"提供器 {provider.provider_id} 的显示名称无效。")
    if (
        not isinstance(provider.cache_version, str)
        or PROVIDER_VERSION_PATTERN.fullmatch(provider.cache_version) is None
    ):
        raise ValueError(f"提供器 {provider.provider_id} 的缓存版本无效。")
    if isinstance(provider.priority, bool) or not isinstance(provider.priority, int):
        raise ValueError(f"提供器 {provider.provider_id} 的优先级必须是整数。")


def _normalize_identity(identity: BookIdentity) -> BookIdentity:
    if not isinstance(identity, BookIdentity):
        raise ProviderContractError("提供器结果缺少 BookIdentity。")
    title = _required_text(identity.title, field="title")
    series_name = _required_text(identity.series_name, field="series_name")
    if not isinstance(identity.authors, (list, tuple)):
        raise ProviderContractError("identity.authors 必须是字符串列表。")
    if not isinstance(identity.tags, (list, tuple)):
        raise ProviderContractError("identity.tags 必须是字符串列表。")

    volume_number = identity.volume_number
    if volume_number is not None and (
        isinstance(volume_number, bool)
        or not isinstance(volume_number, int)
        or not 0 <= volume_number <= VOLUME_NUMBER_MAX
    ):
        raise ProviderContractError("identity.volume_number（卷号）超出有效范围。")

    language = None
    if identity.language is not None:
        if not isinstance(identity.language, str):
            raise ProviderContractError("identity.language 必须是字符串或 None。")
        language = normalize_language_code(identity.language)

    return BookIdentity(
        title=title,
        series_name=safe_folder_name(series_name),
        authors=normalize_identity_values(identity.authors, limit=IDENTITY_MAX_AUTHORS),
        volume_number=volume_number,
        language=language,
        tags=normalize_identity_values(identity.tags, limit=IDENTITY_MAX_TAGS),
    )


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ProviderContractError(f"identity.{field} 必须是字符串。")
    clean = collapse_spaces(value)[:METADATA_TEXT_MAX_CHARS]
    if not clean:
        raise ProviderContractError(f"identity.{field} 不能为空。")
    return clean


def _normalize_confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderContractError("confidence 必须是 0 到 1 之间的数字。")
    confidence = float(value)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ProviderContractError("confidence 必须是 0 到 1 之间的有限数字。")
    return confidence


def _safe_optional_https_url(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return validate_https_url(value)
    except ValueError:
        return None
