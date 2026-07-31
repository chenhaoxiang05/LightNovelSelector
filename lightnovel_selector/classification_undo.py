from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from .classification_reporting import load_classification_report
from .classification_safety import _report_root, _reported_move_state, _validated_undo_items


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
