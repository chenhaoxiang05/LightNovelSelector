from __future__ import annotations

import json
import shutil
import threading
import uuid
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .constants import (
    APP_NAME,
    APP_VERSION,
    REPORT_JOURNAL_MAX_BYTES,
    REPORT_JOURNAL_SCHEMA_VERSION,
    REPORT_MAX_BYTES,
    REPORT_SCHEMA_VERSION,
    SCAN_MAX_ENTRIES,
    SCAN_MAX_FILES,
    SERIES_NAME_MAX_CHARS,
    SUPPORTED_EXTENSIONS,
)
from .files import (
    file_fingerprint,
    find_duplicate_files,
    match_custom_rule,
    read_identity_hint,
)
from .metadata import SeriesResolver, suggest_renamed_filename
from .models import ClassificationPlan, CustomRule, ResolveResult
from .parsing import (
    collapse_spaces,
    extract_book_lookup_query,
    extract_series_guess,
    identity_query_for_path,
    safe_folder_name,
    weak_file_name_query,
)
from .storage import append_json_line_durable, write_json_atomic, write_json_lines_exclusive

_ACTIVE_REPORT_PATHS: set[Path] = set()
_ACTIVE_REPORT_PATHS_LOCK = threading.Lock()


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


def find_novel_files(
    root: Path,
    recursive: bool = False,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> list[Path]:
    root = root.expanduser().resolve()
    iterator = root.rglob("*") if recursive else root.iterdir()
    files: list[Path] = []
    for inspected, path in enumerate(iterator, start=1):
        if checkpoint:
            checkpoint()
        if inspected > SCAN_MAX_ENTRIES:
            raise ValueError(
                f"单次扫描最多检查 {SCAN_MAX_ENTRIES} 个目录项，请缩小目录范围后重试。"
            )
        if not _is_supported_regular_file(path):
            continue
        if recursive:
            try:
                path.resolve().relative_to(root)
            except (OSError, ValueError):
                continue
        files.append(path)
        if len(files) > SCAN_MAX_FILES:
            raise ValueError(
                f"单次扫描最多支持 {SCAN_MAX_FILES} 个小说文件，请分目录处理。"
            )

    def sort_key(item: Path) -> tuple[str, str, str]:
        relative = item.relative_to(root).as_posix()
        return item.name.casefold(), relative.casefold(), relative

    return sorted(files, key=sort_key)


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
        "source_size": plan.source_size,
        "source_mtime_ns": plan.source_mtime_ns,
    }


def write_classification_report(
    plans: list[ClassificationPlan],
    report_path: Path,
    *,
    moved: int,
    skipped: int,
    actual_targets: dict[Path, Path] | None = None,
    execution_id: str | None = None,
) -> None:
    actual_targets = actual_targets or {}
    resolved_report_path = report_path.expanduser().resolve()
    report = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "schema_version": REPORT_SCHEMA_VERSION,
        "root_path": str(resolved_report_path.parent),
        "execution_id": execution_id,
        "created_at": datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds"),
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


def _report_journal_path(report_path: Path) -> Path:
    resolved = report_path.expanduser().resolve()
    return resolved.with_name(f"{resolved.stem}.recovery.jsonl")


def _set_report_execution_active(report_path: Path, active: bool) -> None:
    with _ACTIVE_REPORT_PATHS_LOCK:
        if active:
            _ACTIVE_REPORT_PATHS.add(report_path)
        else:
            _ACTIVE_REPORT_PATHS.discard(report_path)


def _report_execution_is_active(report_path: Path) -> bool:
    with _ACTIVE_REPORT_PATHS_LOCK:
        return report_path in _ACTIVE_REPORT_PATHS


