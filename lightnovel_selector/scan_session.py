from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from .classification_planning import build_classification_plan
from .corrections import RecognitionCorrectionMemory
from .models import AppSettings, ClassificationPlan
from .provider_reliability import ProviderReliabilityController
from .providers import MetadataProvider, MetadataProviderRegistry
from .scan_cache import PersistentScanCache, ScanCacheStats

PlanBuilder = Callable[..., list[ClassificationPlan]]
ScanCacheFactory = Callable[[], PersistentScanCache]


class OperationCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class ScanSessionResult:
    plans: list[ClassificationPlan]
    cache_stats: ScanCacheStats


class ScanSession:
    """Run one cancellable scan without owning UI state or worker threads."""

    def __init__(
        self,
        folder: Path,
        settings: AppSettings,
        *,
        metadata_providers: Iterable[MetadataProvider] | MetadataProviderRegistry,
        correction_memory: RecognitionCorrectionMemory,
        cancel_event: threading.Event,
        provider_reliability: ProviderReliabilityController | None = None,
        on_message: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        plan_builder: PlanBuilder = build_classification_plan,
        scan_cache_factory: ScanCacheFactory = PersistentScanCache,
    ) -> None:
        self.folder = folder
        self.settings = settings
        self.metadata_providers = metadata_providers
        self.correction_memory = correction_memory
        self.provider_reliability = provider_reliability or ProviderReliabilityController()
        self.cancel_event = cancel_event
        self.on_message = on_message
        self.on_progress = on_progress
        self._plan_builder = plan_builder
        self._scan_cache_factory = scan_cache_factory
        self.cache_stats = ScanCacheStats()

    def checkpoint(self) -> None:
        if self.cancel_event.is_set():
            raise OperationCancelled("扫描已取消。")

    def _message(self, message: str) -> None:
        self.checkpoint()
        if self.on_message is not None:
            self.on_message(message)

    def _progress(self, done: int, total: int) -> None:
        self.checkpoint()
        if self.on_progress is not None:
            self.on_progress(done, total)

    def run(self) -> ScanSessionResult:
        scan_cache: PersistentScanCache | None = None
        try:
            scan_cache = self._scan_cache_factory()
        except OSError as exc:
            self.cache_stats = ScanCacheStats(write_warning=str(exc)[:2000])

        try:
            with scan_cache if scan_cache is not None else nullcontext():
                plans = self._plan_builder(
                    self.folder,
                    recursive=self.settings.recursive,
                    use_network=self.settings.use_network,
                    auto_rename=self.settings.auto_rename,
                    custom_rules=self.settings.custom_rules,
                    progress=self._message,
                    progress_count=self._progress,
                    checkpoint=self.checkpoint,
                    scan_cache=scan_cache,
                    metadata_providers=self.metadata_providers,
                    correction_memory=self.correction_memory,
                    provider_reliability=self.provider_reliability,
                )
            if scan_cache is not None:
                self.cache_stats = scan_cache.stats
            self.checkpoint()
            return ScanSessionResult(plans=plans, cache_stats=self.cache_stats)
        finally:
            if scan_cache is not None:
                self.cache_stats = scan_cache.stats
