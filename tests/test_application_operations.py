from __future__ import annotations

import threading
import time
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from lightnovel_selector.application import ApplicationService
from lightnovel_selector.classification import build_classification_plan, count_plan_statuses
from lightnovel_selector.corrections import RecognitionCorrectionMemory
from lightnovel_selector.models import AppSettings, ClassificationPlan
from lightnovel_selector.scan_cache import PersistentScanCache


class ApplicationOperationProgressTests(unittest.TestCase):
    @staticmethod
    def wait_for_operation(service: ApplicationService, timeout: float = 5.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = service.snapshot()
            operation = snapshot["operation"]
            if isinstance(operation, dict) and operation["state"] != "running":
                return snapshot
            time.sleep(0.02)
        raise AssertionError("后台操作未在测试时限内完成")

    @staticmethod
    @contextmanager
    def configured_service(
        root: Path,
        plan_builder: Callable[..., list[ClassificationPlan]],
    ) -> Iterator[ApplicationService]:
        data_dir = root.parent / "app-data"
        with (
            patch(
                "lightnovel_selector.application.load_app_settings",
                return_value=AppSettings(use_network=False),
            ),
            patch("lightnovel_selector.application.try_save_app_settings", return_value=None),
            patch(
                "lightnovel_selector.application.PersistentScanCache",
                side_effect=lambda: PersistentScanCache(data_dir / "scan-cache.json"),
            ),
            patch(
                "lightnovel_selector.application.build_classification_plan",
                side_effect=plan_builder,
            ),
        ):
            service = ApplicationService(correction_memory=RecognitionCorrectionMemory(data_dir / "corrections.json"))
            service.set_folder(str(root))
            yield service

    def test_successful_scan_completes_reported_progress(self) -> None:
        def scan(*_args: object, **kwargs: object) -> list[ClassificationPlan]:
            progress_count = kwargs["progress_count"]
            assert callable(progress_count)
            progress_count(3, 5)
            return []

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "library"
            root.mkdir()
            with self.configured_service(root, scan) as service:
                service.start_scan()
                snapshot = self.wait_for_operation(service)

        operation = snapshot["operation"]
        self.assertIsInstance(operation, dict)
        self.assertEqual(operation["state"], "success")
        self.assertEqual(operation["done"], 5)
        self.assertEqual(operation["total"], 5)

    def test_poll_reuses_counts_until_the_preview_changes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "library"
            root.mkdir()
            (root / "星之旅 第1卷.txt").write_text("one", encoding="utf-8")
            (root / "月之门 第1卷.txt").write_text("two", encoding="utf-8")
            with self.configured_service(root, build_classification_plan) as service:
                service.start_scan()
                first = self.wait_for_operation(service)
                self.assertEqual(first["counts"]["series"], 2)
                first["counts"]["series"] = 0
                with patch("lightnovel_selector.application.count_plan_statuses", wraps=count_plan_statuses) as count:
                    poll = service.snapshot(plans_revision=first["plans_revision"])
                    self.assertEqual(poll["counts"]["series"], 2)
                    self.assertIsNone(poll["plans"])
                    count.assert_not_called()
                    edited = service.edit_plan(0, first["plans"][1]["series_name"])
                    self.assertEqual(edited["counts"]["series"], 1)
                    service.snapshot(plans_revision=edited["plans_revision"])
                    count.assert_called_once()

    def test_cancelled_scan_preserves_partial_progress(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def scan(*_args: object, **kwargs: object) -> list[ClassificationPlan]:
            progress_count = kwargs["progress_count"]
            checkpoint = kwargs["checkpoint"]
            assert callable(progress_count)
            assert callable(checkpoint)
            progress_count(2, 5)
            started.set()
            release.wait(timeout=2)
            checkpoint()
            return []

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "library"
            root.mkdir()
            with self.configured_service(root, scan) as service:
                service.start_scan()
                self.assertTrue(started.wait(timeout=1))
                try:
                    response = service.cancel_operation()
                    self.assertTrue(response["cancelled"])
                finally:
                    release.set()
                snapshot = self.wait_for_operation(service)

        operation = snapshot["operation"]
        self.assertIsInstance(operation, dict)
        self.assertEqual(operation["state"], "cancelled")
        self.assertEqual(operation["done"], 2)
        self.assertEqual(operation["total"], 5)

    def test_failed_scan_preserves_partial_progress(self) -> None:
        def scan(*_args: object, **kwargs: object) -> list[ClassificationPlan]:
            progress_count = kwargs["progress_count"]
            assert callable(progress_count)
            progress_count(2, 5)
            raise RuntimeError("模拟扫描失败")

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "library"
            root.mkdir()
            with self.configured_service(root, scan) as service:
                service.start_scan()
                snapshot = self.wait_for_operation(service)

        operation = snapshot["operation"]
        self.assertIsInstance(operation, dict)
        self.assertEqual(operation["state"], "error")
        self.assertEqual(operation["done"], 2)
        self.assertEqual(operation["total"], 5)
        self.assertEqual(operation["error"], "模拟扫描失败")


if __name__ == "__main__":
    unittest.main()
