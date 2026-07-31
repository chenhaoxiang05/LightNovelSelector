from __future__ import annotations

import zipfile
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import Literal

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
from .models import ClassificationCandidate, ClassificationPlan, CustomRule, ResolveResult
from .parsing import (
    collapse_spaces,
    extract_book_lookup_query,
    extract_series_guess,
    identity_query_for_path,
    normalize_for_match,
    safe_folder_name,
    weak_file_name_query,
)
from .providers import MetadataProvider, MetadataProviderRegistry
from .recognition import assess_recognition
from .scan_cache import LocalFileAnalysis, PersistentScanCache, capture_file_snapshot


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
) -> list[ClassificationPlan]:
    root = validate_classification_root(root)

    if progress:
        progress("正在查找支持的小说文件…")
    files = find_novel_files(
        root,
        recursive=recursive,
        checkpoint=checkpoint,
    )
    if files and progress:
        progress(f"正在检查 {len(files)} 个文件的重复内容…")

    duplicates = find_duplicate_files(
        files,
        checkpoint=checkpoint,
        scan_cache=scan_cache,
    )
    rules = tuple(custom_rules or ())
    resolver = SeriesResolver(
        use_network=use_network,
        providers=metadata_providers,
    )
    plans: list[ClassificationPlan] = []
    reserved_targets: set[Path] = set()
    duplicate_fingerprints: dict[Path, str | None] = {}

    def current_fingerprint(path: Path) -> str | None:
        if path not in duplicate_fingerprints:
            try:
                duplicate_fingerprints[path] = file_fingerprint(
                    path,
                    checkpoint=checkpoint,
                    scan_cache=scan_cache,
                )
            except OSError:
                duplicate_fingerprints[path] = None
        return duplicate_fingerprints[path]

    for index, path in enumerate(files, start=1):
        try:
            source_stat = path.stat()
        except OSError:
            source_stat = None
        source_size = source_stat.st_size if source_stat else None
        source_mtime_ns = source_stat.st_mtime_ns if source_stat else None
        if progress:
            progress(f"[{index}/{len(files)}] 识别：{path.name}")
        duplicate_of = duplicates.get(path)
        if duplicate_of is not None:
            candidate_fingerprint = current_fingerprint(path)
            original_fingerprint = current_fingerprint(duplicate_of)
            if candidate_fingerprint is None or candidate_fingerprint != original_fingerprint:
                duplicate_of = None
        if duplicate_of is not None:
            identity = identity_from_filename(path.name)
            local_guess = identity.series_name
            folder_name = safe_folder_name(identity.series_name)
            plans.append(
                ClassificationPlan(
                    source_path=path,
                    identity=with_series_name(identity, folder_name),
                    target_dir=root / folder_name,
                    target_path=path,
                    resolver_source="重复文件检测",
                    confidence=1.0,
                    confidence_level="高",
                    classification_reason="完整文件指纹与已扫描文件一致，因此标记为重复并默认跳过。",
                    classification_evidence=("完整 SHA-256 内容一致",),
                    local_guess=local_guess,
                    source_size=source_size,
                    source_mtime_ns=source_mtime_ns,
                    identity_query=extract_book_lookup_query(path.name),
                    series_key=folder_name,
                    status="duplicate",
                    note=f"与 {duplicate_of.name} 内容重复，默认跳过。",
                    duplicate_of=duplicate_of,
                )
            )
            if progress_count:
                progress_count(index, len(files))
            continue

        try:
            file_query = extract_book_lookup_query(path.name)
            identity_hint: str | None = None
            cached_local_analysis = None
            initial_snapshot = None
            if scan_cache is not None:
                if checkpoint:
                    checkpoint()
                initial_snapshot = capture_file_snapshot(path)
                source_size = initial_snapshot.size
                source_mtime_ns = initial_snapshot.mtime_ns
                cached_local_analysis = scan_cache.get_local_analysis(path, initial_snapshot)
                if cached_local_analysis is not None:
                    if checkpoint:
                        checkpoint()
                    if capture_file_snapshot(path) != initial_snapshot:
                        raise OSError(f"文件在读取缓存识别结果时发生变化：{path}")

            if cached_local_analysis is not None:
                identity_query = cached_local_analysis.identity_query
                local_identity = cached_local_analysis.identity
                used_content_hint = cached_local_analysis.used_content_hint
            else:
                identity_hint = read_identity_hint(path)
                identity_query = identity_query_for_path(path, identity_hint)
                local_identity = read_book_identity(path, identity_hint)
                used_content_hint = bool(identity_hint and identity_query != file_query)
                if (
                    scan_cache is not None
                    and identity_hint
                    and initial_snapshot is not None
                    and initial_snapshot.cacheable
                ):
                    final_snapshot = capture_file_snapshot(path)
                    if final_snapshot != initial_snapshot:
                        raise OSError(f"文件在读取本地识别信息时发生变化：{path}")
                    scan_cache.remember_local_analysis(
                        path,
                        final_snapshot,
                        LocalFileAnalysis(
                            identity=local_identity,
                            identity_query=identity_query,
                            used_content_hint=used_content_hint,
                        ),
                    )
            network_query = None if weak_file_name_query(path.name) else file_query
            custom_rule = match_custom_rule(path.name, identity_query, rules)
            remembered_alias = (
                correction_memory.lookup(
                    local_identity.series_name,
                    extract_series_guess(identity_query),
                )
                if correction_memory is not None
                else None
            )
            if custom_rule is not None:
                network_query = custom_rule.series
                result = ResolveResult(
                    identity=with_series_name(local_identity, custom_rule.series),
                    source="自定义规则",
                    confidence=1.0,
                    local_guess=identity_query,
                )
            elif remembered_alias is not None:
                if network_query is not None:
                    network_query = remembered_alias.canonical_series
                result = ResolveResult(
                    identity=with_series_name(
                        local_identity,
                        remembered_alias.canonical_series,
                    ),
                    source="本地修正记忆",
                    confidence=0.99,
                    local_guess=identity_query,
                )
            elif network_query is None:
                result = ResolveResult(
                    identity=with_series_name(
                        local_identity,
                        extract_series_guess(identity_query),
                    ),
                    source="本地内容提示" if used_content_hint else "本地规则",
                    confidence=0.6 if used_content_hint else 0.45,
                    local_guess=identity_query,
                )
            else:
                result = resolver.resolve(network_query)
                if correction_memory is not None:
                    resolved_alias = correction_memory.lookup(result.series_name)
                    if resolved_alias is not None:
                        result = ResolveResult(
                            identity=with_series_name(
                                result.identity,
                                resolved_alias.canonical_series,
                            ),
                            source="本地修正记忆",
                            confidence=0.99,
                            local_guess=result.local_guess,
                            metadata_summary=result.metadata_summary,
                            metadata_cover_url=result.metadata_cover_url,
                            metadata_url=result.metadata_url,
                        )
            folder_name = safe_folder_name(result.series_name)
            target_dir = root / folder_name
            metadata = None
            rename_to = None
            target_name = path.name
            if auto_rename and use_network and network_query:
                metadata = resolver.resolve_book_metadata_for_query(network_query, series_name=folder_name)
                rename_to = suggest_renamed_filename(
                    path,
                    series_name=folder_name,
                    metadata=metadata,
                    identity_query=identity_query,
                )
                target_name = rename_to
            identity = merge_book_identities(
                local_identity,
                replace(
                    result.identity,
                    title=local_identity.title,
                    volume_number=local_identity.volume_number,
                ),
                metadata.identity if metadata else None,
                series_name=folder_name,
            )
            assessment = assess_recognition(
                raw_confidence=result.confidence,
                source=result.source,
                identity_query=identity_query,
                chosen_identity=identity,
                local_identity=local_identity,
                used_content_hint=used_content_hint,
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
                        identity=local_identity,
                        source="本地识别",
                        confidence=0.55,
                    ),
                ),
            )
            proposed_target_path = target_dir / target_name
            try:
                already_classified = path.resolve() == proposed_target_path.resolve()
            except OSError:
                already_classified = path.absolute() == proposed_target_path.absolute()
            if already_classified:
                target_path = path
                status = "unchanged"
                note = "文件已在正确的系列目录中，无需移动。"
            else:
                target_path = unique_target_path(proposed_target_path, reserved_targets)
                status = "ready"
                note = ""
            plans.append(
                ClassificationPlan(
                    source_path=path,
                    identity=identity,
                    target_dir=target_dir,
                    target_path=target_path,
                    resolver_source=result.source,
                    confidence=assessment.confidence,
                    confidence_level=assessment.level,
                    classification_reason=assessment.reason,
                    classification_evidence=assessment.evidence,
                    local_guess=result.local_guess,
                    source_size=source_size,
                    source_mtime_ns=source_mtime_ns,
                    metadata_summary=(metadata.summary if metadata else result.metadata_summary),
                    metadata_cover_url=(metadata.cover_url if metadata else result.metadata_cover_url),
                    metadata_url=(metadata.url if metadata else result.metadata_url),
                    identity_hint=identity_hint,
                    identity_query=identity_query,
                    network_query=network_query,
                    rename_to=rename_to,
                    series_key=folder_name,
                    status=status,
                    note=note,
                    candidates=candidates,
                )
            )
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            identity = identity_from_filename(path.name)
            local_guess = identity.series_name
            folder_name = safe_folder_name(identity.series_name)
            plans.append(
                ClassificationPlan(
                    source_path=path,
                    identity=with_series_name(identity, folder_name),
                    target_dir=root / folder_name,
                    target_path=path,
                    resolver_source="文件读取失败",
                    confidence=0.0,
                    confidence_level="需复核",
                    classification_reason="文件读取失败，未执行自动分类。",
                    classification_evidence=("读取文件或元数据时发生错误",),
                    local_guess=local_guess,
                    source_size=source_size,
                    source_mtime_ns=source_mtime_ns,
                    identity_query=extract_book_lookup_query(path.name),
                    series_key=folder_name,
                    status="error",
                    note=str(exc),
                )
            )
        if progress_count:
            progress_count(index, len(files))

    return plans


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
