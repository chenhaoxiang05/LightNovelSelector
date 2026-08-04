"""Stable public facade for classification workflows.

Implementation lives in focused modules so planning, file transactions, recovery,
and undo safety can evolve and be tested independently.
"""

from __future__ import annotations
from .classification_discovery import find_novel_files, validate_classification_root
from .classification_execution import execute_classification_plan
from .classification_planning import (
    build_classification_plan,
    classification_plan_group_indices,
    count_plan_statuses,
    plan_status_label,
    revise_classification_plan,
    revise_classification_plans,
    unique_target_path,
)
from .classification_reporting import (
    classification_plan_to_report_item,
    load_classification_report,
    write_classification_report,
)
from .classification_safety import classification_report_root
from .classification_undo import undo_classification_report
__all__ = [
    "build_classification_plan",
    "classification_plan_group_indices",
    "classification_plan_to_report_item",
    "classification_report_root",
    "count_plan_statuses",
    "execute_classification_plan",
    "find_novel_files",
    "load_classification_report",
    "plan_status_label",
    "revise_classification_plan",
    "revise_classification_plans",
    "undo_classification_report",
    "unique_target_path",
    "validate_classification_root",
    "write_classification_report",
]
