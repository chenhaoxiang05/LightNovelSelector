from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .classification_safety import (
    _optional_undo_integer,
    _report_root,
    _reported_move_state,
    _undo_item_path,
)
from .constants import REPORT_JOURNAL_MAX_BYTES, REPORT_JOURNAL_SCHEMA_VERSION, SCAN_MAX_FILES
from .storage import append_json_line_durable, write_json_atomic, write_json_lines_exclusive

_ACTIVE_REPORT_PATHS: set[Path] = set()
_ACTIVE_REPORT_PATHS_LOCK = threading.Lock()


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


def valid_execution_id(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 32:
        return False
    try:
        return uuid.UUID(hex=value).hex == value
    except ValueError:
        return False


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
        raise ValueError("检测到尚未恢复的分类操作。请先打开或撤销上次分类报告，再重新整理。") from exc
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
        raise ValueError(f"分类恢复日志超过允许大小（{REPORT_JOURNAL_MAX_BYTES} 字节）。")

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
    if not valid_execution_id(execution_id):
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
        if event.get("type") != "move_intent" or event.get("execution_id") != execution_id:
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
            raise ValueError(f"分类恢复日志第 {event_number} 项的文件状态字段不完整。")
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
        isinstance(item, dict) and item.get("operation") == "moved" and bool(item.get("actual_target_path"))
        for item in items
    )
    known_skipped = sum(
        isinstance(item, dict) and item.get("operation") != "moved" and item.get("status") != "ready" for item in items
    )
    existing_skipped = summary.get("skipped")
    if isinstance(existing_skipped, bool) or not isinstance(existing_skipped, int) or existing_skipped < 0:
        existing_skipped = 0
    summary["moved"] = moved
    summary["skipped"] = max(existing_skipped, known_skipped)
    report["recovered_at"] = datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    write_json_atomic(report_path, report)
    _remove_report_journal(journal_path)
    return report
