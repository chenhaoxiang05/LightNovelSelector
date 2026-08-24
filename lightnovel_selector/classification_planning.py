from __future__ import annotations

import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from .cancellation import OperationCancelled
from .classification_discovery import find_novel_files, validate_classification_root
from .constants import SERIES_NAME_MAX_CHARS
from .corrections import RecognitionCorrectionMemory
from .files import (
    file_fingerprint,
    find_duplicate_files,
    match_custom_rule,
    read_book_identity,
    read_identity_hint,
)
from .identity import (
    identity_from_filename,
    merge_book_identities,
    merge_classification_candidates,
    with_series_name,
)
from .metadata import SeriesResolver, suggest_renamed_filename
from .models import (
    BookIdentity,
    BookMetadata,
    ClassificationCandidate,
    ClassificationPlan,
    CustomRule,
    ResolveResult,
)
from .parsing import (
    collapse_spaces,
    extract_book_lookup_query,
    extract_series_guess,
    identity_query_for_path,
    normalize_for_match,
    safe_folder_name,
    weak_file_name_query,
)
from .provider_reliability import ProviderReliabilityController
from .providers import MetadataProvider, MetadataProviderRegistry
from .recognition import RecognitionAssessment, assess_recognition
from .scan_cache import FileSnapshot, LocalFileAnalysis, PersistentScanCache, capture_file_snapshot


def unique_target_path(target_path: Path, reserved: set[Path]) -> Path:
    normalized = target_path.absolute()
    occupied = target_path.exists() or target_path.is_symlink()
    if not occupied and normalized not in reserved:
        reserved.add(normalized)
        return target_path

    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        normalized_candidate = candidate.absolute()
        occupied = candidate.exists() or candidate.is_symlink()
        if not occupied and normalized_candidate not in reserved:
            reserved.add(normalized_candidate)
            return candidate
        counter += 1


@dataclass(frozen=True, slots=True)
class _PlannerConfig:
    root: Path
    recursive: bool
    use_network: bool
    auto_rename: bool
    custom_rules: Iterable[CustomRule] | None
    progress: Callable[[str], None] | None
    progress_count: Callable[[int, int], None] | None
    checkpoint: Callable[[], None] | None
    scan_cache: PersistentScanCache | None
    metadata_providers: Iterable[MetadataProvider] | MetadataProviderRegistry | None
    correction_memory: RecognitionCorrectionMemory | None
    provider_reliability: ProviderReliabilityController | None


@dataclass(slots=True)
class _SourceDetails:
    size: int | None
    mtime_ns: int | None


@dataclass(frozen=True, slots=True)
class _LocalRecognition:
    identity_hint: str | None
    identity_query: str
    identity: BookIdentity
    used_content_hint: bool


@dataclass(frozen=True, slots=True)
class _RenameDecision:
    metadata: BookMetadata | None
    rename_to: str | None
    target_name: str


@dataclass(frozen=True, slots=True)
class _RecognitionData:
    identity: BookIdentity
    assessment: RecognitionAssessment
    candidates: tuple[ClassificationCandidate, ...]


@dataclass(frozen=True, slots=True)
class _TargetDecision:
    path: Path
    status: str
    note: str


