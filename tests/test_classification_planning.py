import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lightnovel_selector import OperationCancelled, build_classification_plan
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
            root = Path(temp_dir)
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


if __name__ == "__main__":
    unittest.main()
