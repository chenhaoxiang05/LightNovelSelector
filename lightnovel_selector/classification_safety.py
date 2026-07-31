from __future__ import annotations

from pathlib import Path
from typing import Literal

from .constants import (
    APP_NAME,
    REPORT_HISTORY_DIR_NAME,
    REPORT_HISTORY_ROOT_DIR_NAME,
    REPORT_SCHEMA_VERSION,
    SCAN_MAX_FILES,
)
from .models import ClassificationPlan


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
        and (current_stat.st_size != plan.source_size or current_stat.st_mtime_ns != plan.source_mtime_ns)
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
        expected_history_root = resolved_root / REPORT_HISTORY_ROOT_DIR_NAME
        expected_history_dir = expected_history_root / REPORT_HISTORY_DIR_NAME
        try:
            resolved_history_root = expected_history_root.resolve()
            resolved_history_dir = expected_history_dir.resolve()
        except (OSError, ValueError) as exc:
            raise ValueError("无法安全解析分类历史目录。") from exc
        if (
            resolved_history_root != expected_history_root.absolute()
            or resolved_history_dir != expected_history_dir.absolute()
        ):
            raise ValueError("分类历史目录不能是符号链接或目录联接。")
        try:
            resolved_history_root.relative_to(resolved_root)
            resolved_history_dir.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("分类历史目录超出分类根目录。") from exc
        if report_path.parent != resolved_history_dir:
            raise ValueError("撤销报告必须保留在生成它的分类根目录或历史目录中。")
    return resolved_root


def classification_report_root(report: dict, report_path: Path) -> Path:
    return _report_root(report, report_path.expanduser().resolve())


def _undo_item_path(value: object, *, field_name: str, item_number: int, root_path: Path) -> Path:
    item_label = f"撤销报告第 {item_number} 项" if item_number > 0 else "当前撤销操作"
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
        raise ValueError(f"{item_label}的 {field_name} 路径不规范或包含符号链接。")
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
            raise ValueError(f"撤销报告第 {item_number} 项的文件状态字段必须同时存在或同时省略。")
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
        and (file_stat.st_size != expected_size or file_stat.st_mtime_ns != expected_mtime_ns)
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
