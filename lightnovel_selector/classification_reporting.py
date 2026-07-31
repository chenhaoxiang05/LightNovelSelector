from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .classification_recovery import (
    _recover_classification_report,
    _report_execution_is_active,
    _report_journal_path,
)
from .constants import APP_NAME, APP_VERSION, REPORT_MAX_BYTES, REPORT_SCHEMA_VERSION
from .models import ClassificationPlan
from .storage import book_identity_to_dict, write_json_atomic


def classification_plan_to_report_item(
    plan: ClassificationPlan,
    *,
    actual_target_path: Path | None = None,
) -> dict:
    return {
        "source_path": str(plan.source_path),
        "target_path": str(plan.target_path),
        "actual_target_path": str(actual_target_path) if actual_target_path else None,
        "identity": book_identity_to_dict(plan.identity),
        "series_name": plan.series_name,
        "resolver_source": plan.resolver_source,
        "confidence": round(plan.confidence, 4),
        "confidence_level": plan.confidence_level,
        "classification_reason": plan.classification_reason,
        "classification_evidence": list(plan.classification_evidence),
        "status": plan.status,
        "operation": "moved" if actual_target_path else "skipped",
        "note": plan.note,
        "duplicate_of": str(plan.duplicate_of) if plan.duplicate_of else None,
        "rename_to": plan.rename_to,
        "metadata_title": plan.identity.title,
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
    if not recover_pending or (not journal_path.exists() and not journal_path.is_symlink()):
        return report

    if _report_execution_is_active(report_path):
        return report
    return _recover_classification_report(report, report_path, journal_path)