def _valid_execution_id(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 32:
        return False
    try:
        return uuid.UUID(hex=value).hex == value
    except ValueError:
        return False


def _read_classification_report(report_path: Path) -> dict:
    with report_path.open("rb") as handle:
        data = handle.read(REPORT_MAX_BYTES + 1)
    if len(data) > REPORT_MAX_BYTES:
        raise ValueError(f"分类报告超过允许大小（{REPORT_MAX_BYTES} 字节）。")
    try:
        report = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValueError("分类报告格式无效：文件不是有效的 UTF-8 JSON。") from exc
    if not isinstance(report, dict):
        raise ValueError("分类报告格式无效：根节点必须是对象。")
    return report


def load_classification_report(
    report_path: Path,
    *,
    recover_pending: bool = True,
) -> dict:
    report_path = report_path.expanduser().resolve()
    report = _read_classification_report(report_path)
    journal_path = _report_journal_path(report_path)
    if not recover_pending or (
        not journal_path.exists()
        and not journal_path.is_symlink()
    ):
        return report

    if _report_execution_is_active(report_path):
        return report
    return _recover_classification_report(report, report_path, journal_path)


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


def _validate_source_state(plan: ClassificationPlan) -> None:
    if plan.source_path.is_symlink():
        raise ValueError("分类计划的源文件已变为符号链接，请重新扫描。")
    if not plan.source_path.is_file():
        raise ValueError("分类计划的源文件已不存在或不再是普通文件，请重新扫描。")
    try:
        current_stat = plan.source_path.stat()
    except OSError as exc:
        raise ValueError(f"无法重新校验源文件：{plan.source_path}") from exc
    if (
        plan.source_size is not None
        and plan.source_mtime_ns is not None
        and (
            current_stat.st_size != plan.source_size
            or current_stat.st_mtime_ns != plan.source_mtime_ns
        )
    ):
        raise ValueError(f"源文件在扫描后发生变化，请重新扫描：{plan.source_path.name}")


def _validate_target_state(plan: ClassificationPlan) -> tuple[Path, Path]:
    try:
        root_path = plan.target_dir.parent.expanduser().resolve()
    except OSError as exc:
        raise ValueError(f"无法解析分类根目录：{exc}") from exc
    if root_path.parent == root_path:
        raise ValueError("分类计划不能直接整理驱动器或共享根目录。")
    if plan.target_dir.is_symlink():
        raise ValueError("分类计划的目标目录已变为符号链接，请重新扫描。")
    target_dir = _resolved_child_path(
        plan.target_dir,
        root_path=root_path,
        field_name="target_dir",
    )
    target_path = _resolved_child_path(
        plan.target_path,
        root_path=root_path,
        field_name="target_path",
    )
    if target_path.parent != target_dir:
        raise ValueError("分类计划的 target_path 不在对应的 target_dir 中。")
    if plan.target_dir.exists() and not plan.target_dir.is_dir():
        raise ValueError("分类计划的目标目录已被其他文件占用，请重新扫描。")
    return root_path, target_dir


def _validate_execution_plan(
    plans: list[ClassificationPlan],
    report_path: Path | None,
) -> None:
    if not plans:
        return
    if len(plans) > SCAN_MAX_FILES:
        raise ValueError(f"单次执行最多支持 {SCAN_MAX_FILES} 个分类计划。")
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
            _validate_source_state(plan)


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
    item_label = (
        f"撤销报告第 {item_number} 项"
        if item_number > 0
        else "当前撤销操作"
    )
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{item_label}缺少有效的 {field_name}。")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{item_label}的 {field_name} 必须是绝对路径。")
    try:
        absolute_path = path.absolute()
        resolved_path = path.resolve()
    except OSError as exc:
        raise ValueError(f"无法解析{item_label}的 {field_name}：{exc}") from exc
    if absolute_path != resolved_path:
        raise ValueError(
            f"{item_label}的 {field_name} 路径不规范或包含符号链接。"
        )
    try:
        relative_path = resolved_path.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(f"{item_label}的 {field_name} 超出分类根目录。") from exc
    if not relative_path.parts:
        raise ValueError(f"{item_label}的 {field_name} 不能指向分类根目录本身。")
    return resolved_path


def _optional_undo_integer(
    item: dict,
    *,
    field_name: str,
    item_number: int,
) -> int | None:
    value = item.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"撤销报告第 {item_number} 项的 {field_name} 必须是非负整数。")
    return value


