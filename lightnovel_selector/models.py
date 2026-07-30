from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BookIdentity:
    title: str
    series_name: str
    authors: tuple[str, ...] = ()
    volume_number: int | None = None
    language: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClassificationCandidate:
    identity: BookIdentity
    source: str
    confidence: float


@dataclass(frozen=True, init=False)
class ResolveResult:
    identity: BookIdentity
    source: str
    confidence: float
    local_guess: str
    metadata_summary: str | None = None
    metadata_cover_url: str | None = None
    metadata_url: str | None = None

    def __init__(
        self,
        series_name: str | None = None,
        source: str = "",
        confidence: float = 0.0,
        local_guess: str = "",
        metadata_title: str | None = None,
        metadata_summary: str | None = None,
        metadata_cover_url: str | None = None,
        metadata_url: str | None = None,
        *,
        identity: BookIdentity | None = None,
    ) -> None:
        if identity is None:
            if not series_name:
                raise TypeError("ResolveResult 需要 identity 或 series_name。")
            identity = BookIdentity(
                title=metadata_title or series_name,
                series_name=series_name,
            )
        elif series_name and series_name != identity.series_name:
            identity = BookIdentity(
                title=identity.title,
                series_name=series_name,
                authors=identity.authors,
                volume_number=identity.volume_number,
                language=identity.language,
                tags=identity.tags,
            )
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "local_guess", local_guess)
        object.__setattr__(self, "metadata_summary", metadata_summary)
        object.__setattr__(self, "metadata_cover_url", metadata_cover_url)
        object.__setattr__(self, "metadata_url", metadata_url)

    @property
    def series_name(self) -> str:
        return self.identity.series_name

    @property
    def metadata_title(self) -> str:
        return self.identity.title


@dataclass(frozen=True, init=False)
class BookMetadata:
    identity: BookIdentity
    source: str
    confidence: float
    query: str
    summary: str | None = None
    cover_url: str | None = None
    url: str | None = None

    def __init__(
        self,
        title: str | None = None,
        source: str = "",
        confidence: float = 0.0,
        query: str = "",
        summary: str | None = None,
        cover_url: str | None = None,
        url: str | None = None,
        *,
        identity: BookIdentity | None = None,
    ) -> None:
        if identity is None:
            if not title:
                raise TypeError("BookMetadata 需要 identity 或 title。")
            identity = BookIdentity(title=title, series_name=title)
        elif title and title != identity.title:
            identity = BookIdentity(
                title=title,
                series_name=identity.series_name,
                authors=identity.authors,
                volume_number=identity.volume_number,
                language=identity.language,
                tags=identity.tags,
            )
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "cover_url", cover_url)
        object.__setattr__(self, "url", url)

    @property
    def title(self) -> str:
        return self.identity.title


@dataclass(frozen=True)
class CustomRule:
    pattern: str
    series: str


@dataclass(frozen=True)
class AppSettings:
    use_network: bool = True
    recursive: bool = False
    auto_rename: bool = False
    custom_rules: tuple[CustomRule, ...] = ()
    last_folder: str = ""


@dataclass(frozen=True, init=False)
class ClassificationPlan:
    source_path: Path
    identity: BookIdentity
    target_dir: Path
    target_path: Path
    resolver_source: str
    confidence: float
    local_guess: str
    source_size: int | None = None
    source_mtime_ns: int | None = None
    metadata_summary: str | None = None
    metadata_cover_url: str | None = None
    metadata_url: str | None = None
    identity_hint: str | None = None
    identity_query: str | None = None
    network_query: str | None = None
    rename_to: str | None = None
    series_key: str | None = None
    status: str = "ready"
    note: str = ""
    duplicate_of: Path | None = None
    candidates: tuple[ClassificationCandidate, ...] = ()

    def __init__(
        self,
        source_path: Path,
        series_name: str | None = None,
        target_dir: Path | None = None,
        target_path: Path | None = None,
        resolver_source: str = "",
        confidence: float = 0.0,
        local_guess: str = "",
        source_size: int | None = None,
        source_mtime_ns: int | None = None,
        metadata_title: str | None = None,
        metadata_summary: str | None = None,
        metadata_cover_url: str | None = None,
        metadata_url: str | None = None,
        identity_hint: str | None = None,
        identity_query: str | None = None,
        network_query: str | None = None,
        rename_to: str | None = None,
        series_key: str | None = None,
        status: str = "ready",
        note: str = "",
        duplicate_of: Path | None = None,
        candidates: tuple[ClassificationCandidate, ...] = (),
        *,
        identity: BookIdentity | None = None,
    ) -> None:
        if target_dir is None or target_path is None:
            raise TypeError("ClassificationPlan 需要 target_dir 和 target_path。")
        if identity is None:
            if not series_name:
                raise TypeError("ClassificationPlan 需要 identity 或 series_name。")
            identity = BookIdentity(
                title=metadata_title or identity_query or source_path.stem or series_name,
                series_name=series_name,
            )
        elif series_name and series_name != identity.series_name:
            identity = BookIdentity(
                title=identity.title,
                series_name=series_name,
                authors=identity.authors,
                volume_number=identity.volume_number,
                language=identity.language,
                tags=identity.tags,
            )
        object.__setattr__(self, "source_path", source_path)
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "target_dir", target_dir)
        object.__setattr__(self, "target_path", target_path)
        object.__setattr__(self, "resolver_source", resolver_source)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "local_guess", local_guess)
        object.__setattr__(self, "source_size", source_size)
        object.__setattr__(self, "source_mtime_ns", source_mtime_ns)
        object.__setattr__(self, "metadata_summary", metadata_summary)
        object.__setattr__(self, "metadata_cover_url", metadata_cover_url)
        object.__setattr__(self, "metadata_url", metadata_url)
        object.__setattr__(self, "identity_hint", identity_hint)
        object.__setattr__(self, "identity_query", identity_query)
        object.__setattr__(self, "network_query", network_query)
        object.__setattr__(self, "rename_to", rename_to)
        object.__setattr__(self, "series_key", series_key)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "note", note)
        object.__setattr__(self, "duplicate_of", duplicate_of)
        object.__setattr__(self, "candidates", candidates)

    @property
    def series_name(self) -> str:
        return self.identity.series_name

    @property
    def metadata_title(self) -> str:
        return self.identity.title

    @property
    def will_move(self) -> bool:
        if self.status != "ready":
            return False
        try:
            return self.source_path.resolve() != self.target_path.resolve()
        except OSError:
            return self.source_path != self.target_path