class _ClassificationPlanner:
    def __init__(self, config: _PlannerConfig) -> None:
        self._config = config
        self._rules: tuple[CustomRule, ...] = ()
        self._resolver: SeriesResolver
        self._reserved_targets: set[Path] = set()
        self._duplicate_fingerprints: dict[Path, str | None] = {}

    def build(self) -> list[ClassificationPlan]:
        files, duplicates = self._discover_files()
        self._rules = tuple(self._config.custom_rules or ())
        self._resolver = SeriesResolver(
            use_network=self._config.use_network,
            providers=self._config.metadata_providers,
            reliability=self._config.provider_reliability,
            checkpoint=self._config.checkpoint,
        )
        plans: list[ClassificationPlan] = []
        total = len(files)
        for index, path in enumerate(files, start=1):
            source = self._read_source_details(path)
            if self._config.progress:
                self._config.progress(f"[{index}/{total}] 识别：{path.name}")
            plans.append(self._build_file_plan(path, duplicates.get(path), source))
            if self._config.progress_count:
                self._config.progress_count(index, total)
        return plans

    def _discover_files(self) -> tuple[list[Path], dict[Path, Path]]:
        if self._config.progress:
            self._config.progress("正在查找支持的小说文件…")
        files = find_novel_files(
            self._config.root,
            recursive=self._config.recursive,
            checkpoint=self._config.checkpoint,
        )
        if files and self._config.progress:
            self._config.progress(f"正在检查 {len(files)} 个文件的重复内容…")
        duplicates = find_duplicate_files(
            files,
            checkpoint=self._config.checkpoint,
            scan_cache=self._config.scan_cache,
        )
        return files, duplicates

    @staticmethod
    def _read_source_details(path: Path) -> _SourceDetails:
        try:
            source_stat = path.stat()
        except OSError:
            return _SourceDetails(size=None, mtime_ns=None)
        return _SourceDetails(size=source_stat.st_size, mtime_ns=source_stat.st_mtime_ns)

    def _build_file_plan(
        self,
        path: Path,
        duplicate_of: Path | None,
        source: _SourceDetails,
    ) -> ClassificationPlan:
        duplicate_of = self._confirm_duplicate(path, duplicate_of)
        if duplicate_of is not None:
            return self._build_duplicate_plan(path, duplicate_of, source)
        try:
            return self._build_ready_plan(path, source)
        except OperationCancelled:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            return self._build_error_plan(path, source, exc)

    def _confirm_duplicate(self, path: Path, duplicate_of: Path | None) -> Path | None:
        if duplicate_of is None:
            return None
        candidate_fingerprint = self._current_fingerprint(path)
        original_fingerprint = self._current_fingerprint(duplicate_of)
        if candidate_fingerprint is None or candidate_fingerprint != original_fingerprint:
            return None
        return duplicate_of

    def _current_fingerprint(self, path: Path) -> str | None:
        if path not in self._duplicate_fingerprints:
            try:
                self._duplicate_fingerprints[path] = file_fingerprint(
                    path,
                    checkpoint=self._config.checkpoint,
                    scan_cache=self._config.scan_cache,
                )
            except OSError:
                self._duplicate_fingerprints[path] = None
        return self._duplicate_fingerprints[path]

    def _build_duplicate_plan(
        self,
        path: Path,
        duplicate_of: Path,
        source: _SourceDetails,
    ) -> ClassificationPlan:
        identity = identity_from_filename(path.name)
        local_guess = identity.series_name
        folder_name = safe_folder_name(identity.series_name)
        return ClassificationPlan(
            source_path=path,
            identity=with_series_name(identity, folder_name),
            target_dir=self._config.root / folder_name,
            target_path=path,
            resolver_source="重复文件检测",
            confidence=1.0,
            confidence_level="高",
            classification_reason="完整文件指纹与已扫描文件一致，因此标记为重复并默认跳过。",
            classification_evidence=("完整 SHA-256 内容一致",),
            local_guess=local_guess,
            source_size=source.size,
            source_mtime_ns=source.mtime_ns,
            identity_query=extract_book_lookup_query(path.name),
            series_key=folder_name,
            status="duplicate",
            note=f"与 {duplicate_of.name} 内容重复，默认跳过。",
            duplicate_of=duplicate_of,
        )

    def _build_ready_plan(self, path: Path, source: _SourceDetails) -> ClassificationPlan:
        file_query = extract_book_lookup_query(path.name)
        local = self._load_local_recognition(path, file_query, source)
        network_query, result = self._resolve_series(path, file_query, local)
        folder_name = safe_folder_name(result.series_name)
        target_dir = self._config.root / folder_name
        rename = self._resolve_rename(path, folder_name, local.identity_query, network_query)
        recognition = self._merge_recognition(local, result, rename.metadata, folder_name)
        target = self._select_target(path, target_dir / rename.target_name)
        return ClassificationPlan(
            source_path=path,
            identity=recognition.identity,
            target_dir=target_dir,
            target_path=target.path,
            resolver_source=result.source,
            confidence=recognition.assessment.confidence,
            confidence_level=recognition.assessment.level,
            classification_reason=recognition.assessment.reason,
            classification_evidence=recognition.assessment.evidence,
            local_guess=result.local_guess,
            source_size=source.size,
            source_mtime_ns=source.mtime_ns,
            metadata_summary=(rename.metadata.summary if rename.metadata else result.metadata_summary),
            metadata_cover_url=(rename.metadata.cover_url if rename.metadata else result.metadata_cover_url),
            metadata_url=(rename.metadata.url if rename.metadata else result.metadata_url),
            identity_hint=local.identity_hint,
            identity_query=local.identity_query,
            network_query=network_query,
            rename_to=rename.rename_to,
            series_key=folder_name,
            status=target.status,
            note=target.note,
            candidates=recognition.candidates,
        )

    def _load_local_recognition(
        self,
        path: Path,
        file_query: str,
        source: _SourceDetails,
    ) -> _LocalRecognition:
        cached, initial_snapshot = self._load_cached_analysis(path, source)
        if cached is not None:
            return _LocalRecognition(
                identity_hint=None,
                identity_query=cached.identity_query,
                identity=cached.identity,
                used_content_hint=cached.used_content_hint,
            )

        identity_hint = read_identity_hint(path)
        identity_query = identity_query_for_path(path, identity_hint)
        local_identity = read_book_identity(path, identity_hint)
        used_content_hint = bool(identity_hint and identity_query != file_query)
        self._remember_local_analysis(
            path,
            initial_snapshot,
            identity_hint,
            LocalFileAnalysis(
                identity=local_identity,
                identity_query=identity_query,
                used_content_hint=used_content_hint,
            ),
        )
        return _LocalRecognition(
            identity_hint=identity_hint,
            identity_query=identity_query,
            identity=local_identity,
            used_content_hint=used_content_hint,
        )

    def _load_cached_analysis(
        self,
        path: Path,
        source: _SourceDetails,
    ) -> tuple[LocalFileAnalysis | None, FileSnapshot | None]:
        scan_cache = self._config.scan_cache
        if scan_cache is None:
            return None, None
        self._checkpoint()
        initial_snapshot = capture_file_snapshot(path)
        source.size = initial_snapshot.size
        source.mtime_ns = initial_snapshot.mtime_ns
        cached = scan_cache.get_local_analysis(path, initial_snapshot)
        if cached is not None:
            self._checkpoint()
            if capture_file_snapshot(path) != initial_snapshot:
                raise OSError(f"文件在读取缓存识别结果时发生变化：{path}")
        return cached, initial_snapshot

    def _remember_local_analysis(
        self,
        path: Path,
        initial_snapshot: FileSnapshot | None,
        identity_hint: str | None,
        analysis: LocalFileAnalysis,
    ) -> None:
        scan_cache = self._config.scan_cache
        if scan_cache is None or not identity_hint or initial_snapshot is None or not initial_snapshot.cacheable:
            return
        final_snapshot = capture_file_snapshot(path)
        if final_snapshot != initial_snapshot:
            raise OSError(f"文件在读取本地识别信息时发生变化：{path}")
        scan_cache.remember_local_analysis(path, final_snapshot, analysis)

    def _checkpoint(self) -> None:
        if self._config.checkpoint:
            self._config.checkpoint()

    def _resolve_series(
        self,
        path: Path,
        file_query: str,
        local: _LocalRecognition,
    ) -> tuple[str | None, ResolveResult]:
        network_query = None if weak_file_name_query(path.name) else file_query
        custom_rule = match_custom_rule(path.name, local.identity_query, self._rules)
        remembered_alias = (
            self._config.correction_memory.lookup(
                local.identity.series_name,
                extract_series_guess(local.identity_query),
            )
            if self._config.correction_memory is not None
            else None
        )
        if custom_rule is not None:
            network_query = custom_rule.series
            return network_query, ResolveResult(
                identity=with_series_name(local.identity, custom_rule.series),
                source="自定义规则",
                confidence=1.0,
                local_guess=local.identity_query,
            )
        if remembered_alias is not None:
            if network_query is not None:
                network_query = remembered_alias.canonical_series
            return network_query, ResolveResult(
                identity=with_series_name(local.identity, remembered_alias.canonical_series),
                source="本地修正记忆",
                confidence=0.99,
                local_guess=local.identity_query,
            )
        if network_query is None:
            return None, ResolveResult(
                identity=with_series_name(
                    local.identity,
                    extract_series_guess(local.identity_query),
                ),
                source="本地内容提示" if local.used_content_hint else "本地规则",
                confidence=0.6 if local.used_content_hint else 0.45,
                local_guess=local.identity_query,
            )
        return network_query, self._apply_resolved_alias(self._resolver.resolve(network_query))

    def _apply_resolved_alias(self, result: ResolveResult) -> ResolveResult:
        if self._config.correction_memory is None:
            return result
        resolved_alias = self._config.correction_memory.lookup(result.series_name)
        if resolved_alias is None:
            return result
        return ResolveResult(
            identity=with_series_name(result.identity, resolved_alias.canonical_series),
            source="本地修正记忆",
            confidence=0.99,
            local_guess=result.local_guess,
            metadata_summary=result.metadata_summary,
            metadata_cover_url=result.metadata_cover_url,
            metadata_url=result.metadata_url,
        )

    def _resolve_rename(
        self,
        path: Path,
        folder_name: str,
        identity_query: str,
        network_query: str | None,
    ) -> _RenameDecision:
        if not (self._config.auto_rename and self._config.use_network and network_query):
            return _RenameDecision(metadata=None, rename_to=None, target_name=path.name)
        metadata = self._resolver.resolve_book_metadata_for_query(network_query, series_name=folder_name)
        rename_to = suggest_renamed_filename(
            path,
            series_name=folder_name,
            metadata=metadata,
            identity_query=identity_query,
        )
        return _RenameDecision(metadata=metadata, rename_to=rename_to, target_name=rename_to)

    @staticmethod
    def _merge_recognition(
        local: _LocalRecognition,
        result: ResolveResult,
        metadata: BookMetadata | None,
        folder_name: str,
    ) -> _RecognitionData:
        identity = merge_book_identities(
            local.identity,
            replace(
                result.identity,
                title=local.identity.title,
                volume_number=local.identity.volume_number,
            ),
            metadata.identity if metadata else None,
            series_name=folder_name,
        )
        assessment = assess_recognition(
            raw_confidence=result.confidence,
            source=result.source,
            identity_query=local.identity_query,
            chosen_identity=identity,
            local_identity=local.identity,
            used_content_hint=local.used_content_hint,
            has_book_metadata=metadata is not None,
        )
        candidates = merge_classification_candidates(
            (
                ClassificationCandidate(
                    identity=identity,
                    source=result.source,
                    confidence=assessment.confidence,
                ),
            ),
            (
                ClassificationCandidate(
                    identity=metadata.identity,
                    source=metadata.source,
                    confidence=metadata.confidence,
                ),
            )
            if metadata
            else (),
            (
                ClassificationCandidate(
                    identity=local.identity,
                    source="本地识别",
                    confidence=0.55,
                ),
            ),
        )
        return _RecognitionData(identity=identity, assessment=assessment, candidates=candidates)

    def _select_target(self, path: Path, proposed_target: Path) -> _TargetDecision:
        try:
            already_classified = path.resolve() == proposed_target.resolve()
        except OSError:
            already_classified = path.absolute() == proposed_target.absolute()
        if already_classified:
            return _TargetDecision(
                path=path,
                status="unchanged",
                note="文件已在正确的系列目录中，无需移动。",
            )
        return _TargetDecision(
            path=unique_target_path(proposed_target, self._reserved_targets),
            status="ready",
            note="",
        )

    def _build_error_plan(
        self,
        path: Path,
        source: _SourceDetails,
        exc: OSError | RuntimeError | zipfile.BadZipFile,
    ) -> ClassificationPlan:
        identity = identity_from_filename(path.name)
        local_guess = identity.series_name
        folder_name = safe_folder_name(identity.series_name)
        return ClassificationPlan(
            source_path=path,
            identity=with_series_name(identity, folder_name),
            target_dir=self._config.root / folder_name,
            target_path=path,
            resolver_source="文件读取失败",
            confidence=0.0,
            confidence_level="需复核",
            classification_reason="文件读取失败，未执行自动分类。",
            classification_evidence=("读取文件或元数据时发生错误",),
            local_guess=local_guess,
            source_size=source.size,
            source_mtime_ns=source.mtime_ns,
            identity_query=extract_book_lookup_query(path.name),
            series_key=folder_name,
            status="error",
            note=str(exc),
        )