def _validated_undo_items(
    report: dict,
    report_path: Path,
) -> list[tuple[Path, Path, int | None, int | None]]:
    root_path = _report_root(report, report_path)
    items = report.get("items")
    if not isinstance(items, list):
        raise ValueError("撤销报告格式无效：items 必须是数组。")

    moved_items: list[tuple[Path, Path, int | None, int | None]] = []
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
        source_size = _optional_undo_integer(
            item,
            field_name="source_size",
            item_number=item_number,
        )
        source_mtime_ns = _optional_undo_integer(
            item,
            field_name="source_mtime_ns",
            item_number=item_number,
        )
        if (source_size is None) != (source_mtime_ns is None):
            raise ValueError(
                f"撤销报告第 {item_number} 项的文件状态字段必须同时存在或同时省略。"
            )
        moved_items.append((source_path, target_path, source_size, source_mtime_ns))
    return moved_items


def _validate_reported_file_snapshot(
    path: Path,
    *,
    label: str,
    expected_size: int | None,
    expected_mtime_ns: int | None,
) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label}不再是原来的普通文件：{path}")
    try:
        file_stat = path.stat()
    except OSError as exc:
        raise ValueError(f"无法重新校验{label}：{path}") from exc
    if (
        expected_size is not None
        and expected_mtime_ns is not None
        and (
            file_stat.st_size != expected_size
            or file_stat.st_mtime_ns != expected_mtime_ns
        )
    ):
        raise ValueError(f"{label}已发生变化，为避免移动错误内容，已停止操作：{path.name}")


def _reported_move_state(
    source_path: Path,
    target_path: Path,
    *,
    root_path: Path,
    expected_size: int | None,
    expected_mtime_ns: int | None,
) -> Literal["pending", "restored"]:
    current_source = _undo_item_path(
        str(source_path),
        field_name="source_path",
        item_number=0,
        root_path=root_path,
    )
    current_target = _undo_item_path(
        str(target_path),
        field_name="target_path",
        item_number=0,
        root_path=root_path,
    )
    if current_source != source_path or current_target != target_path:
        raise ValueError("撤销路径在操作期间发生变化，已停止撤销。")

    source_present = source_path.exists() or source_path.is_symlink()
    target_present = target_path.exists() or target_path.is_symlink()
    if source_present and target_present:
        raise ValueError("报告中的源文件和目标文件同时存在，状态存在歧义，请人工检查。")
    if not source_present and not target_present:
        raise ValueError("报告中的源文件和目标文件均不存在，状态存在歧义，请人工检查。")
    if source_present:
        _validate_reported_file_snapshot(
            source_path,
            label="报告源位置的文件",
            expected_size=expected_size,
            expected_mtime_ns=expected_mtime_ns,
        )
        return "restored"

    _validate_reported_file_snapshot(
        target_path,
        label="报告目标文件",
        expected_size=expected_size,
        expected_mtime_ns=expected_mtime_ns,
    )
    return "pending"


def _start_report_journal(report_path: Path, execution_id: str) -> Path:
    resolved_report_path = report_path.expanduser().resolve()
    journal_path = _report_journal_path(resolved_report_path)
    try:
        write_json_lines_exclusive(
            journal_path,
            [
                {
                    "type": "header",
                    "schema_version": REPORT_JOURNAL_SCHEMA_VERSION,
                    "execution_id": execution_id,
                    "report_path": str(resolved_report_path),
                    "root_path": str(resolved_report_path.parent),
                }
            ],
        )
    except FileExistsError as exc:
        raise ValueError(
            "检测到尚未恢复的分类操作。请先打开或撤销上次分类报告，再重新整理。"
        ) from exc
    return journal_path


def _append_move_intent(
    journal_path: Path,
    execution_id: str,
    source_path: Path,
    target_path: Path,
) -> None:
    append_json_line_durable(
        journal_path,
        {
            "type": "move_intent",
            "execution_id": execution_id,
            "source_path": str(source_path),
            "actual_target_path": str(target_path),
        },
        max_bytes=REPORT_JOURNAL_MAX_BYTES,
    )


