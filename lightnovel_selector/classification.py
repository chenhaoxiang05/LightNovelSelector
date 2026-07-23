from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from .constants import (
    APP_NAME,
    APP_VERSION,
    REPORT_MAX_BYTES,
    REPORT_SCHEMA_VERSION,
    SUPPORTED_EXTENSIONS,
)
from .files import find_duplicate_files, match_custom_rule, read_identity_hint, read_local_cover_bytes
from .metadata import SeriesResolver, suggest_renamed_filename
from .models import ClassificationPlan, CustomRule, ResolveResult
from .parsing import (
    extract_book_lookup_query,
    extract_series_guess,
    identity_query_for_path,
    collapse_spaces,
    safe_folder_name,
)
from .storage import write_json_atomic


def validate_classification_root(root: Path) -> Path:
    root = root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"大文件夹不存在：{root}")
    if not root.is_dir():
        raise NotADirectoryError(f"不是文件夹：{root}")
    if root.parent == root:
        raise ValueError("为保护系统文件，请选择驱动器或共享根目录下的专用文件夹。")
    return root


def _is_supported_regular_file(path: Path) -> bool:
    try:
        return (
            not path.is_symlink()
            and path.is_file()
            and path.suffix.casefold() in SUPPORTED_EXTENSIONS
        )
    except OSError:
        return False


def find_novel_files(root: Path, recursive: bool = False) -> list[Path]:
    iterator = root.rglob("*") if recursive else root.iterdir()
    files = [path for path in iterator if _is_supported_regular_file(path)]
    return sorted(files, key=lambda item: item.name.casefold())


def unique_target_path(target_path: Path, reserved: set[Path]) -> Path:
    normalized = target_path.resolve() if target_path.exists() else target_path.absolute()
    if not target_path.exists() and normalized not in reserved:
        reserved.add(normalized)
        return target_path

    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        normalized_candidate = candidate.resolve() if candidate.exists() else candidate.absolute()
        if not candidate.exists() and normalized_candidate not in reserved:
            reserved.add(normalized_candidate)
            return candidate
        counter += 1


def classification_plan_to_report_item(
    plan: ClassificationPlan,
    *,
    actual_target_path: Path | None = None,
) -> dict:
    return {
        "source_path": str(plan.source_path),
        "target_path": str(plan.target_path),
        "actual_target_path": str(actual_target_path) if actual_target_path else None,
        "series_name": plan.series_name,
        "resolver_source": plan.resolver_source,
        "confidence": round(plan.confidence, 4),
        "status": plan.status,
        "operation": "moved" if actual_target_path else "skipped",
        "note": plan.note,
        "duplicate_of": str(plan.duplicate_of) if plan.duplicate_of else None,
        "rename_to": plan.rename_to,
        "metadata_title": plan.metadata_title,
        "metadata_url": plan.metadata_url,
    }


def write_classification_report(
    plans: list[ClassificationPlan],
    report_path: Path,
    *,
    moved: int,
    skipped: int,
    actual_targets: dict[Path, Path] | None = None,
) -> None:
    actual_targets = actual_targets or {}
    resolved_report_path = report_path.expanduser().resolve()
    report = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "schema_version": REPORT_SCHEMA_VERSION,
        "root_path": str(resolved_report_path.parent),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "total": len(plans),
            "moved": moved,
            "skipped": skipped,
            "duplicates": sum(1 for plan in plans if plan.status == "duplicate"),
            "errors": sum(1 for plan in plans if plan.status == "error"),
        },
        "items": [
            classification_plan_to_report_item(plan, actual_target_path=actual_targets.get(plan.source_path))
            for plan in plans
        ],
    }
    write_json_atomic(report_path, report)


def load_classification_report(report_path: Path) -> dict:
    try:
        if report_path.stat().st_size > REPORT_MAX_BYTES:
            raise ValueError(f"分类报告超过允许大小（{REPORT_MAX_BYTES} 字节）。")
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("分类报告格式无效：文件不是有效的 UTF-8 JSON。") from exc
    if not isinstance(report, dict):
        raise ValueError("分类报告格式无效：根节点必须是对象。")
    return report


