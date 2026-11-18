import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lightnovel_selector import (
    ClassificationPlan,
    OperationCancelled,
    build_classification_plan,
    revise_classification_plans,
)
from lightnovel_selector.cancellation import OperationCancelled as SharedOperationCancelled
from lightnovel_selector.scan_session import OperationCancelled as SessionOperationCancelled


class ClassificationPlanningCancellationTests(unittest.TestCase):
    def test_cancellation_during_file_analysis_propagates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Demo.Vol.01.txt").write_text("content", encoding="utf-8")

            with (
                patch(
                    "lightnovel_selector.classification_planning.read_identity_hint",
                    side_effect=OperationCancelled("扫描已取消。"),
                ),
                self.assertRaisesRegex(OperationCancelled, "扫描已取消"),
            ):
                build_classification_plan(root, use_network=False)

    def test_non_cancellation_runtime_error_remains_a_file_error(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            book = root / "Demo.Vol.01.txt"
            book.write_text("content", encoding="utf-8")

            with patch(
                "lightnovel_selector.classification_planning.read_identity_hint",
                side_effect=RuntimeError("解析器暂时不可用"),
            ):
                plans = build_classification_plan(root, use_network=False)

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].source_path, book)
        self.assertEqual(plans[0].status, "error")
        self.assertEqual(plans[0].note, "解析器暂时不可用")

    def test_public_and_legacy_imports_share_the_same_cancellation_type(self) -> None:
        self.assertIs(OperationCancelled, SharedOperationCancelled)
        self.assertIs(OperationCancelled, SessionOperationCancelled)


class ClassificationPlanningProgressTests(unittest.TestCase):
    def test_mixed_batch_preserves_order_statuses_and_progress_contract(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            first = root / "Alpha.Vol.01.txt"
            duplicate = root / "Beta.Vol.01.txt"
            broken = root / "Gamma.Vol.01.txt"
            first.write_text("same content", encoding="utf-8")
            duplicate.write_text("same content", encoding="utf-8")
            broken.write_text("different content", encoding="utf-8")
            messages: list[str] = []
            counts: list[tuple[int, int]] = []

            def read_hint(path: Path) -> None:
                if path == broken:
                    raise RuntimeError("解析器暂时不可用")

            with patch(
                "lightnovel_selector.classification_planning.read_identity_hint",
                side_effect=read_hint,
            ):
                plans = build_classification_plan(
                    root,
                    use_network=False,
                    progress=messages.append,
                    progress_count=lambda current, total: counts.append((current, total)),
                )

        self.assertEqual([plan.source_path for plan in plans], [first, duplicate, broken])
        self.assertEqual([plan.status for plan in plans], ["ready", "duplicate", "error"])
        self.assertEqual(
            messages,
            [
                "正在查找支持的小说文件…",
                "正在检查 3 个文件的重复内容…",
                "[1/3] 识别：Alpha.Vol.01.txt",
                "[2/3] 识别：Beta.Vol.01.txt",
                "[3/3] 识别：Gamma.Vol.01.txt",
            ],
        )
        self.assertEqual(counts, [(1, 3), (2, 3), (3, 3)])


class ClassificationBatchEditTests(unittest.TestCase):
    def test_same_filename_keeps_existing_and_pending_reservations(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "Corrected"
            target.mkdir()
            (target / "Book (1).txt").touch()
            plans = [
                ClassificationPlan(root / "a/Book.txt", "Old", root / "Old", root / "Old/Book.txt"),
                ClassificationPlan(root / "b/Book.txt", "Old", target, target / "Book.txt"),
                ClassificationPlan(root / "c/Book.txt", "Other", target, target / "Book (2).txt"),
            ]
            other = plans[-1]
            self.assertEqual(revise_classification_plans(plans, 0, "Corrected", scope="same_series"), (0, 1))
            self.assertEqual([p.target_path.name for p in plans], ["Book (3).txt", "Book.txt", "Book (2).txt"])
            self.assertIs(plans[-1], other)


if __name__ == "__main__":
    unittest.main()