def _remove_report_journal(journal_path: Path) -> None:
    try:
        journal_path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_report_journal(journal_path: Path) -> list[dict]:
    if journal_path.is_symlink() or not journal_path.is_file():
        raise ValueError("分类恢复日志不是可信的普通文件。")
    with journal_path.open("rb") as handle:
        data = handle.read(REPORT_JOURNAL_MAX_BYTES + 1)
    if len(data) > REPORT_JOURNAL_MAX_BYTES:
        raise ValueError(
            f"分类恢复日志超过允许大小（{REPORT_JOURNAL_MAX_BYTES} 字节）。"
        )

    lines = data.splitlines()
    if not lines:
        raise ValueError("分类恢复日志为空。")
    if len(lines) > SCAN_MAX_FILES + 1:
        raise ValueError("分类恢复日志包含过多记录。")

    records: list[dict] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line.decode("utf-8"))
        except (
            UnicodeError,
            json.JSONDecodeError,
            RecursionError,
            ValueError,
        ) as exc:
            raise ValueError(f"分类恢复日志第 {line_number} 行格式无效。") from exc
        if not isinstance(record, dict):
            raise ValueError(f"分类恢复日志第 {line_number} 行必须是对象。")
        records.append(record)
    return records


def _recover_classification_report(
    report: dict,
    report_path: Path,
    journal_path: Path,
) -> dict:
    records = _read_report_journal(journal_path)
    header = records[0]
    execution_id = report.get("execution_id")
    if not _valid_execution_id(execution_id):
        raise ValueError("分类恢复日志无法匹配缺少或无效执行编号的报告。")
    journal_schema_version = header.get("schema_version")
    if (
        header.get("type") != "header"
        or isinstance(journal_schema_version, bool)
        or not isinstance(journal_schema_version, int)
        or journal_schema_version != REPORT_JOURNAL_SCHEMA_VERSION
        or header.get("execution_id") != execution_id
        or header.get("report_path") != str(report_path)
    ):
        raise ValueError("分类恢复日志与当前报告不匹配。")

    root_path = _report_root(report, report_path)
    if header.get("root_path") != str(root_path):
        raise ValueError("分类恢复日志的根目录与当前报告不匹配。")
    items = report.get("items")
    summary = report.get("summary")
    if not isinstance(items, list) or not isinstance(summary, dict):
        raise ValueError("分类报告格式无效：无法应用恢复日志。")

    items_by_source: dict[Path, dict] = {}
    for item_number, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"分类报告第 {item_number} 项必须是对象。")
        source_path = _undo_item_path(
            item.get("source_path"),
            field_name="source_path",
            item_number=item_number,
            root_path=root_path,
        )
        if source_path in items_by_source:
            raise ValueError("分类报告包含重复的源路径。")
        items_by_source[source_path] = item

    seen_sources: set[Path] = set()
    seen_targets: set[Path] = set()
    for event_number, event in enumerate(records[1:], start=1):
        if (
            event.get("type") != "move_intent"
            or event.get("execution_id") != execution_id
        ):
            raise ValueError(f"分类恢复日志第 {event_number} 项类型或执行编号无效。")
        source_path = _undo_item_path(
            event.get("source_path"),
            field_name="source_path",
            item_number=event_number,
            root_path=root_path,
        )
        target_path = _undo_item_path(
            event.get("actual_target_path"),
            field_name="actual_target_path",
            item_number=event_number,
            root_path=root_path,
        )
        item = items_by_source.get(source_path)
        if item is None:
            raise ValueError(f"分类恢复日志第 {event_number} 项不属于当前报告。")
        planned_target = _undo_item_path(
            item.get("target_path"),
            field_name="target_path",
            item_number=event_number,
            root_path=root_path,
        )
        if target_path.parent != planned_target.parent:
            raise ValueError(f"分类恢复日志第 {event_number} 项超出原目标目录。")
        if source_path in seen_sources or target_path in seen_targets:
            raise ValueError("分类恢复日志包含重复的源路径或目标路径。")
        seen_sources.add(source_path)
        seen_targets.add(target_path)

        expected_size = _optional_undo_integer(
            item,
            field_name="source_size",
            item_number=event_number,
        )
        expected_mtime_ns = _optional_undo_integer(
            item,
            field_name="source_mtime_ns",
            item_number=event_number,
        )
        if (expected_size is None) != (expected_mtime_ns is None):
            raise ValueError(
                f"分类恢复日志第 {event_number} 项的文件状态字段不完整。"
            )
        move_state = _reported_move_state(
            source_path,
            target_path,
            root_path=root_path,
            expected_size=expected_size,
            expected_mtime_ns=expected_mtime_ns,
        )
        if move_state == "restored":
            item["actual_target_path"] = None
            item["operation"] = "skipped"
            continue
        item["actual_target_path"] = str(target_path)
        item["operation"] = "moved"

    moved = sum(
        isinstance(item, dict)
        and item.get("operation") == "moved"
        and bool(item.get("actual_target_path"))
        for item in items
    )
    known_skipped = sum(
        isinstance(item, dict)
        and item.get("operation") != "moved"
        and item.get("status") != "ready"
        for item in items
    )
    existing_skipped = summary.get("skipped")
    if (
        isinstance(existing_skipped, bool)
        or not isinstance(existing_skipped, int)
        or existing_skipped < 0
    ):
        existing_skipped = 0
    summary["moved"] = moved
    summary["skipped"] = max(existing_skipped, known_skipped)
    report["recovered_at"] = (
        datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    )
    write_json_atomic(report_path, report)
    _remove_report_journal(journal_path)
    return report


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
    )
    rules = tuple(custom_rules or ())
    resolver = SeriesResolver(use_network=use_network)
    plans: list[ClassificationPlan] = []
    reserved_targets: set[Path] = set()
    duplicate_fingerprints: dict[Path, str | None] = {}

    def current_fingerprint(path: Path) -> str | None:
        if path not in duplicate_fingerprints:
            try:
                duplicate_fingerprints[path] = file_fingerprint(
                    path,
                    checkpoint=checkpoint,
                )
            except OSError:
                duplicate_fingerprints[path] = None
        return duplicate_fingerprints[path]

    for index, path in enumerate(files, start=1):
        try:
            source_stat = path.stat()
        except OSError:
            source_stat = None
        if progress:
            progress(f"[{index}/{len(files)}] 识别：{path.name}")
        duplicate_of = duplicates.get(path)
        if duplicate_of is not None:
            candidate_fingerprint = current_fingerprint(path)
            original_fingerprint = current_fingerprint(duplicate_of)
            if (
                candidate_fingerprint is None
                or candidate_fingerprint != original_fingerprint
            ):
                duplicate_of = None
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
                    source_size=source_stat.st_size if source_stat else None,
                    source_mtime_ns=source_stat.st_mtime_ns if source_stat else None,
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
            file_query = extract_book_lookup_query(path.name)
            network_query = None if weak_file_name_query(path.name) else file_query
            custom_rule = match_custom_rule(path.name, identity_query, rules)
            if custom_rule is not None:
                network_query = custom_rule.series
                result = ResolveResult(
                    series_name=safe_folder_name(custom_rule.series),
                    source="自定义规则",
                    confidence=1.0,
                    local_guess=identity_query,
                )
            elif network_query is None:
                used_content_hint = bool(identity_hint and identity_query != file_query)
                result = ResolveResult(
                    series_name=extract_series_guess(identity_query),
                    source="本地内容提示" if used_content_hint else "本地规则",
                    confidence=0.6 if used_content_hint else 0.45,
                    local_guess=identity_query,
                )
            else:
                result = resolver.resolve(network_query)
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
                    source_size=source_stat.st_size if source_stat else None,
                    source_mtime_ns=source_stat.st_mtime_ns if source_stat else None,
                    metadata_title=(metadata.title if metadata else result.metadata_title),
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
                    source_size=source_stat.st_size if source_stat else None,
                    source_mtime_ns=source_stat.st_mtime_ns if source_stat else None,
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
        series_name=folder_name,
        target_dir=target_dir,
        target_path=target_path,
        resolver_source="手动修正",
        confidence=1.0,
        metadata_title=None,
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