def _resolved_child_path(path: Path, *, root_path: Path, field_name: str) -> Path:
    try:
        resolved_path = path.expanduser().resolve()
        relative_path = resolved_path.relative_to(root_path)
    except OSError as exc:
        raise ValueError(f"无法解析分类计划的 {field_name}：{exc}") from exc
    except ValueError as exc:
        raise ValueError(f"分类计划的 {field_name} 超出分类根目录。") from exc
    if not relative_path.parts:
        raise ValueError(f"分类计划的 {field_name} 不能指向分类根目录本身。")
    return resolved_path


def _validate_execution_plan(
    plans: list[ClassificationPlan],
    report_path: Path | None,
) -> None:
    if not plans:
        return
    roots = {plan.target_dir.parent.expanduser().resolve() for plan in plans}
    if len(roots) != 1:
        raise ValueError("分类计划包含多个根目录，已拒绝执行。")
    root_path = roots.pop()
    if root_path.parent == root_path:
        raise ValueError("分类计划不能直接整理驱动器或共享根目录。")
    if report_path is not None and report_path.expanduser().resolve().parent != root_path:
        raise ValueError("分类报告必须保存在分类根目录中。")
    seen_sources: set[Path] = set()
    seen_targets: set[Path] = set()
    for plan in plans:
        source_path = _resolved_child_path(plan.source_path, root_path=root_path, field_name="source_path")
        target_dir = _resolved_child_path(plan.target_dir, root_path=root_path, field_name="target_dir")
        target_path = _resolved_child_path(plan.target_path, root_path=root_path, field_name="target_path")
        if plan.will_move and target_path.parent != target_dir:
            raise ValueError("分类计划的 target_path 不在对应的 target_dir 中。")
        if source_path in seen_sources:
            raise ValueError("分类计划包含重复的源路径。")
        seen_sources.add(source_path)
        if plan.will_move:
            if target_path in seen_targets:
                raise ValueError("分类计划包含重复的目标路径。")
            seen_targets.add(target_path)
            if plan.source_path.is_symlink():
                raise ValueError("分类计划的源文件已变为符号链接，请重新扫描。")


def _report_root(report: dict, report_path: Path) -> Path:
    if report.get("app") != APP_NAME:
        raise ValueError("撤销报告格式无效：应用标识不匹配。")

    schema_version = report.get("schema_version", 1)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ValueError("撤销报告格式无效：schema_version 必须是整数。")
    if schema_version not in {1, REPORT_SCHEMA_VERSION}:
        raise ValueError(f"不支持的撤销报告版本：{schema_version}。")

    if schema_version == 1:
        return report_path.parent

    root_value = report.get("root_path")
    if not isinstance(root_value, str) or not root_value.strip():
        raise ValueError("撤销报告格式无效：缺少分类根目录。")
    root_path = Path(root_value).expanduser()
    if not root_path.is_absolute():
        raise ValueError("撤销报告格式无效：分类根目录必须是绝对路径。")
    try:
        resolved_root = root_path.resolve()
    except OSError as exc:
        raise ValueError(f"无法解析撤销报告的分类根目录：{exc}") from exc
    if report_path.parent != resolved_root:
        raise ValueError("撤销报告必须保留在生成它的分类根目录中。")
    return resolved_root


def _undo_item_path(value: object, *, field_name: str, item_number: int, root_path: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"撤销报告第 {item_number} 项缺少有效的 {field_name}。")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"撤销报告第 {item_number} 项的 {field_name} 必须是绝对路径。")
    try:
        resolved_path = path.resolve()
    except OSError as exc:
        raise ValueError(f"无法解析撤销报告第 {item_number} 项的 {field_name}：{exc}") from exc
    try:
        relative_path = resolved_path.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(f"撤销报告第 {item_number} 项的 {field_name} 超出分类根目录。") from exc
    if not relative_path.parts:
        raise ValueError(f"撤销报告第 {item_number} 项的 {field_name} 不能指向分类根目录本身。")
    return resolved_path


