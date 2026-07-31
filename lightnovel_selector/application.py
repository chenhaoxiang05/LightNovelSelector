from __future__ import annotations

import base64
import math
import threading
from collections import deque
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

from .classification import (
    build_classification_plan,
    classification_plan_group_indices,
    count_plan_statuses,
    execute_classification_plan,
    load_classification_report,
    plan_status_label,
    revise_classification_plans,
    undo_classification_report,
    validate_classification_root,
)
from .constants import (
    APP_NAME,
    APP_VERSION,
    CLASSIFICATION_CANDIDATE_MAX_COUNT,
    COVER_MAX_BYTES,
    CUSTOM_RULE_MAX_COUNT,
    CUSTOM_RULE_PATTERN_MAX_CHARS,
    METADATA_PROVIDER_MAX_COUNT,
    METADATA_PROVIDER_PRIORITY_MAX,
    METADATA_PROVIDER_PRIORITY_MIN,
    REPORT_FILE_NAME,
    REPORT_UI_MAX_ITEMS,
    SERIES_NAME_MAX_CHARS,
)
from .corrections import RecognitionCorrectionMemory
from .files import http_bytes, read_local_cover_bytes
from .identity import (
    language_display_name,
    merge_book_identities,
    merge_classification_candidates,
    volume_display_name,
)
from .metadata import SeriesResolver
from .models import (
    AppSettings,
    ClassificationCandidate,
    ClassificationPlan,
    CustomRule,
    MetadataProviderSetting,
)
from .parsing import collapse_spaces, normalize_for_match
from .provider_reliability import ProviderReliabilityController
from .providers import (
    MetadataProvider,
    MetadataProviderRegistry,
    builtin_metadata_providers,
)
from .report_history import (
    archive_classification_report,
    list_classification_reports,
    mark_classification_report_undone,
    resolve_classification_report,
)
from .scan_cache import PersistentScanCache, ScanCacheStats
from .scan_session import OperationCancelled, ScanSession
from .storage import (
    app_settings_to_dict,
    book_identity_from_dict,
    book_identity_to_dict,
    load_app_settings,
    try_save_app_settings,
)


def plan_to_dict(plan: ClassificationPlan, index: int) -> dict[str, Any]:
    identity = plan.identity
    return {
        "index": index,
        "file_name": plan.source_path.name,
        "extension": plan.source_path.suffix.casefold(),
        "source_path": str(plan.source_path),
        "identity": book_identity_to_dict(identity),
        "book_title": identity.title,
        "series_name": plan.series_name,
        "authors": list(identity.authors),
        "authors_label": "、".join(identity.authors) or "未识别",
        "volume_number": identity.volume_number,
        "volume_label": volume_display_name(identity.volume_number),
        "language": identity.language,
        "language_label": language_display_name(identity.language),
        "tags": list(identity.tags),
        "tags_label": " · ".join(identity.tags),
        "series_key": plan.series_key or plan.series_name,
        "target_dir": str(plan.target_dir),
        "target_path": str(plan.target_path),
        "target_name": plan.target_path.name,
        "resolver_source": plan.resolver_source,
        "confidence": round(plan.confidence, 4),
        "confidence_label": f"{plan.confidence:.0%}",
        "confidence_level": plan.confidence_level,
        "classification_reason": plan.classification_reason,
        "classification_evidence": list(plan.classification_evidence),
        "status": plan.status,
        "status_label": plan_status_label(plan.status),
        "note": plan.note,
        "duplicate_of": str(plan.duplicate_of) if plan.duplicate_of else None,
        "rename_to": plan.rename_to,
        "metadata_title": identity.title,
        "metadata_url": plan.metadata_url,
        "has_local_cover": plan.source_path.suffix.casefold() in {".epub", ".cbz", ".zip"},
        "will_move": plan.will_move,
    }


def classification_candidate_to_dict(
    candidate: ClassificationCandidate,
    *,
    current_series: str,
) -> dict[str, Any]:
    identity = candidate.identity
    is_current = normalize_for_match(identity.series_name) == normalize_for_match(current_series)
    return {
        "identity": book_identity_to_dict(identity),
        "title": identity.title,
        "series_name": identity.series_name,
        "authors_label": "、".join(identity.authors) or "未识别",
        "volume_label": volume_display_name(identity.volume_number),
        "language_label": language_display_name(identity.language),
        "tags_label": " · ".join(identity.tags) or "未识别",
        "source": candidate.source,
        "confidence": round(candidate.confidence, 4),
        "confidence_label": f"{candidate.confidence:.0%}",
        "is_current": is_current,
        "current_label": "当前" if is_current else "",
    }