def execute_classification_plan(
    plans: list[ClassificationPlan],
    *,
    progress: Callable[[str], None] | None = None,
    progress_count: Callable[[int, int], None] | None = None,
    report_path: Path | None = None,
) -> tuple[int, int]:
    if report_path is not None:
        report_path = report_path.expanduser().resolve()
    _validate_execution_plan(plans, report_path)
    moved = 0
    skipped = 0
    actual_targets: dict[Path, Path] = {}
    execution_id: str | None = None
    journal_path: Path | None = None
    if report_path is not None:
        execution_id = uuid.uuid4().hex
        _set_report_execution_active(report_path, active=True)
    try:
        if report_path is not None and execution_id is not None:
            journal_path = _start_report_journal(report_path, execution_id)
            try:
                write_classification_report(
                    plans,
                    report_path,
                    moved=0,
                    skipped=0,
                    actual_targets=actual_targets,
                    execution_id=execution_id,
                )
            except BaseException:
                _remove_report_journal(journal_path)
                journal_path = None
                raise
        for index, plan in enumerate(plans, start=1):
            if not plan.will_move:
                skipped += 1
                if progress_count:
                    progress_count(index, len(plans))
                continue
            if progress:
                progress(f"[{index}/{len(plans)}] 移动：{plan.source_path.name} -> {plan.target_dir.name}")
            _validate_source_state(plan)
            root_path, target_dir = _validate_target_state(plan)
            plan.target_dir.mkdir(parents=True, exist_ok=True)
            root_path, target_dir = _validate_target_state(plan)
            final_target = unique_target_path(plan.target_path, set())
            resolved_final_target = _resolved_child_path(
                final_target,
                root_path=root_path,
                field_name="final_target",
            )
            if resolved_final_target.parent != target_dir:
                raise ValueError("分类计划的最终目标文件超出目标目录。")
            if journal_path is not None and execution_id is not None:
                _append_move_intent(
                    journal_path,
                    execution_id,
                    plan.source_path,
                    resolved_final_target,
                )
            shutil.move(str(plan.source_path), str(resolved_final_target))
            actual_targets[plan.source_path] = resolved_final_target
            moved += 1
            if progress_count:
                progress_count(index, len(plans))
    except Exception as exc:
        if report_path is not None and journal_path is not None:
            try:
                write_classification_report(
                    plans,
                    report_path,
                    moved=moved,
                    skipped=skipped,
                    actual_targets=actual_targets,
                    execution_id=execution_id,
                )
            except OSError as report_exc:
                raise RuntimeError(
                    f"分类中断，且部分撤销报告无法更新：{report_exc}"
                ) from exc
        raise
    else:
        if report_path is not None:
            write_classification_report(
                plans,
                report_path,
                moved=moved,
                skipped=skipped,
                actual_targets=actual_targets,
                execution_id=execution_id,
            )
            if journal_path is not None:
                _remove_report_journal(journal_path)
        return moved, skipped
    finally:
        if execution_id is not None and report_path is not None:
            _set_report_execution_active(report_path, active=False)


