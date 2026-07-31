from __future__ import annotations

import shutil
import uuid
from collections.abc import Callable
from pathlib import Path

from .classification_planning import unique_target_path
from .classification_recovery import (
    _append_move_intent,
    _remove_report_journal,
    _set_report_execution_active,
    _start_report_journal,
)
from .classification_reporting import write_classification_report
from .classification_safety import (
    _resolved_child_path,
    _validate_execution_plan,
    _validate_source_state,
    _validate_target_state,
)
from .models import ClassificationPlan


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
                raise RuntimeError(f"分类中断，且部分撤销报告无法更新：{report_exc}") from exc
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