def _validated_undo_items(report: dict, report_path: Path) -> list[tuple[Path, Path]]:
    root_path = _report_root(report, report_path)
    items = report.get("items")
    if not isinstance(items, list):
        raise ValueError("撤销报告格式无效：items 必须是数组。")

    moved_items: list[tuple[Path, Path]] = []
    seen_sources: set[Path] = set()
    seen_targets: set[Path] = set()
    for item_number, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"撤销报告第 {item_number} 项必须是对象。")
        if item.get("operation") != "moved":
            continue
        source_path = _undo_item_path(
            item.get("source_path"),
            field_name="source_path",
            item_number=item_number,
            root_path=root_path,
        )
        target_value = item.get("actual_target_path") or item.get("target_path")
        target_path = _undo_item_path(
            target_value,
            field_name="target_path",
            item_number=item_number,
            root_path=root_path,
        )
        if source_path == target_path:
            raise ValueError(f"撤销报告第 {item_number} 项的源路径与目标路径相同。")
        if source_path in seen_sources or target_path in seen_targets:
            raise ValueError(f"撤销报告第 {item_number} 项包含重复的文件路径。")
        seen_sources.add(source_path)
        seen_targets.add(target_path)
        moved_items.append((source_path, target_path))
    return moved_items


def build_classification_plan(
    root: Path,
    *,
    recursive: bool = False,
    use_network: bool = True,
    auto_rename: bool = False,
    custom_rules: Iterable[CustomRule] | None = None,
    progress: Callable[[str], None] | None = None,
    progress_count: Callable[[int, int], None] | None = None,
) -> list[ClassificationPlan]:
    root = validate_classification_root(root)

    files = find_novel_files(root, recursive=recursive)
    duplicates = find_duplicate_files(files)
    rules = tuple(custom_rules or ())
    resolver = SeriesResolver(use_network=use_network)
    plans: list[ClassificationPlan] = []
    reserved_targets: set[Path] = set()

    for index, path in enumerate(files, start=1):
        if progress:
            progress(f"[{index}/{len(files)}] 识别：{path.name}")
        duplicate_of = duplicates.get(path)
        if duplicate_of is not None:
            local_guess = extract_series_guess(path.name)
            folder_name = safe_folder_name(local_guess)
            plans.append(
                ClassificationPlan(
                    source_path=path,
                    series_name=folder_name,
                    target_dir=root / folder_name,
                    target_path=path,
                    resolver_source="重复文件检测",
                    confidence=1.0,
                    local_guess=local_guess,
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
            identity_hint = read_identity_hint(path)
            identity_query = identity_query_for_path(path, identity_hint)
            custom_rule = match_custom_rule(path.name, identity_query, rules)
            if custom_rule is not None:
                result = ResolveResult(
                    series_name=safe_folder_name(custom_rule.series),
                    source="自定义规则",
                    confidence=1.0,
                    local_guess=identity_query,
                )
            else:
                result = resolver.resolve(identity_query)
            folder_name = safe_folder_name(result.series_name)
            target_dir = root / folder_name
            metadata = None
            rename_to = None
            target_name = path.name
            if auto_rename and use_network:
                metadata = resolver.resolve_book_metadata_for_query(identity_query, series_name=folder_name)
                rename_to = suggest_renamed_filename(
                    path,
                    series_name=folder_name,
                    metadata=metadata,
                    identity_query=identity_query,
                )
                target_name = rename_to
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
                    series_name=folder_name,
                    target_dir=target_dir,
                    target_path=target_path,
                    resolver_source=result.source,
                    confidence=result.confidence,
                    local_guess=result.local_guess,
                    metadata_title=(metadata.title if metadata else result.metadata_title),
                    metadata_summary=(metadata.summary if metadata else result.metadata_summary),
                    metadata_cover_url=(metadata.cover_url if metadata else result.metadata_cover_url),
                    metadata_url=(metadata.url if metadata else result.metadata_url),
                    local_cover_bytes=read_local_cover_bytes(path),
                    identity_hint=identity_hint,
                    identity_query=identity_query,
                    rename_to=rename_to,
                    series_key=folder_name,
                    status=status,
                    note=note,
                )
            )
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            local_guess = extract_series_guess(path.name)
            folder_name = safe_folder_name(local_guess)
            plans.append(
                ClassificationPlan(
                    source_path=path,
                    series_name=folder_name,
                    target_dir=root / folder_name,
                    target_path=path,
                    resolver_source="文件读取失败",
                    confidence=0.0,
                    local_guess=local_guess,
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
        series_name=folder_name,
        target_dir=target_dir,
        target_path=target_path,
        resolver_source="手动修正",
        confidence=1.0,
        metadata_title=None,
        metadata_summary=None,
        metadata_cover_url=None,
        metadata_url=None,
        rename_to=None,
        series_key=folder_name,
        status=status,
        note=note,
        duplicate_of=None,
    )


def execute_classification_plan(
    plans: list[ClassificationPlan],
    *,
    progress: Callable[[str], None] | None = None,
    progress_count: Callable[[int, int], None] | None = None,
    report_path: Path | None = None,
) -> tuple[int, int]:
    _validate_execution_plan(plans, report_path)
    moved = 0
    skipped = 0
    actual_targets: dict[Path, Path] = {}
    if report_path is not None:
        write_classification_report(plans, report_path, moved=0, skipped=0, actual_targets=actual_targets)
    try:
        for index, plan in enumerate(plans, start=1):
            if not plan.will_move:
                skipped += 1
                if progress_count:
                    progress_count(index, len(plans))
                continue
            if progress:
                progress(f"[{index}/{len(plans)}] 移动：{plan.source_path.name} -> {plan.target_dir.name}")
            plan.target_dir.mkdir(parents=True, exist_ok=True)
            final_target = unique_target_path(plan.target_path, set()) if plan.target_path.exists() else plan.target_path
            shutil.move(str(plan.source_path), str(final_target))
            actual_targets[plan.source_path] = final_target
            moved += 1
            if report_path is not None:
                write_classification_report(
                    plans,
                    report_path,
                    moved=moved,
                    skipped=skipped,
                    actual_targets=actual_targets,
                )
            if progress_count:
                progress_count(index, len(plans))
    except Exception as exc:
        if report_path is not None:
            try:
                write_classification_report(
                    plans,
                    report_path,
                    moved=moved,
                    skipped=skipped,
                    actual_targets=actual_targets,
                )
            except OSError as report_exc:
                raise RuntimeError(
                    f"分类中断，且部分撤销报告无法更新：{report_exc}"
                ) from exc
        raise
    if report_path is not None:
        write_classification_report(plans, report_path, moved=moved, skipped=skipped, actual_targets=actual_targets)
    return moved, skipped


def undo_classification_report(
    report_path: Path,
    *,
    progress: Callable[[str], None] | None = None,
    progress_count: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    report_path = report_path.expanduser().resolve()
    report = load_classification_report(report_path)
    moved_items = list(reversed(_validated_undo_items(report, report_path)))
    restored = 0
    skipped = 0
    for index, (source_path, target_path) in enumerate(moved_items, start=1):
        if not target_path.exists() or source_path.exists():
            skipped += 1
            if progress_count:
                progress_count(index, len(moved_items))
            continue
        if progress:
            progress(f"撤销：{target_path.name} -> {source_path}")
        source_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target_path), str(source_path))
        restored += 1
        try:
            if not any(target_path.parent.iterdir()):
                target_path.parent.rmdir()
        except OSError:
            pass
        if progress_count:
            progress_count(index, len(moved_items))
    return restored, skipped


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
