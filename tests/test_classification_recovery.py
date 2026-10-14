import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from lightnovel_selector.classification_recovery import (
    _append_move_intent,
    _claim_report_execution,
    _read_report_journal,
    _recover_classification_report,
    _release_report_execution,
    _remove_report_journal,
    _report_execution_is_active,
    _report_journal_path,
    _start_report_journal,
    _ACTIVE_REPORT_PATHS,
    _ACTIVE_REPORT_LEASES,
)
from lightnovel_selector.constants import REPORT_JOURNAL_SCHEMA_VERSION, SCAN_MAX_FILES

class ClassificationRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_dir_path = Path(self.temp_dir.name)

        # Reset global state for tests
        _ACTIVE_REPORT_PATHS.clear()
        _ACTIVE_REPORT_LEASES.clear()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        _ACTIVE_REPORT_PATHS.clear()
        _ACTIVE_REPORT_LEASES.clear()

    def test_report_journal_path(self) -> None:
        report_path = self.temp_dir_path / "classification_report.json"
        expected_journal_path = self.temp_dir_path / "classification_report.recovery.jsonl"

        self.assertEqual(_report_journal_path(report_path), expected_journal_path.resolve())

    @patch("lightnovel_selector.classification_recovery.try_acquire_report_execution_lease")
    def test_claim_and_release_report_execution(self, mock_try_acquire: unittest.mock.MagicMock) -> None:
        report_path = self.temp_dir_path / "classification_report.json"

        # Mock successful lease acquisition
        mock_lease = unittest.mock.MagicMock()
        mock_try_acquire.return_value = mock_lease

        # Initially inactive
        self.assertFalse(_report_execution_is_active(report_path))

        # Claim
        _claim_report_execution(report_path)
        self.assertTrue(_report_execution_is_active(report_path))
        self.assertIn(report_path, _ACTIVE_REPORT_PATHS)
        mock_try_acquire.assert_called_once_with(report_path)

        # Re-claiming the same path should fail
        with self.assertRaisesRegex(ValueError, "同一分类报告已有正在执行的分类操作"):
            _claim_report_execution(report_path)

        # Release
        _release_report_execution(report_path)
        self.assertFalse(report_path in _ACTIVE_REPORT_PATHS)
        mock_lease.release.assert_called_once()

        # Re-releasing should not error
        _release_report_execution(report_path)

    @patch("lightnovel_selector.classification_recovery.try_acquire_report_execution_lease")
    def test_claim_fails_on_lease_conflict(self, mock_try_acquire: unittest.mock.MagicMock) -> None:
        report_path = self.temp_dir_path / "classification_report.json"
        mock_try_acquire.return_value = None  # Simulate locked by another process

        with self.assertRaisesRegex(ValueError, "另一个程序正在整理同一书库"):
            _claim_report_execution(report_path)

    @patch("lightnovel_selector.classification_recovery.report_execution_lease_is_active")
    def test_report_execution_is_active_with_system_lease(self, mock_lease_active: unittest.mock.MagicMock) -> None:
        report_path = self.temp_dir_path / "classification_report.json"
        mock_lease_active.return_value = True

        # When not in our memory set, checks the lease
        self.assertTrue(_report_execution_is_active(report_path))
        mock_lease_active.assert_called_once_with(report_path)

    def test_start_and_append_and_read_report_journal(self) -> None:
        report_path = self.temp_dir_path / "classification_report.json"
        execution_id = uuid.uuid4().hex

        # 1. Start journal
        journal_path = _start_report_journal(report_path, execution_id)
        self.assertTrue(journal_path.exists())
        self.assertTrue(journal_path.name.endswith(".recovery.jsonl"))

        # Re-starting should fail because file exists
        with self.assertRaisesRegex(ValueError, "检测到尚未恢复的分类操作"):
            _start_report_journal(report_path, execution_id)

        # 2. Append intents
        source_path = self.temp_dir_path / "src.txt"
        target_path = self.temp_dir_path / "dst.txt"
        _append_move_intent(journal_path, execution_id, source_path, target_path)

        # 3. Read journal
        records = _read_report_journal(journal_path)
        self.assertEqual(len(records), 2)

        header = records[0]
        self.assertEqual(header["type"], "header")
        self.assertEqual(header["schema_version"], REPORT_JOURNAL_SCHEMA_VERSION)
        self.assertEqual(header["execution_id"], execution_id)

        intent = records[1]
        self.assertEqual(intent["type"], "move_intent")
        self.assertEqual(intent["execution_id"], execution_id)
        self.assertEqual(intent["source_path"], str(source_path))
        self.assertEqual(intent["actual_target_path"], str(target_path))

    def test_remove_report_journal(self) -> None:
        journal_path = self.temp_dir_path / "test.recovery.jsonl"
        journal_path.write_text("{}")
        self.assertTrue(journal_path.exists())

        _remove_report_journal(journal_path)
        self.assertFalse(journal_path.exists())

        # Removing non-existent should not error
        _remove_report_journal(journal_path)

    def test_read_report_journal_errors(self) -> None:
        journal_path = self.temp_dir_path / "test.recovery.jsonl"

        # Directory instead of file
        journal_path.mkdir()
        with self.assertRaisesRegex(ValueError, "分类恢复日志不是可信的普通文件"):
            _read_report_journal(journal_path)
        journal_path.rmdir()

        # Empty file
        journal_path.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "分类恢复日志为空"):
            _read_report_journal(journal_path)

        # Invalid JSON
        journal_path.write_bytes(b"not json\n")
        with self.assertRaisesRegex(ValueError, "分类恢复日志第 1 行格式无效"):
            _read_report_journal(journal_path)

        # Not a dict
        journal_path.write_bytes(b"[1, 2, 3]\n")
        with self.assertRaisesRegex(ValueError, "分类恢复日志第 1 行必须是对象"):
            _read_report_journal(journal_path)

        # Too many lines
        lines = [b'{"a": 1}'] * (SCAN_MAX_FILES + 2)
        journal_path.write_bytes(b"\n".join(lines))
        with self.assertRaisesRegex(ValueError, "分类恢复日志包含过多记录"):
            _read_report_journal(journal_path)

    def test_recover_classification_report(self) -> None:
        report_path = self.temp_dir_path / "classification_report.json"
        execution_id = uuid.uuid4().hex

        # Write some data to a journal
        journal_path = _start_report_journal(report_path, execution_id)
        source_path = self.temp_dir_path / "src.txt"
        target_path = self.temp_dir_path / "dst.txt"
        _append_move_intent(journal_path, execution_id, source_path, target_path)

        from lightnovel_selector.constants import APP_NAME, REPORT_SCHEMA_VERSION
        report = {
            "app": APP_NAME,
            "schema_version": REPORT_SCHEMA_VERSION,
            "execution_id": execution_id,
            "root_path": str(self.temp_dir_path),
            "items": [
                {
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "source_size": 100,
                    "source_mtime_ns": 1000,
                }
            ],
            "summary": {"skipped": 0, "moved": 0}
        }

        # Test missing actual actual move -> actual target file missing.
        # we need to create it and pass the correct expected size and mtime to not fail validation.
        # Actually in _recover_classification_report, it calls _reported_move_state
        # We can just patch _reported_move_state to return "moved" and test success.

        with patch("lightnovel_selector.classification_recovery._reported_move_state", return_value="moved"):
            recovered = _recover_classification_report(report, report_path, journal_path)

        self.assertEqual(recovered["summary"]["moved"], 1)
        self.assertEqual(recovered["items"][0]["actual_target_path"], str(target_path))
        self.assertEqual(recovered["items"][0]["operation"], "moved")
        self.assertFalse(journal_path.exists()) # Journal should be deleted on success

if __name__ == "__main__":
    unittest.main()