def undo_classification_report(
    report_path: Path,
    *,
    progress: Callable[[str], None] | None = None,
    progress_count: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    report_path = report_path.expanduser().resolve()
    report = load_classification_report(report_path)
    root_path = _report_root(report, report_path)
    moved_items = list(reversed(_validated_undo_items(report, report_path)))
    for source_path, target_path, expected_size, expected_mtime_ns in moved_items:
        _reported_move_state(
            source_path,
            target_path,
            root_path=root_path,
            expected_size=expected_size,
            expected_mtime_ns=expected_mtime_ns,
        )

    restored = 0
    skipped = 0
    for index, (
        source_path,
        target_path,
        expected_size,
        expected_mtime_ns,
    ) in enumerate(moved_items, start=1):
        move_state = _reported_move_state(
            source_path,
            target_path,
            root_path=root_path,
            expected_size=expected_size,
            expected_mtime_ns=expected_mtime_ns,
        )
        if move_state == "restored":
            skipped += 1
            if progress_count:
                progress_count(index, len(moved_items))
            continue
        source_path.parent.mkdir(parents=True, exist_ok=True)
        move_state = _reported_move_state(
            source_path,
            target_path,
            root_path=root_path,
            expected_size=expected_size,
            expected_mtime_ns=expected_mtime_ns,
        )
        if move_state == "restored":
            skipped += 1
            if progress_count:
                progress_count(index, len(moved_items))
            continue
        if progress:
            progress(f"撤销：{target_path.name} -> {source_path}")
        shutil.move(str(target_path), str(source_path))
        if (
            _reported_move_state(
                source_path,
                target_path,
                root_path=root_path,
                expected_size=expected_size,
                expected_mtime_ns=expected_mtime_ns,
            )
            != "restored"
        ):
            raise RuntimeError("撤销操作完成后文件状态未达到预期，已停止后续操作。")
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
