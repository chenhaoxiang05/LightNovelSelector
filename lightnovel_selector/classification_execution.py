from __future__ import annotations

import shutil
import uuid
from collections.abc import Callable
from pathlib import Path

from .classification_planning import unique_target_path
from .classification_recovery import (
    _append_move_intent,
    _claim_report_execution,
    _release_report_execution,
    _remove_report_journal,
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


class _ClassificationExecutor:
    def __init__(
        self,
        plans: list[ClassificationPlan],
        *,
        progress: Callable[[str], None] | None,
        progress_count: Callable[[int, int], None] | None,
        report_path: Path | None,
    ) -> None:
        self._plans = plans
        self._progress = progress
        self._progress_count = progress_count
        self._report_path = report_path
        self._moved = 0
        self._skipped = 0
        self._actual_targets: dict[Path, Path] = {}
        self._execution_id: str | None = None
        self._journal_path: Path | None = None

    def run(self) -> tuple[int, int]:
        _validate_execution_plan(self._plans, self._report_path)
        if self._report_path is None:
            self._execute_moves()
            return self._moved, self._skipped

        _claim_report_execution(self._report_path)
        try:
            return self._run_with_report()
        finally:
            _release_report_execution(self._report_path)

    def _run_with_report(self) -> tuple[int, int]:
        try:
            self._initialize_report()
            self._execute_moves()
        except Exception as exc:
            self._write_interrupted_report(exc)
            raise
        else:
            self._finalize_report()
            return self._moved, self._skipped

    def _initialize_report(self) -> None:
        if self._report_path is None:
            return
        self._execution_id = uuid.uuid4().hex
        self._journal_path = _start_report_journal(self._report_path, self._execution_id)
        try:
            self._write_report()
        except BaseException:
            _remove_report_journal(self._journal_path)
            self._journal_path = None
            raise

    def _execute_moves(self) -> None:
        total = len(self._plans)
        for index, plan in enumerate(self._plans, start=1):
            if plan.will_move:
                if self._progress:
                    self._progress(f"[{index}/{total}] 移动：{plan.source_path.name} -> {plan.target_dir.name}")
                final_target = self._move_plan(plan)
                self._actual_targets[plan.source_path] = final_target
                self._moved += 1
            else:
                self._skipped += 1
            if self._progress_count:
                self._progress_count(index, total)

    def _move_plan(self, plan: ClassificationPlan) -> Path:
        _validate_source_state(plan)
        _root_path, _target_dir = _validate_target_state(plan)
        plan.target_dir.mkdir(parents=True, exist_ok=True)
        root_path, target_dir = _validate_target_state(plan)
        resolved_final_target = _resolved_child_path(
            unique_target_path(plan.target_path, set()),
            root_path=root_path,
            field_name="final_target",
        )
        if resolved_final_target.parent != target_dir:
            raise ValueError("分类计划的最终目标文件超出目标目录。")
        self._append_move_intent(plan.source_path, resolved_final_target)
        shutil.move(str(plan.source_path), str(resolved_final_target))
        return resolved_final_target

    def _append_move_intent(self, source_path: Path, target_path: Path) -> None:
        if self._journal_path is None or self._execution_id is None:
            return
        _append_move_intent(
            self._journal_path,
            self._execution_id,
            source_path,
            target_path,
        )

    def _write_report(self) -> None:
        if self._report_path is None:
            return
        write_classification_report(
            self._plans,
            self._report_path,
            moved=self._moved,
            skipped=self._skipped,
            actual_targets=self._actual_targets,
            execution_id=self._execution_id,
        )

    def _write_interrupted_report(self, cause: Exception) -> None:
        if self._report_path is None or self._journal_path is None:
            return
        try:
            self._write_report()
        except OSError as report_exc:
            raise RuntimeError(f"分类中断，且部分撤销报告无法更新：{report_exc}") from cause

    def _finalize_report(self) -> None:
        if self._report_path is None:
            return
        self._write_report()
        if self._journal_path is not None:
            _remove_report_journal(self._journal_path)


def execute_classification_plan(
    plans: list[ClassificationPlan],
    *,
    progress: Callable[[str], None] | None = None,
    progress_count: Callable[[int, int], None] | None = None,
    report_path: Path | None = None,
) -> tuple[int, int]:
    resolved_report_path = report_path.expanduser().resolve() if report_path is not None else None
    return _ClassificationExecutor(
        plans,
        progress=progress,
        progress_count=progress_count,
        report_path=resolved_report_path,
    ).run()
