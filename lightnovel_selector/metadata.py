from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .identity import identity_from_filename
from .models import BookMetadata, ResolveResult
from .parsing import (
    collapse_spaces,
    extract_book_lookup_query,
    extract_series_guess,
    normalize_for_match,
    parse_volume_number,
    safe_folder_name,
)
from .providers import (
    MetadataProvider,
    MetadataProviderRegistry,
    builtin_metadata_providers,
    normalize_provider_book_metadata,
    normalize_provider_resolve_result,
    provider_error_message,
)
from .storage import (
    PersistentMetadataCache,
    book_metadata_from_dict,
    book_metadata_to_dict,
    get_persistent_metadata_cache,
    resolve_result_from_dict,
    resolve_result_to_dict,
)

_CACHE_PROVIDER_ID_KEY = "_provider_id"


def suggest_renamed_filename(
    original_path: Path,
    *,
    series_name: str,
    metadata: BookMetadata | None,
    identity_query: str,
) -> str:
    volume_number = None
    if metadata is not None:
        volume_number = metadata.identity.volume_number
        if volume_number is None:
            volume_number = parse_volume_number(metadata.query)
    if volume_number is None:
        volume_number = parse_volume_number(identity_query)
    if volume_number is None:
        volume_number = parse_volume_number(original_path.name)

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
        providers: Iterable[MetadataProvider] | MetadataProviderRegistry | None = None,
    ) -> None:
        self.use_network = use_network
        self.timeout = timeout
        self._cache: dict[str, ResolveResult] = {}
        self.persistent_cache = persistent_cache if persistent_cache is not None else get_persistent_metadata_cache()
        self.provider_registry = (
            providers
            if isinstance(providers, MetadataProviderRegistry)
            else MetadataProviderRegistry(builtin_metadata_providers() if providers is None else providers)
        )
        self.last_network_error: str | None = None

    @property
    def providers(self) -> tuple[MetadataProvider, ...]:
        return self.provider_registry.providers

    def resolve(self, file_name: str) -> ResolveResult:
        self.last_network_error = None
        local_identity = identity_from_filename(file_name)
        local_guess = local_identity.series_name
        cache_key = self._cache_key("series", local_guess)
        if cache_key in self._cache:
            return self._cache[cache_key]

        result: ResolveResult | None = None
        if self.use_network:
            cached_payload = self.persistent_cache.get(cache_key)
            result = self._resolve_result_from_cache(cached_payload, query=local_guess)
            if result is None:
                resolved = self._resolve_with_network(local_guess)
                if resolved is not None:
                    provider, result = resolved
                    self.persistent_cache.set(
                        cache_key,
                        self._provider_cache_payload(
                            provider,
                            resolve_result_to_dict(result),
                        ),
                    )

        if result is None:
            suffix = "（联网失败）" if self.last_network_error else ""
            result = ResolveResult(
                identity=local_identity,
                source=f"本地规则{suffix}",
                confidence=0.55,
                local_guess=local_guess,
            )

        self._cache[cache_key] = result
        return result

    def resolve_candidates(self, query: str) -> tuple[ResolveResult, ...]:
        query = collapse_spaces(query)
        if not self.use_network or not query:
            return ()

        self.last_network_error = None
        results: list[ResolveResult] = []
        errors: list[str] = []
        for provider in self.provider_registry:
            try:
                raw_result = provider.resolve_series(query, timeout=self.timeout)
                if raw_result is not None:
                    results.append(
                        normalize_provider_resolve_result(
                            provider,
                            raw_result,
                            query=query,
                        )
                    )
            except MemoryError:
                raise
            # Third-party providers are an explicit isolation boundary.
            except Exception as exc:  # noqa: BLE001
                errors.append(provider_error_message(provider, exc))

        if errors:
            self.last_network_error = "；".join(errors)
        return tuple(results)

    def resolve_book_metadata(
        self,
        file_name: str,
        series_name: str = "",
    ) -> BookMetadata | None:
        return self.resolve_book_metadata_for_query(
            extract_book_lookup_query(file_name),
            series_name=series_name,
        )

    def resolve_book_metadata_for_query(
        self,
        query: str,
        series_name: str = "",
    ) -> BookMetadata | None:
        self.last_network_error = None
        if not self.use_network:
            return None

        query = collapse_spaces(query)
        if not query:
            return None
        cache_key = self._cache_key("book", query)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return BookMetadata(
                identity=cached.identity,
                source=cached.source,
                confidence=cached.confidence,
                query=query,
                summary=cached.metadata_summary,
                cover_url=cached.metadata_cover_url,
                url=cached.metadata_url,
            )
        cached_payload = self.persistent_cache.get(cache_key)
        cached_metadata = self._book_metadata_from_cache(cached_payload, query=query)
        if cached_metadata is not None:
            self._cache_book_metadata(cache_key, cached_metadata)
            return cached_metadata

        errors: list[str] = []
        for provider in self.provider_registry:
            try:
                raw_metadata = provider.resolve_book(
                    query,
                    series_name=series_name,
                    timeout=self.timeout,
                )
                if raw_metadata is None:
                    continue
                metadata = normalize_provider_book_metadata(
                    provider,
                    raw_metadata,
                    query=query,
                )
            except MemoryError:
                raise
            # A broken optional provider must not block later providers.
            except Exception as exc:  # noqa: BLE001
                errors.append(provider_error_message(provider, exc))
                continue

            if errors:
                self.last_network_error = "；".join(errors)
            self.persistent_cache.set(
                cache_key,
                self._provider_cache_payload(
                    provider,
                    book_metadata_to_dict(metadata),
                ),
            )
            self._cache_book_metadata(cache_key, metadata)
            return metadata

        if errors:
            self.last_network_error = "；".join(errors)
        return None

    def _resolve_with_network(
        self,
        query: str,
    ) -> tuple[MetadataProvider, ResolveResult] | None:
        errors: list[str] = []
        for provider in self.provider_registry:
            try:
                raw_result = provider.resolve_series(query, timeout=self.timeout)
                if raw_result is None:
                    continue
                result = normalize_provider_resolve_result(
                    provider,
                    raw_result,
                    query=query,
                )
            except MemoryError:
                raise
            # A broken optional provider must not block local classification.
            except Exception as exc:  # noqa: BLE001
                errors.append(provider_error_message(provider, exc))
                continue

            if errors:
                self.last_network_error = "；".join(errors)
            return provider, result

        if errors:
            self.last_network_error = "；".join(errors)
        return None

    def _cache_key(self, kind: str, query: str) -> str:
        normalized_query = normalize_for_match(query)
        return f"{kind}:{self.provider_registry.cache_namespace}:{normalized_query}"

    @staticmethod
    def _provider_cache_payload(
        provider: MetadataProvider,
        payload: dict,
    ) -> dict:
        return {
            **payload,
            _CACHE_PROVIDER_ID_KEY: provider.provider_id,
        }

    def _provider_from_cache(self, payload: dict | None) -> MetadataProvider | None:
        if payload is None:
            return None
        provider_id = payload.get(_CACHE_PROVIDER_ID_KEY)
        return self.provider_registry.get(provider_id) if isinstance(provider_id, str) else None

    def _resolve_result_from_cache(
        self,
        payload: dict | None,
        *,
        query: str,
    ) -> ResolveResult | None:
        provider = self._provider_from_cache(payload)
        result = resolve_result_from_dict(payload) if payload is not None else None
        if provider is None or result is None:
            return None
        try:
            return normalize_provider_resolve_result(
                provider,
                result,
                query=query,
            )
        except (TypeError, ValueError):
            return None

    def _book_metadata_from_cache(
        self,
        payload: dict | None,
        *,
        query: str,
    ) -> BookMetadata | None:
        provider = self._provider_from_cache(payload)
        metadata = book_metadata_from_dict(payload) if payload is not None else None
        if provider is None or metadata is None:
            return None
        try:
            return normalize_provider_book_metadata(
                provider,
                metadata,
                query=query,
            )
        except (TypeError, ValueError):
            return None

    def _cache_book_metadata(
        self,
        cache_key: str,
        metadata: BookMetadata,
    ) -> None:
        self._cache[cache_key] = ResolveResult(
            identity=metadata.identity,
            source=metadata.source,
            confidence=metadata.confidence,
            local_guess=metadata.query,
            metadata_summary=metadata.summary,
            metadata_cover_url=metadata.cover_url,
            metadata_url=metadata.url,
        )
