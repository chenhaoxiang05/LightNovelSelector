import shutil
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lightnovel_selector import (
    build_classification_plan,
    execute_classification_plan,
    load_classification_report,
)


class ClassificationExecutionConcurrencyTests(unittest.TestCase):
    def test_rejected_concurrent_execution_keeps_active_report_protected(self) -> None:
        real_move = shutil.move
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_source = root / "A.Concurrent.Series.Vol.01.txt"
            second_source = root / "B.Concurrent.Series.Vol.02.txt"
            first_source.write_text("volume one", encoding="utf-8")
            second_source.write_text("volume two", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)
            report_path = root / "classification_report.json"
            journal_path = root / "classification_report.recovery.jsonl"
            move_finished = threading.Event()
            allow_first_execution_to_finish = threading.Event()

            def move_then_wait(source_path: str, target_path: str) -> str:
                result = real_move(source_path, target_path)
                move_finished.set()
                if not allow_first_execution_to_finish.wait(timeout=5):
                    raise TimeoutError("测试未及时释放第一次分类操作。")
                return result

            with (
                patch(
                    "lightnovel_selector.classification_execution.shutil.move",
                    side_effect=move_then_wait,
                ),
                ThreadPoolExecutor(max_workers=1) as executor,
            ):
                first_execution = executor.submit(
                    execute_classification_plan,
                    plans[:1],
                    report_path=report_path,
                )
                try:
                    self.assertTrue(move_finished.wait(timeout=5), "第一次分类操作没有进入预期暂停点。")
                    with self.assertRaisesRegex(ValueError, "尚未恢复|正在执行"):
                        execute_classification_plan(plans[1:], report_path=report_path)

                    active_report = load_classification_report(report_path)
                    self.assertEqual(active_report["summary"]["moved"], 0)
                    self.assertTrue(journal_path.is_file())
                finally:
                    allow_first_execution_to_finish.set()
                self.assertEqual(first_execution.result(timeout=5), (1, 0))

            self.assertEqual(load_classification_report(report_path)["summary"]["moved"], 1)
            self.assertFalse(journal_path.exists())
            self.assertTrue(second_source.is_file())

    def test_initial_report_failure_releases_execution_claim_for_retry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Retry.Series.Vol.01.txt"
            source.write_text("volume one", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)
            report_path = root / "classification_report.json"

            with (
                patch(
                    "lightnovel_selector.classification_execution.write_classification_report",
                    side_effect=OSError("报告暂时被占用"),
                ),
                self.assertRaisesRegex(OSError, "报告暂时被占用"),
            ):
                execute_classification_plan(plans, report_path=report_path)

            self.assertEqual(execute_classification_plan(plans, report_path=report_path), (1, 0))


if __name__ == "__main__":
    unittest.main()