# 公开关键字参数需兼容 CLI、Sidecar 和现有调用方。
def build_classification_plan(
    root: Path,
    *,
    recursive: bool = False,
    use_network: bool = True,
    auto_rename: bool = False,
    custom_rules: Iterable[CustomRule] | None = None,
    progress: Callable[[str], None] | None = None,
    progress_count: Callable[[int, int], None] | None = None,
    checkpoint: Callable[[], None] | None = None,
    scan_cache: PersistentScanCache | None = None,
    metadata_providers: Iterable[MetadataProvider] | MetadataProviderRegistry | None = None,
    correction_memory: RecognitionCorrectionMemory | None = None,
    provider_reliability: ProviderReliabilityController | None = None,
) -> list[ClassificationPlan]:
    config = _PlannerConfig(
        root=validate_classification_root(root),
        recursive=recursive,
        use_network=use_network,
        auto_rename=auto_rename,
        custom_rules=custom_rules,
        progress=progress,
        progress_count=progress_count,
        checkpoint=checkpoint,
        scan_cache=scan_cache,
        metadata_providers=metadata_providers,
        correction_memory=correction_memory,
        provider_reliability=provider_reliability,
    )
    return _ClassificationPlanner(config).build()


def revise_classification_plan(
    plans: list[ClassificationPlan],
    index: int,
    series_name: str,
) -> ClassificationPlan:
    if index < 0 or index >= len(plans):
        raise IndexError("分类计划索引超出范围。")
    clean_series = collapse_spaces(series_name)
    if not clean_series:
        raise ValueError("系列名不能为空。")
    if len(clean_series) > SERIES_NAME_MAX_CHARS:
        raise ValueError(f"系列名不能超过 {SERIES_NAME_MAX_CHARS} 个字符。")

    plan = plans[index]
    if plan.status == "moved":
        raise ValueError("已移动的文件不能直接修改，请先撤销分类。")

    folder_name = safe_folder_name(clean_series)
    target_dir = plan.target_dir.parent / folder_name
    proposed_target = target_dir / plan.source_path.name
    try:
        unchanged = plan.source_path.resolve() == proposed_target.resolve()
    except OSError:
        unchanged = plan.source_path.absolute() == proposed_target.absolute()

    if unchanged:
        target_path = plan.source_path
        status = "unchanged"
        note = "文件已在手动指定的系列目录中，无需移动。"
    else:
        reserved = {
            other.target_path.resolve() if other.target_path.exists() else other.target_path.absolute()
            for other_index, other in enumerate(plans)
            if other_index != index and other.status == "ready"
        }
        target_path = unique_target_path(proposed_target, reserved)
        status = "ready"
        note = "已手动修正系列名。"

    return replace(
        plan,
        identity=with_series_name(plan.identity, folder_name),
        target_dir=target_dir,
        target_path=target_path,
        resolver_source="手动修正",
        confidence=1.0,
        confidence_level="高",
        classification_reason="你已在分类预览中手动确认此系列。",
        classification_evidence=("用户手动修正",),
        metadata_summary=None,
        metadata_cover_url=None,
        metadata_url=None,
        network_query=folder_name,
        rename_to=None,
        series_key=folder_name,
        status=status,
        note=note,
        duplicate_of=None,
    )


