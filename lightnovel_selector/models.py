from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResolveResult:
    series_name: str
    source: str
    confidence: float
    local_guess: str
    metadata_title: str | None = None
    metadata_summary: str | None = None
    metadata_cover_url: str | None = None
    metadata_url: str | None = None


@dataclass(frozen=True)
class BookMetadata:
    title: str
    source: str
    confidence: float
    query: str
    summary: str | None = None
    cover_url: str | None = None
    url: str | None = None


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


@dataclass(frozen=True)
class ClassificationPlan:
    source_path: Path
    series_name: str
    target_dir: Path
    target_path: Path
    resolver_source: str
    confidence: float
    local_guess: str
    metadata_title: str | None = None
    metadata_summary: str | None = None
    metadata_cover_url: str | None = None
    metadata_url: str | None = None
    local_cover_bytes: bytes | None = None
    identity_hint: str | None = None
    identity_query: str | None = None
    rename_to: str | None = None
    series_key: str | None = None
    status: str = "ready"
    note: str = ""
    duplicate_of: Path | None = None

    @property
    def will_move(self) -> bool:
        if self.status != "ready":
            return False
        try:
            return self.source_path.resolve() != self.target_path.resolve()
        except OSError:
            return self.source_path != self.target_path

    @property
    def has_warning(self) -> bool:
        return self.status != "ready" or bool(self.note)
