import json
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from lightnovel_selector.constants import (
    APP_NAME,
    REPORT_FILE_NAME,
    REPORT_HISTORY_DIR_NAME,
    REPORT_HISTORY_FILE_PREFIX,
    REPORT_HISTORY_ROOT_DIR_NAME,
    REPORT_SCHEMA_VERSION,
)
from lightnovel_selector.report_history import (
    _history_file_execution_id,
    archive_classification_report,
    classification_report_history_directory,
    list_classification_reports,
    mark_classification_report_undone,
    resolve_classification_report,
)


class ReportHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.execution_id = uuid.uuid4().hex
        self.stamp = "20240101T123456Z"

    def test_history_file_execution_id(self) -> None:
        valid_name = f"{REPORT_HISTORY_FILE_PREFIX}{self.stamp}-{self.execution_id}.json"
        self.assertEqual(_history_file_execution_id(Path(valid_name)), self.execution_id)

        invalid_names = [
            f"{REPORT_HISTORY_FILE_PREFIX}{self.stamp}-{self.execution_id}.txt",
            f"report-{self.stamp}-{self.execution_id}.json",
            f"{REPORT_HISTORY_FILE_PREFIX}20240101T12345Z-{self.execution_id}.json",  # wrong timestamp len
            f"{REPORT_HISTORY_FILE_PREFIX}20240101T1234567-{self.execution_id}.json", # wrong T/Z
            f"{REPORT_HISTORY_FILE_PREFIX}20240101_123456Z-{self.execution_id}.json",
            f"{REPORT_HISTORY_FILE_PREFIX}20240101T123456Z-{self.execution_id[:31]}.json", # short uuid
        ]

        for name in invalid_names:
            with self.subTest(name=name):
                self.assertIsNone(_history_file_execution_id(Path(name)))

    def test_classification_report_history_directory_creation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            history_root = root / REPORT_HISTORY_ROOT_DIR_NAME
            history_dir = history_root / REPORT_HISTORY_DIR_NAME

            # Without create=True, should return None if dir doesn't exist
            self.assertIsNone(classification_report_history_directory(root))

            # With create=True, should create and return dir
            result = classification_report_history_directory(root, create=True)
            self.assertIsNotNone(result)
            self.assertEqual(result, history_dir)
            self.assertTrue(history_dir.is_dir())

    def test_archive_classification_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / REPORT_FILE_NAME
            report = {
                "app": APP_NAME,
                "schema_version": REPORT_SCHEMA_VERSION,
                "execution_id": self.execution_id,
                "created_at": "2024-01-01T12:34:56Z",
                "summary": {"moved": 1},
                "root_path": str(root.resolve())
            }
            report_path.write_text(json.dumps(report), encoding="utf-8")

            # Missing execution_id
            invalid_report_path = root / "invalid.json"
            invalid_report_path.write_text(json.dumps({"app": APP_NAME, "schema_version": REPORT_SCHEMA_VERSION, "root_path": str(root.resolve())}), encoding="utf-8")
            with self.assertRaises(ValueError):
                archive_classification_report(invalid_report_path)

            # Archive the valid report
            archived_path = archive_classification_report(report_path)
            self.assertIsNotNone(archived_path)
            assert archived_path is not None
            self.assertTrue(archived_path.exists())
            self.assertTrue(archived_path.name.startswith(REPORT_HISTORY_FILE_PREFIX))
            self.assertTrue(archived_path.name.endswith(f"-{self.execution_id}.json"))

            # Idempotent archival
            archived_path2 = archive_classification_report(report_path)
            self.assertEqual(archived_path, archived_path2)

    def test_list_classification_reports(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            canonical = root / REPORT_FILE_NAME
            report1 = {
                "app": APP_NAME,
                "schema_version": REPORT_SCHEMA_VERSION,
                "execution_id": self.execution_id,
                "created_at": "2024-01-01T12:34:56Z",
                "summary": {"moved": 1, "total": 1, "skipped": 0, "duplicates": 0, "errors": 0},
                "version": "1.0.0",
                "root_path": str(root.resolve())
            }
            canonical.write_text(json.dumps(report1), encoding="utf-8")

            # Setup history dir
            history_dir = classification_report_history_directory(root, create=True)

            # Archive a different report
            assert history_dir is not None
            exec_id2 = uuid.uuid4().hex
            report2 = {
                "app": APP_NAME,
                "schema_version": REPORT_SCHEMA_VERSION,
                "execution_id": exec_id2,
                "created_at": "2023-01-01T12:34:56Z",
                "summary": {"moved": 5},
                "version": "1.0.0",
                "root_path": str(root.resolve())
            }
            history_path = history_dir / f"{REPORT_HISTORY_FILE_PREFIX}20230101T123456Z-{exec_id2}.json"
            history_path.write_text(json.dumps(report2), encoding="utf-8")

            # Add an invalid file to history
            invalid_path = history_dir / f"{REPORT_HISTORY_FILE_PREFIX}invalid.json"
            invalid_path.write_text("invalid", encoding="utf-8")

            result = list_classification_reports(root)
            self.assertEqual(result["total_count"], 2)
            self.assertEqual(result["invalid_count"], 1)
            self.assertFalse(result["truncated"])

            reports = result["reports"]
            self.assertEqual(len(reports), 2)
            self.assertEqual(reports[0]["report_id"], self.execution_id)
            self.assertTrue(reports[0]["is_latest"])
            self.assertEqual(reports[1]["report_id"], exec_id2)
            self.assertFalse(reports[1]["is_latest"])

    def test_resolve_classification_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            canonical = root / REPORT_FILE_NAME
            report = {
                "app": APP_NAME,
                "schema_version": REPORT_SCHEMA_VERSION,
                "execution_id": self.execution_id,
                "created_at": "2024-01-01T12:34:56Z",
                "summary": {"moved": 1},
                "root_path": str(root.resolve())
            }
            canonical.write_text(json.dumps(report), encoding="utf-8")

            # Resolve latest
            self.assertEqual(resolve_classification_report(root, None), canonical)
            self.assertEqual(resolve_classification_report(root, "latest"), canonical)

            # Resolve by id (canonical match)
            self.assertEqual(resolve_classification_report(root, self.execution_id), canonical)

            # Resolve by id (history match)
            canonical.unlink()
            history_dir = classification_report_history_directory(root, create=True)
            assert history_dir is not None
            history_path = history_dir / f"{REPORT_HISTORY_FILE_PREFIX}20240101T123456Z-{self.execution_id}.json"
            history_path.write_text(json.dumps(report), encoding="utf-8")

            self.assertEqual(resolve_classification_report(root, self.execution_id), history_path)

            # Non-existent
            with self.assertRaises(FileNotFoundError):
                resolve_classification_report(root, uuid.uuid4().hex)

    def test_mark_classification_report_undone(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / REPORT_FILE_NAME
            report = {
                "app": APP_NAME,
                "schema_version": REPORT_SCHEMA_VERSION,
                "execution_id": self.execution_id,
                "created_at": "2024-01-01T12:34:56Z",
                "summary": {"moved": 1},
                "root_path": str(root.resolve())
            }
            report_path.write_text(json.dumps(report), encoding="utf-8")

            mark_classification_report_undone(report_path, restored=1, skipped=0)

            updated = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIn("undo_completed_at", updated)
            self.assertEqual(updated["undo_summary"]["restored"], 1)
            self.assertEqual(updated["undo_summary"]["skipped"], 0)


if __name__ == "__main__":
    unittest.main()