def classification_plan_group_indices(
    plans: list[ClassificationPlan],
    index: int,
    scope: Literal["single", "same_series"],
) -> tuple[int, ...]:
    if index < 0 or index >= len(plans):
        raise IndexError("分类计划索引超出范围。")
    if scope == "single":
        return (index,)
    if scope != "same_series":
        raise ValueError("批量修正范围无效。")

    anchor = plans[index]
    anchor_key = normalize_for_match(anchor.series_key or anchor.series_name)
    if not anchor_key:
        return (index,)
    return tuple(
        plan_index
        for plan_index, plan in enumerate(plans)
        if normalize_for_match(plan.series_key or plan.series_name) == anchor_key
    )


def revise_classification_plans(
    plans: list[ClassificationPlan],
    index: int,
    series_name: str,
    *,
    scope: Literal["single", "same_series"] = "single",
) -> tuple[int, ...]:
    indices = classification_plan_group_indices(plans, index, scope)
    revised_plans = list(plans)
    for plan_index in indices:
        revised_plans[plan_index] = revise_classification_plan(
            revised_plans,
            plan_index,
            series_name,
        )
    plans[:] = revised_plans
    return indices


def plan_status_label(status: str) -> str:
    return {
        "ready": "可执行",
        "duplicate": "重复",
        "error": "错误",
        "moved": "已移动",
        "unchanged": "无需移动",
    }.get(status, status)


def count_plan_statuses(plans: Iterable[ClassificationPlan]) -> dict[str, int]:
    counts = {"total": 0, "ready": 0, "duplicate": 0, "error": 0}
    for plan in plans:
        counts["total"] += 1
        if plan.status in counts:
            counts[plan.status] += 1
    return counts
