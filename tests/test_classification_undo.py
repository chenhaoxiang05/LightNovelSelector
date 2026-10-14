import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from lightnovel_selector.classification_execution import execute_classification_plan
from lightnovel_selector.classification_planning import build_classification_plan
from lightnovel_selector.classification_undo import undo_classification_report


class ClassificationUndoTests(unittest.TestCase):
    def test_undo_classification_report_restores_moved_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Sword.Art.Online.Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)

            restored, skipped = undo_classification_report(report_path)

            self.assertEqual((restored, skipped), (1, 0))
            self.assertTrue(book.exists())

    def test_callbacks_are_invoked(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Sword.Art.Online.Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)

            progress = Mock()
            progress_count = Mock()

            undo_classification_report(report_path, progress=progress, progress_count=progress_count)

            progress.assert_called_once()
            progress_count.assert_called_once_with(1, 1)

    def test_skips_already_restored_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Sword.Art.Online.Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)

            # Undo first time
            undo_classification_report(report_path)

            # Undo second time
            restored, skipped = undo_classification_report(report_path)

            self.assertEqual((restored, skipped), (0, 1))

    def test_raises_runtime_error_if_state_not_restored(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Sword.Art.Online.Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)

            with patch('lightnovel_selector.classification_undo.shutil.move'):
                with self.assertRaisesRegex(RuntimeError, "撤销操作完成后文件状态未达到预期，已停止后续操作。"):
                    undo_classification_report(report_path)


if __name__ == "__main__":
    unittest.main()
