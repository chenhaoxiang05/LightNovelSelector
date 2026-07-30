from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .classification import classification_report_root, load_classification_report
from .constants import (
    REPORT_FILE_NAME,
    REPORT_HISTORY_DIR_NAME,
    REPORT_HISTORY_FILE_PREFIX,
    REPORT_HISTORY_ROOT_DIR_NAME,
    REPORT_HISTORY_SCAN_MAX_ENTRIES,
    REPORT_HISTORY_UI_MAX_REPORTS,
    REPORT_SCHEMA_VERSION,
)
from .storage import write_json_atomic


def _valid_execution_id(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 32:
        return False
    try:
        return uuid.UUID(hex=value).hex == value
    except ValueError:
        return False


def _history_file_execution_id(path: Path) -> str | None:
    name = path.name
    if not name.startswith(REPORT_HISTORY_FILE_PREFIX) or path.suffix.casefold() != ".json":
        return None
    stem = name[: -len(path.suffix)]
    remainder = stem[len(REPORT_HISTORY_FILE_PREFIX) :]
    if len(remainder) != 49 or remainder[8] != "T" or remainder[15:17] != "Z-":
        return None
    timestamp = remainder[:16]
    execution_id = remainder[17:]
    if not timestamp[:8].isdigit() or not timestamp[9:15].isdigit() or not _valid_execution_id(execution_id):
        return None
    return execution_id


def _resolved_root(root: Path) -> Path:
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(f"分类根目录不存在或不是文件夹：{resolved}")
    return resolved


def _history_directory(root: Path, *, create: bool) -> Path | None:
    resolved_root = _resolved_root(root)
    history_root = resolved_root / REPORT_HISTORY_ROOT_DIR_NAME
    configured = history_root / REPORT_HISTORY_DIR_NAME
    if not history_root.exists() and not history_root.is_symlink():
        if not create:
            return None
        history_root.mkdir()
    try:
        resolved_history_root = history_root.resolve()
    except OSError as exc:
        raise ValueError("分类历史根目录超出所选根目录。") from exc
    if resolved_history_root != history_root.absolute():
        raise ValueError("分类历史根目录不能是符号链接或目录联接。")
    try:
        resolved_history_root.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("分类历史根目录超出所选根目录。") from exc
    if not resolved_history_root.is_dir():
        raise NotADirectoryError("分类历史根目录已被其他文件占用。")

    if not configured.exists() and not configured.is_symlink():
        if not create:
            return None
        configured.mkdir()

    try:
        resolved = configured.resolve()
    except OSError as exc:
        raise ValueError("分类历史目录超出所选根目录。") from exc
    if resolved != configured.absolute():
        raise ValueError("分类历史目录不能是符号链接或目录联接。")
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("分类历史目录超出所选根目录。") from exc
    if not resolved.is_dir():
        raise NotADirectoryError("分类历史路径已被其他文件占用。")
    return resolved


def classification_report_history_directory(root: Path, *, create: bool = False) -> Path | None:
    return _history_directory(root, create=create)


def _report_timestamp(report: dict[str, Any], report_path: Path) -> tuple[datetime, str | None]:
    value = report.get("created_at")
    if isinstance(value, str) and len(value) <= 64:
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc), value
        except ValueError:
            pass
    try:
        fallback = datetime.fromtimestamp(report_path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        fallback = datetime.now(tz=timezone.utc)
    return fallback, None


def _report_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _validated_report(root: Path, report_path: Path, *, recover_pending: bool) -> dict[str, Any]:
    resolved_path = report_path.expanduser().resolve()
    report = load_classification_report(resolved_path, recover_pending=recover_pending)
    if classification_report_root(report, resolved_path) != root:
        raise ValueError("分类报告不属于当前所选目录。")
    return report


def archive_classification_report(report_path: Path) -> Path | None:
    resolved_report = report_path.expanduser().resolve()
    report = load_classification_report(resolved_report)
    root = classification_report_root(report, resolved_report)
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        return None
    execution_id = report.get("execution_id")
    if not _valid_execution_id(execution_id):
        raise ValueError("分类报告缺少有效的执行编号，无法归档。")

    history_dir = _history_directory(root, create=True)
    if history_dir is None:
        raise RuntimeError("无法创建分类历史目录。")
    timestamp, _ = _report_timestamp(report, resolved_report)
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    target = history_dir / f"{REPORT_HISTORY_FILE_PREFIX}{stamp}-{execution_id}.json"
    if target.exists() and not target.is_symlink():
        try:
            if load_classification_report(target, recover_pending=False) == report:
                return target
        except (OSError, ValueError):
            pass
    write_json_atomic(target, report)
    return target


def _report_summary(
    root: Path,
    report_path: Path,
    *,
    is_latest: bool,
    recover_pending: bool,
) -> tuple[datetime, dict[str, Any]]:
    report = _validated_report(
        root,
        report_path,
        recover_pending=recover_pending,
    )
    execution_id = report.get("execution_id")
    if not _valid_execution_id(execution_id):
        if not is_latest:
            raise ValueError("历史报告缺少有效的执行编号。")
        report_id = "latest"
    else:
        report_id = str(execution_id)
    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("分类报告格式无效：summary 必须是对象。")
    timestamp, created_at = _report_timestamp(report, report_path)
    undo_completed_at = report.get("undo_completed_at")
    if not isinstance(undo_completed_at, str) or len(undo_completed_at) > 64:
        undo_completed_at = None
    stats = {
        "total": _report_count(summary.get("total")),
        "moved": _report_count(summary.get("moved")),
        "skipped": _report_count(summary.get("skipped")),
        "duplicates": _report_count(summary.get("duplicates")),
        "errors": _report_count(summary.get("errors")),
    }
    undo_completed = undo_completed_at is not None
    if undo_completed:
        status = "undone"
        status_label = "已撤销"
    elif stats["moved"] > 0:
        status = "available"
        status_label = "可撤销"
    else:
        status = "no_moves"
        status_label = "无移动"
    return timestamp, {
        "report_id": report_id,
        "path": str(report_path),
        "file_name": report_path.name,
        "created_at": created_at,
        "version": str(report.get("version") or "")[:64],
        "is_latest": is_latest,
        "undo_completed": undo_completed,
        "undo_completed_at": undo_completed_at,
        "can_undo": not undo_completed and stats["moved"] > 0,
        "status": status,
        "status_label": status_label,
        "summary": stats,
    }


def list_classification_reports(
    root: Path,
    *,
    limit: int = REPORT_HISTORY_UI_MAX_REPORTS,
    recover_latest: bool = True,
) -> dict[str, Any]:
    resolved_root = _resolved_root(root)
    bounded_limit = max(1, min(limit, REPORT_HISTORY_UI_MAX_REPORTS))
    canonical = resolved_root / REPORT_FILE_NAME
    candidates: list[tuple[Path, bool]] = []
    if canonical.exists() or canonical.is_symlink():
        candidates.append((canonical, True))

    history_truncated = False
    history_dir = _history_directory(resolved_root, create=False)
    if history_dir is not None:
        history_paths: list[Path] = []
        for inspected, path in enumerate(history_dir.iterdir(), start=1):
            if inspected > REPORT_HISTORY_SCAN_MAX_ENTRIES:
                history_truncated = True
                break
            if path.name.startswith(REPORT_HISTORY_FILE_PREFIX) and path.suffix.casefold() == ".json":
                history_paths.append(path)
        candidates.extend((path, False) for path in sorted(history_paths, reverse=True))

    records: list[tuple[datetime, dict[str, Any]]] = []
    seen_ids: set[str] = set()
    invalid_count = 0
    for path, is_latest in candidates:
        if path.is_symlink() or not path.is_file():
            invalid_count += 1
            continue
        file_execution_id = None
        if not is_latest:
            file_execution_id = _history_file_execution_id(path)
            if file_execution_id is None:
                invalid_count += 1
                continue
        try:
            timestamp, summary = _report_summary(
                resolved_root,
                path,
                is_latest=is_latest,
                recover_pending=is_latest and recover_latest,
            )
        except (OSError, ValueError):
            invalid_count += 1
            continue
        report_id = str(summary["report_id"])
        if file_execution_id is not None and file_execution_id != report_id:
            invalid_count += 1
            continue
        if report_id in seen_ids:
            continue
        seen_ids.add(report_id)
        records.append((timestamp, summary))

    records.sort(key=lambda item: (item[0], item[1]["file_name"]), reverse=True)
    total_count = len(records)
    return {
        "reports": [summary for _, summary in records[:bounded_limit]],
        "total_count": total_count,
        "invalid_count": invalid_count,
        "truncated": history_truncated or total_count > bounded_limit,
    }


def resolve_classification_report(root: Path, report_id: str | None) -> Path:
    resolved_root = _resolved_root(root)
    canonical = resolved_root / REPORT_FILE_NAME
    if report_id in {None, "", "latest"}:
        if not canonical.is_file() or canonical.is_symlink():
            raise FileNotFoundError("当前目录没有可用的最新分类报告。")
        return canonical
    if not _valid_execution_id(report_id):
        raise ValueError("分类历史执行编号无效。")

    if canonical.is_file() and not canonical.is_symlink():
        try:
            report = _validated_report(resolved_root, canonical, recover_pending=True)
        except (OSError, ValueError):
            pass
        else:
            if report.get("execution_id") == report_id:
                return canonical

    history_dir = _history_directory(resolved_root, create=False)
    if history_dir is None:
        raise FileNotFoundError("没有找到指定的分类历史报告。")
    matches = sorted(
        history_dir.glob(f"{REPORT_HISTORY_FILE_PREFIX}*-{report_id}.json"),
        reverse=True,
    )
    for path in matches:
        if path.is_symlink() or not path.is_file() or _history_file_execution_id(path) != report_id:
            continue
        try:
            report = _validated_report(resolved_root, path, recover_pending=False)
        except (OSError, ValueError):
            continue
        if report.get("execution_id") == report_id:
            return path
    raise FileNotFoundError("没有找到指定的分类历史报告。")


def mark_classification_report_undone(
    report_path: Path,
    *,
    restored: int,
    skipped: int,
) -> None:
    resolved_report = report_path.expanduser().resolve()
    report = load_classification_report(resolved_report)
    classification_report_root(report, resolved_report)
    report["undo_completed_at"] = datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    report["undo_summary"] = {
        "restored": max(0, int(restored)),
        "skipped": max(0, int(skipped)),
    }
    write_json_atomic(resolved_report, report)