def classification_candidate_payloads(plan: ClassificationPlan) -> list[dict[str, Any]]:
    current = ClassificationCandidate(
        identity=plan.identity,
        source=plan.resolver_source,
        confidence=plan.confidence,
    )
    current_key = normalize_for_match(plan.series_name)
    alternatives = [
        candidate
        for candidate in merge_classification_candidates(plan.candidates)
        if normalize_for_match(candidate.identity.series_name) != current_key
    ][: CLASSIFICATION_CANDIDATE_MAX_COUNT - 1]
    return [
        classification_candidate_to_dict(candidate, current_series=plan.series_name)
        for candidate in (current, *alternatives)
    ]


def _image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    return "application/octet-stream"


def _data_uri(data: bytes | None) -> str | None:
    if not data:
        return None
    mime = _image_mime(data)
    if not mime.startswith("image/"):
        return None
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _report_text(value: object, *, max_chars: int, default: str = "") -> str:
    return value[:max_chars] if isinstance(value, str) else default


def _report_count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _report_confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    result = float(value)
    return max(0.0, min(result, 1.0)) if math.isfinite(result) else 0.0


def _report_item_for_ui(item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    actual_target = item.get("actual_target_path")
    series_name = _report_text(item.get("series_name"), max_chars=120)
    metadata_title = _report_text(item.get("metadata_title"), max_chars=512)
    identity = (
        book_identity_from_dict(
            item.get("identity") if isinstance(item.get("identity"), dict) else {},
            fallback_title=metadata_title or series_name,
            fallback_series=series_name,
        )
        if metadata_title or series_name
        else None
    )
    return {
        "source_path": _report_text(item.get("source_path"), max_chars=4_096),
        "target_path": _report_text(item.get("target_path"), max_chars=4_096),
        "actual_target_path": (
            _report_text(actual_target, max_chars=4_096) if isinstance(actual_target, str) else None
        ),
        "identity": book_identity_to_dict(identity) if identity else None,
        "series_name": series_name,
        "resolver_source": _report_text(item.get("resolver_source"), max_chars=120),
        "confidence": _report_confidence(item.get("confidence")),
        "status": _report_text(item.get("status"), max_chars=32),
        "operation": _report_text(item.get("operation"), max_chars=32),
        "note": _report_text(item.get("note"), max_chars=2_000),
    }


class ApplicationService:
    def __init__(
        self,
        metadata_providers: Iterable[MetadataProvider] | MetadataProviderRegistry | None = None,
        correction_memory: RecognitionCorrectionMemory | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.metadata_provider_registry = (
            metadata_providers
            if isinstance(metadata_providers, MetadataProviderRegistry)
            else MetadataProviderRegistry(
                builtin_metadata_providers() if metadata_providers is None else metadata_providers
            )
        )
        self.settings = load_app_settings()
        self.provider_reliability = ProviderReliabilityController()
        self.correction_memory = correction_memory or RecognitionCorrectionMemory()
        self.folder = self._existing_folder(self.settings.last_folder)
        self.plans: list[ClassificationPlan] = []
        self.plans_revision = 0
        self.scan_cache_stats = ScanCacheStats().to_dict()
        self.report_path: Path | None = self._report_for_folder(self.folder)
        self._operation_id = 0
        self.operation = self._idle_operation(has_folder=self.folder is not None)
        self._cancel_event: threading.Event | None = None
        self._logs: deque[dict[str, Any]] = deque(maxlen=300)
        self._next_log_id = 0
        initial_message = (
            f"已恢复上次目录：{self.folder}。可以开始扫描。"
            if self.folder is not None
            else "应用已就绪。选择一个轻小说目录开始扫描。"
        )
        self._append_log(initial_message, "info")

    @staticmethod
    def _existing_folder(value: str) -> Path | None:
        if not value:
            return None
        try:
            return validate_classification_root(Path(value))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _report_for_folder(folder: Path | None) -> Path | None:
        if folder is None:
            return None
        candidate = folder / REPORT_FILE_NAME
        return candidate if candidate.exists() else None

    @staticmethod
    def _idle_operation(*, operation_id: int = 0, has_folder: bool = False) -> dict[str, Any]:
        return {
            "id": operation_id,
            "kind": "idle",
            "state": "idle",
            "message": "等待扫描预览" if has_folder else "等待选择目录",
            "done": 0,
            "total": 0,
            "can_cancel": False,
            "error": None,
        }

    def _append_log(self, message: str, kind: str = "info") -> None:
        with self._lock:
            self._next_log_id += 1
            self._logs.append(
                {
                    "id": self._next_log_id,
                    "time": datetime.now(tz=timezone.utc).astimezone().strftime("%H:%M:%S"),
                    "kind": kind,
                    "message": str(message),
                }
            )

    def _invalidate_plans_locked(self) -> None:
        self.plans = []
        self.plans_revision += 1
        self.scan_cache_stats = ScanCacheStats().to_dict()

    def _assert_idle_locked(self) -> None:
        if self.operation["state"] == "running":
            raise RuntimeError("当前操作尚未完成，请稍候。")

    def _start_operation_locked(
        self,
        kind: str,
        message: str,
        *,
        total: int = 0,
        can_cancel: bool = False,
    ) -> tuple[int, threading.Event]:
        self._assert_idle_locked()
        self._operation_id += 1
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self.operation = {
            "id": self._operation_id,
            "kind": kind,
            "state": "running",
            "message": message,
            "done": 0,
            "total": total,
            "can_cancel": can_cancel,
            "error": None,
        }
        self._append_log(message, "info")
        return self._operation_id, cancel_event

    def _update_operation(
        self,
        operation_id: int,
        *,
        message: str | None = None,
        done: int | None = None,
        total: int | None = None,
    ) -> None:
        with self._lock:
            if self.operation["id"] != operation_id or self.operation["state"] != "running":
                return
            if message is not None:
                self.operation["message"] = message
            if done is not None:
                self.operation["done"] = done
            if total is not None:
                self.operation["total"] = total

    def _finish_operation(
        self,
        operation_id: int,
        state: str,
        message: str,
        *,
        error: str | None = None,
    ) -> None:
        with self._lock:
            if self.operation["id"] != operation_id:
                return
            self.operation["state"] = state
            self.operation["message"] = message
            self.operation["can_cancel"] = False
            self.operation["error"] = error
            if self.operation["total"]:
                self.operation["done"] = self.operation["total"]
            self._cancel_event = None
            log_kind = "success" if state == "success" else "warning" if state == "cancelled" else "error"
            self._append_log(message if error is None else f"{message}：{error}", log_kind)

    def is_critical_operation(self) -> bool:
        with self._lock:
            return self.operation["state"] == "running" and self.operation["kind"] in {"apply", "undo"}

    def is_operation_running(self) -> bool:
        with self._lock:
            return self.operation["state"] == "running"

    def set_folder(self, value: str) -> dict[str, Any]:
        path = validate_classification_root(Path(value))

        with self._lock:
            self._assert_idle_locked()
            changed = self.folder != path
            self.folder = path
            self.report_path = self._report_for_folder(path)
            self.settings = replace(self.settings, last_folder=str(path))
            if changed:
                self._invalidate_plans_locked()
                self.operation = self._idle_operation(
                    operation_id=self._operation_id,
                    has_folder=True,
                )
        error = try_save_app_settings(self.settings)
        if error:
            self._append_log(f"最近目录未能保存：{error}", "warning")
        if changed:
            self._append_log(f"已选择目录：{path}", "info")
        return self.snapshot()

    @staticmethod
    def _rules_from_payload(payload: dict[str, Any]) -> tuple[CustomRule, ...]:
        raw_rules = payload.get("custom_rules") or []
        if not isinstance(raw_rules, list):
            raise ValueError("自定义规则必须是数组。")
        if len(raw_rules) > CUSTOM_RULE_MAX_COUNT:
            raise ValueError(f"自定义规则不能超过 {CUSTOM_RULE_MAX_COUNT} 条。")
        rules: list[CustomRule] = []
        for position, item in enumerate(raw_rules, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"第 {position} 条规则格式无效。")
            pattern_value = item.get("pattern")
            series_value = item.get("series")
            if not isinstance(pattern_value, str) or not isinstance(series_value, str):
                raise ValueError(f"第 {position} 条规则的匹配模式和系列名必须是字符串。")
            pattern = collapse_spaces(pattern_value)
            series = collapse_spaces(series_value)
            if not pattern or not series:
                raise ValueError(f"第 {position} 条规则需要同时填写匹配模式和系列名。")
            if len(pattern) > CUSTOM_RULE_PATTERN_MAX_CHARS:
                raise ValueError(f"第 {position} 条规则的匹配模式过长。")
            if len(series) > SERIES_NAME_MAX_CHARS:
                raise ValueError(f"第 {position} 条规则的系列名过长。")
            rules.append(CustomRule(pattern=pattern, series=series))
        return tuple(rules)

    @staticmethod
    def _boolean_from_payload(payload: dict[str, Any], name: str, *, default: bool) -> bool:
        value = payload.get(name, default)
        if not isinstance(value, bool):
            raise ValueError(f"设置 {name} 必须是布尔值。")
        return value

    def _provider_settings_from_payload(
        self,
        payload: dict[str, Any],
    ) -> tuple[MetadataProviderSetting, ...]:
        raw_settings = payload.get("provider_settings")
        if raw_settings is None:
            return self.settings.provider_settings
        if not isinstance(raw_settings, list):
            raise ValueError("元数据来源设置必须是数组。")
        if len(raw_settings) > METADATA_PROVIDER_MAX_COUNT:
            raise ValueError(f"元数据来源设置不能超过 {METADATA_PROVIDER_MAX_COUNT} 条。")

        known_ids = {provider.provider_id for provider in self.metadata_provider_registry}
        seen_ids: set[str] = set()
        settings: list[MetadataProviderSetting] = []
        for position, item in enumerate(raw_settings, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"第 {position} 条元数据来源设置格式无效。")
            provider_id = item.get("provider_id")
            enabled = item.get("enabled")
            priority = item.get("priority")
            if not isinstance(provider_id, str) or provider_id not in known_ids:
                raise ValueError(f"第 {position} 条元数据来源设置包含未知来源。")
            if provider_id in seen_ids:
                raise ValueError(f"元数据来源设置 ID 重复：{provider_id}")
            if not isinstance(enabled, bool):
                raise ValueError(f"元数据来源 {provider_id} 的启用状态必须是布尔值。")
            if (
                isinstance(priority, bool)
                or not isinstance(priority, int)
                or not METADATA_PROVIDER_PRIORITY_MIN <= priority <= METADATA_PROVIDER_PRIORITY_MAX
            ):
                raise ValueError(
                    f"元数据来源 {provider_id} 的优先级必须在 "
                    f"{METADATA_PROVIDER_PRIORITY_MIN} 到 {METADATA_PROVIDER_PRIORITY_MAX} 之间。"
                )
            seen_ids.add(provider_id)
            settings.append(
                MetadataProviderSetting(
                    provider_id=provider_id,
                    enabled=enabled,
                    priority=priority,
                )
            )
        return tuple(settings)

    def _configured_provider_registry(
        self,
        settings: AppSettings,
    ) -> MetadataProviderRegistry:
        return self.metadata_provider_registry.configured(settings.provider_settings)

    def _provider_snapshot(self) -> list[dict[str, Any]]:
        settings_by_id = {setting.provider_id: setting for setting in self.settings.provider_settings}
        providers: list[dict[str, Any]] = []
        for provider in self.metadata_provider_registry:
            setting = settings_by_id.get(provider.provider_id)
            enabled = setting.enabled if setting is not None else True
            priority = setting.priority if setting is not None else provider.priority
            health = self.provider_reliability.health(provider.provider_id).to_dict()
            if not enabled:
                health = {
                    **health,
                    "status": "disabled",
                    "status_label": "已禁用",
                    "cooldown_remaining_seconds": 0,
                }
            providers.append(
                {
                    "id": provider.provider_id,
                    "name": provider.display_name,
                    "priority": priority,
                    "default_priority": provider.priority,
                    "enabled": enabled,
                    **health,
                }
            )
        return sorted(
            providers,
            key=lambda item: (
                int(item["priority"]),
                str(item["id"]),
            ),
        )

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("设置格式无效。")
        rules = self._rules_from_payload(payload)
        with self._lock:
            self._assert_idle_locked()
            provider_settings = self._provider_settings_from_payload(payload)
            new_settings = AppSettings(
                use_network=self._boolean_from_payload(payload, "use_network", default=True),
                recursive=self._boolean_from_payload(payload, "recursive", default=False),
                auto_rename=self._boolean_from_payload(payload, "auto_rename", default=False),
                custom_rules=rules,
                provider_settings=provider_settings,
                last_folder=str(self.folder or ""),
            )
            changed = new_settings != self.settings
            self.settings = new_settings
            if changed and self.plans:
                self._invalidate_plans_locked()
        error = try_save_app_settings(new_settings)
        if error:
            self._append_log(f"设置未能写入磁盘，但本次操作仍可继续：{error}", "warning")
        elif changed:
            self._append_log("设置已保存。", "success")
        return {"saved": error is None, "warning": str(error) if error else None, "state": self.snapshot()}

    def snapshot(self, log_cursor: int = 0, plans_revision: int = -1) -> dict[str, Any]:
        with self._lock:
            plans_payload = None
            if plans_revision != self.plans_revision:
                plans_payload = [plan_to_dict(plan, index) for index, plan in enumerate(self.plans)]
            counts = count_plan_statuses(self.plans)
            counts.update(
                {
                    "unchanged": sum(plan.status == "unchanged" for plan in self.plans),
                    "moved": sum(plan.status == "moved" for plan in self.plans),
                    "series": len({plan.series_key or plan.series_name for plan in self.plans}),
                }
            )
            return {
                "app": {"name": APP_NAME, "version": APP_VERSION},
                "metadata_providers": self._provider_snapshot(),
                "folder": str(self.folder) if self.folder else "",
                "settings": app_settings_to_dict(self.settings),
                "operation": dict(self.operation),
                "counts": counts,
                "scan_cache": dict(self.scan_cache_stats),
                "report_path": str(self.report_path) if self.report_path and self.report_path.exists() else None,
                "plans_revision": self.plans_revision,
                "plans": plans_payload,
                "logs": [dict(item) for item in self._logs if item["id"] > log_cursor],
                "log_cursor": self._next_log_id,
            }

    def start_scan(self) -> dict[str, Any]:
        with self._lock:
            if self.folder is None:
                raise ValueError("请先选择要整理的大文件夹。")
            self._assert_idle_locked()
            folder = self.folder
            settings = self.settings
            metadata_providers = self._configured_provider_registry(settings)
            self._invalidate_plans_locked()
            operation_id, cancel_event = self._start_operation_locked(
                "scan",
                "正在扫描并识别小说文件…",
                can_cancel=True,
            )

        def report_message(message: str) -> None:
            self._append_log(message, "info")
            self._update_operation(operation_id, message=message)

        session = ScanSession(
            folder,
            settings,
            metadata_providers=metadata_providers,
            correction_memory=self.correction_memory,
            cancel_event=cancel_event,
            provider_reliability=self.provider_reliability,
            on_message=report_message,
            on_progress=lambda done, total: self._update_operation(
                operation_id,
                done=done,
                total=total,
            ),
            plan_builder=build_classification_plan,
            scan_cache_factory=PersistentScanCache,
        )

        def work() -> None:
            try:
                result = session.run()
                plans = result.plans
                cache_stats = result.cache_stats
                with self._lock:
                    if self.operation["id"] != operation_id:
                        return
                    self.plans = plans
                    self.plans_revision += 1
                    self.scan_cache_stats = cache_stats.to_dict()
                    self.report_path = self._report_for_folder(folder)
                if cache_stats.write_warning:
                    self._append_log(
                        f"扫描缓存不可用，但本次结果仍然有效：{cache_stats.write_warning}",
                        "warning",
                    )
                if plans:
                    reuse = (
                        f"；复用了 {cache_stats.reused_files} 个未变化文件的缓存" if cache_stats.reused_files else ""
                    )
                    message = f"预览完成，共识别 {len(plans)} 个文件{reuse}。"
                else:
                    message = "扫描完成，未找到支持的小说文件。"
                self._finish_operation(operation_id, "success", message)
            except OperationCancelled:
                with self._lock:
                    if self.operation["id"] == operation_id:
                        self.scan_cache_stats = session.cache_stats.to_dict()
                self._finish_operation(operation_id, "cancelled", "扫描已取消，原文件未发生变化。")
            except Exception as exc:  # noqa: BLE001 - 后台任务边界需将未知错误转为可恢复状态。
                with self._lock:
                    if self.operation["id"] == operation_id:
                        self.scan_cache_stats = session.cache_stats.to_dict()
                self._finish_operation(operation_id, "error", "扫描失败", error=str(exc))

        threading.Thread(target=work, name="novel-scan", daemon=True).start()
        return self.snapshot()

    def cancel_operation(self) -> dict[str, Any]:
        with self._lock:
            if self.operation["state"] != "running" or not self.operation["can_cancel"]:
                return {"cancelled": False, "state": self.snapshot()}
            if self._cancel_event:
                self._cancel_event.set()
            self.operation["message"] = "正在安全停止扫描…"
            self.operation["can_cancel"] = False
        return {"cancelled": True, "state": self.snapshot()}

    def start_apply(self) -> dict[str, Any]:
        with self._lock:
            if self.folder is None:
                raise ValueError("请先选择目录并扫描。")
            movable = sum(plan.will_move for plan in self.plans)
            if movable == 0:
                raise ValueError("当前预览没有可移动的文件。")
            plans = list(self.plans)
            report_path = self.folder / REPORT_FILE_NAME
            operation_id, _ = self._start_operation_locked(
                "apply",
                f"正在执行分类，共 {movable} 个文件需要移动…",
                total=len(plans),
            )

        def work() -> None:
            try:

                def report_progress(message: str) -> None:
                    self._append_log(message)
                    self._update_operation(operation_id, message=message)

                moved, skipped = execute_classification_plan(
                    plans,
                    progress=report_progress,
                    progress_count=lambda done, total: self._update_operation(
                        operation_id,
                        done=done,
                        total=total,
                    ),
                    report_path=report_path,
                )
                report = load_classification_report(report_path)
                self._archive_report_best_effort(report_path)
                actual_targets = {
                    str(item.get("source_path")): Path(str(item.get("actual_target_path")))
                    for item in report.get("items", [])
                    if isinstance(item, dict) and item.get("actual_target_path")
                }
                updated: list[ClassificationPlan] = []
                for plan in plans:
                    actual_target = actual_targets.get(str(plan.source_path))
                    if actual_target is None:
                        updated.append(plan)
                        continue
                    updated.append(
                        replace(
                            plan,
                            source_path=actual_target,
                            target_dir=actual_target.parent,
                            target_path=actual_target,
                            status="moved",
                            note="文件已移动，可通过本次报告撤销。",
                        )
                    )
                with self._lock:
                    if self.operation["id"] != operation_id:
                        return
                    self.plans = updated
                    self.plans_revision += 1
                    self.report_path = report_path
                self._finish_operation(
                    operation_id,
                    "success",
                    f"分类完成：移动 {moved} 个，跳过 {skipped} 个。",
                )
            except Exception as exc:  # noqa: BLE001 - 后台任务边界需将未知错误转为可恢复状态。
                if report_path.exists() and not report_path.is_symlink():
                    self._archive_report_best_effort(report_path)
                with self._lock:
                    self._invalidate_plans_locked()
                    self.report_path = report_path if report_path.exists() else None
                self._finish_operation(operation_id, "error", "分类执行失败", error=str(exc))

        threading.Thread(target=work, name="novel-apply", daemon=True).start()
        return self.snapshot()

    def _latest_report_locked(self) -> Path | None:
        if self.report_path and self.report_path.exists():
            return self.report_path
        return self._report_for_folder(self.folder)

    def _archive_report_best_effort(self, report_path: Path) -> Path | None:
        try:
            return archive_classification_report(report_path)
        except (OSError, RuntimeError, ValueError) as exc:
            self._append_log(f"分类报告已保留，但历史归档失败：{exc}", "warning")
            return None

    def start_undo(self, report_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            folder = self.folder
            report_path = self._latest_report_locked()
            self._assert_idle_locked()
        if folder is None:
            raise FileNotFoundError("请先选择要撤销的分类目录。")
        if report_id not in {None, "", "latest"}:
            report_path = resolve_classification_report(folder, report_id)
        if report_path is None:
            raise FileNotFoundError("当前目录没有可用的分类报告。")
        with self._lock:
            self._assert_idle_locked()
            if self.folder != folder:
                raise RuntimeError("分类目录已变化，请重新选择历史批次。")
            operation_id, _ = self._start_operation_locked(
                "undo",
                "正在按报告撤销上次分类…",
            )

        def work() -> None:
            try:

                def report_progress(message: str) -> None:
                    self._append_log(message)
                    self._update_operation(operation_id, message=message)

                restored, skipped = undo_classification_report(
                    report_path,
                    progress=report_progress,
                    progress_count=lambda done, total: self._update_operation(
                        operation_id,
                        done=done,
                        total=total,
                    ),
                )
                try:
                    mark_classification_report_undone(
                        report_path,
                        restored=restored,
                        skipped=skipped,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    self._append_log(f"文件已恢复，但报告状态未能更新：{exc}", "warning")
                if report_path.name == REPORT_FILE_NAME:
                    self._archive_report_best_effort(report_path)
                with self._lock:
                    self._invalidate_plans_locked()
                    self.report_path = self._report_for_folder(self.folder)
                self._finish_operation(
                    operation_id,
                    "success",
                    f"撤销完成：恢复 {restored} 个，跳过 {skipped} 个；请重新扫描。",
                )
            except Exception as exc:  # noqa: BLE001 - 后台任务边界需将未知错误转为可恢复状态。
                with self._lock:
                    self._invalidate_plans_locked()
                self._finish_operation(operation_id, "error", "撤销失败", error=str(exc))

        threading.Thread(target=work, name="novel-undo", daemon=True).start()
        return self.snapshot()

    def edit_plan(self, index: int, series_name: str) -> dict[str, Any]:
        return self.edit_plans(index, series_name, scope="single")["snapshot"]

    def edit_plans(
        self,
        index: int,
        series_name: str,
        *,
        scope: str,
        expected_plans_revision: int | None = None,
    ) -> dict[str, Any]:
        if len(series_name) > SERIES_NAME_MAX_CHARS:
            raise ValueError(f"系列名称不能超过 {SERIES_NAME_MAX_CHARS} 个字符。")
        if scope not in {"single", "same_series"}:
            raise ValueError("批量修正范围无效。")
        validated_scope = cast(Literal["single", "same_series"], scope)
        with self._lock:
            self._assert_idle_locked()
            if expected_plans_revision is not None and expected_plans_revision != self.plans_revision:
                raise RuntimeError("分类预览已变化，请重新选择文件后再修正。")
            original_plans = tuple(
                self.plans[plan_index]
                for plan_index in classification_plan_group_indices(
                    self.plans,
                    int(index),
                    validated_scope,
                )
            )
            revised_indices = revise_classification_plans(
                self.plans,
                int(index),
                series_name,
                scope=validated_scope,
            )
            self.plans_revision += 1
            revised = self.plans[int(index)]
            if len(revised_indices) == 1:
                message = f"已将 {revised.source_path.name} 修正为「{revised.series_name}」。"
            else:
                message = f"已将同系列的 {len(revised_indices)} 个条目批量修正为「{revised.series_name}」。"
            self._append_log(message, "success")
        learned_count, memory_error = self.correction_memory.try_remember_plans(
            original_plans,
            revised.series_name,
        )
        if memory_error is not None:
            self._append_log(
                f"修正已应用，但本地修正记忆未能保存：{memory_error}",
                "warning",
            )
        elif learned_count:
            self._append_log(
                f"已记住 {learned_count} 个系列别名，后续扫描会优先复用。",
                "info",
            )
        return {
            "updated_count": len(revised_indices),
            "updated_indices": list(revised_indices),
            "snapshot": self.snapshot(),
        }

    def load_candidates(
        self,
        index: int,
        *,
        expected_plans_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._assert_idle_locked()
            if expected_plans_revision is not None and expected_plans_revision != self.plans_revision:
                raise RuntimeError("分类预览已变化，请重新选择文件后再查找候选。")
            if index < 0 or index >= len(self.plans):
                raise IndexError("分类计划索引超出范围。")
            plan = self.plans[index]
            plans_revision = self.plans_revision
            use_network = self.settings.use_network
            metadata_providers = self._configured_provider_registry(self.settings)

        if not use_network:
            return {
                "index": index,
                "candidates": classification_candidate_payloads(plan),
                "warning": "在线识别已关闭，当前只显示本地候选。",
            }
        if not plan.network_query:
            return {
                "index": index,
                "candidates": classification_candidate_payloads(plan),
                "warning": "当前文件没有可安全联网的文件名查询，只显示本地候选。",
            }

        resolver = SeriesResolver(
            use_network=True,
            providers=metadata_providers,
            reliability=self.provider_reliability,
        )
        results = resolver.resolve_candidates(plan.network_query)
        remote_candidates = tuple(
            ClassificationCandidate(
                identity=result.identity,
                source=result.source,
                confidence=result.confidence,
            )
            for result in results
        )
        with self._lock:
            self._assert_idle_locked()
            if (
                self.plans_revision != plans_revision
                or index >= len(self.plans)
                or self.plans[index].source_path != plan.source_path
            ):
                raise RuntimeError("分类预览已变化，请重新选择文件后再查找候选。")
            updated = replace(
                self.plans[index],
                candidates=merge_classification_candidates(
                    self.plans[index].candidates,
                    remote_candidates,
                ),
            )
            self.plans[index] = updated

        warning = None
        if resolver.last_network_error:
            warning = "部分在线来源暂时不可用，已显示成功返回的候选。"
        elif not results:
            warning = "没有找到更多可靠候选。"
        return {
            "index": index,
            "candidates": classification_candidate_payloads(updated),
            "warning": warning,
        }

    def get_detail(
        self,
        index: int,
        *,
        expected_plans_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if expected_plans_revision is not None and expected_plans_revision != self.plans_revision:
                raise RuntimeError("分类预览已变化，请重新选择文件。")
            if index < 0 or index >= len(self.plans):
                raise IndexError("分类计划索引超出范围。")
            plan = self.plans[index]
            plans_revision = self.plans_revision
            use_network = self.settings.use_network
            metadata_providers = self._configured_provider_registry(self.settings)
            matching_series_count = len(
                classification_plan_group_indices(
                    self.plans,
                    index,
                    "same_series",
                )
            )

        metadata = None
        warning = None
        if use_network and plan.network_query:
            try:
                metadata = SeriesResolver(
                    use_network=True,
                    providers=metadata_providers,
                    reliability=self.provider_reliability,
                ).resolve_book_metadata_for_query(
                    plan.network_query,
                    series_name=plan.series_name,
                )
            except (OSError, RuntimeError) as exc:
                warning = f"详情暂时无法联网更新：{exc}"

        identity = merge_book_identities(
            plan.identity,
            metadata.identity if metadata else None,
            series_name=plan.series_name,
        )
        title = identity.title or plan.series_name
        summary = (metadata.summary if metadata else None) or plan.metadata_summary or "暂无可用简介。"
        subject_url = (metadata.url if metadata else None) or plan.metadata_url
        cover_url = (metadata.cover_url if metadata else None) or plan.metadata_cover_url
        local_cover_bytes = read_local_cover_bytes(plan.source_path)
        cover_bytes = local_cover_bytes
        if cover_bytes is None and cover_url:
            try:
                cover_bytes = http_bytes(cover_url, timeout=8.0, max_bytes=COVER_MAX_BYTES)
            except (OSError, RuntimeError, ValueError):
                cover_bytes = None

        cover_data_url = _data_uri(cover_bytes)
        detail_candidates = plan.candidates
        if metadata is not None:
            detail_candidates = merge_classification_candidates(
                plan.candidates,
                (
                    ClassificationCandidate(
                        identity=metadata.identity,
                        source=metadata.source,
                        confidence=metadata.confidence,
                    ),
                ),
            )

        result = {
            "index": index,
            "plans_revision": plans_revision,
            "identity": book_identity_to_dict(identity),
            "title": title,
            "summary": summary,
            "subject_url": subject_url,
            "cover_data_url": cover_data_url,
            "cover_source": "本地封面"
            if local_cover_bytes and cover_data_url
            else "在线封面"
            if cover_data_url
            else "无封面",
            "file_name": plan.source_path.name,
            "source_path": str(plan.source_path),
            "target_path": str(plan.target_path),
            "series_name": plan.series_name,
            "authors": list(identity.authors),
            "authors_label": "、".join(identity.authors) or "未识别",
            "volume_number": identity.volume_number,
            "volume_label": volume_display_name(identity.volume_number),
            "language": identity.language,
            "language_label": language_display_name(identity.language),
            "tags": list(identity.tags),
            "tags_label": " · ".join(identity.tags) or "未识别",
            "resolver_source": plan.resolver_source,
            "confidence_label": f"{plan.confidence:.0%}",
            "confidence_level": plan.confidence_level,
            "classification_reason": plan.classification_reason,
            "classification_evidence": list(plan.classification_evidence),
            "status": plan.status,
            "status_label": plan_status_label(plan.status),
            "note": plan.note,
            "warning": warning,
            "matching_series_count": matching_series_count,
            "can_load_candidates": bool(use_network and plan.network_query),
        }
        with self._lock:
            if (
                self.plans_revision != plans_revision
                or index >= len(self.plans)
                or self.plans[index].source_path != plan.source_path
            ):
                raise RuntimeError("分类预览已变化，请重新选择文件。")
            current_plan = self.plans[index]
            merged_candidates = merge_classification_candidates(
                current_plan.candidates,
                detail_candidates,
            )
            if merged_candidates != current_plan.candidates:
                current_plan = replace(current_plan, candidates=merged_candidates)
                self.plans[index] = current_plan
            result["candidates"] = classification_candidate_payloads(current_plan)
        return result

    def report_history(self) -> dict[str, Any]:
        with self._lock:
            folder = self.folder
            report_path = self._latest_report_locked()
            apply_running = self.operation["state"] == "running" and self.operation["kind"] == "apply"
        if folder is None:
            raise FileNotFoundError("请先选择要查看历史的分类目录。")

        archive_warning = None
        if report_path is not None and not apply_running:
            try:
                archive_classification_report(report_path)
            except (OSError, RuntimeError, ValueError) as exc:
                archive_warning = f"最新报告可用，但暂时无法写入历史归档：{exc}"
        result = list_classification_reports(folder, recover_latest=not apply_running)
        result["warning"] = archive_warning
        return result

    def report_summary(self, report_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            folder = self.folder
            report_path = self._latest_report_locked()
            apply_running = self.operation["state"] == "running" and self.operation["kind"] == "apply"
        if report_id not in {None, "", "latest"}:
            if folder is None:
                raise FileNotFoundError("请先选择要查看的分类目录。")
            report_path = resolve_classification_report(folder, report_id)
        if report_path is None:
            raise FileNotFoundError("当前目录没有分类报告。")
        report = load_classification_report(
            report_path,
            recover_pending=not apply_running,
        )
        summary = report.get("summary")
        items = report.get("items")
        if not isinstance(summary, dict) or not isinstance(items, list):
            raise ValueError("分类报告格式无效：summary 或 items 类型错误。")
        execution_id = report.get("execution_id")
        resolved_report_id = execution_id if isinstance(execution_id, str) and len(execution_id) == 32 else "latest"
        undo_completed_at = _report_text(report.get("undo_completed_at"), max_chars=64) or None
        moved_count = _report_count(summary.get("moved"))
        safe_items = [
            safe_item for item in items[:REPORT_UI_MAX_ITEMS] if (safe_item := _report_item_for_ui(item)) is not None
        ]
        return {
            "report_id": resolved_report_id,
            "path": str(report_path),
            "created_at": _report_text(report.get("created_at"), max_chars=64) or None,
            "undo_completed": undo_completed_at is not None,
            "undo_completed_at": undo_completed_at,
            "can_undo": undo_completed_at is None and moved_count > 0,
            "item_count": len(items),
            "items_truncated": len(items) > REPORT_UI_MAX_ITEMS,
            "summary": {
                "total": _report_count(summary.get("total")),
                "moved": moved_count,
                "skipped": _report_count(summary.get("skipped")),
                "duplicates": _report_count(summary.get("duplicates")),
                "errors": _report_count(summary.get("errors")),
            },
            "items": safe_items,
        }

    def current_folder(self) -> Path | None:
        with self._lock:
            return self.folder

    def current_report(self) -> Path | None:
        with self._lock:
            return self._latest_report_locked()

    def plan_path(self, index: int) -> Path:
        with self._lock:
            if index < 0 or index >= len(self.plans):
                raise IndexError("分类计划索引超出范围。")
            return self.plans[index].source_path
