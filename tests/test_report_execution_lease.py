from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from lightnovel_selector.report_execution_lease import (
    _WAIT_ABANDONED,
    _WAIT_FAILED,
    _WAIT_OBJECT_0,
    _WAIT_TIMEOUT,
    ReportExecutionLease,
    _report_mutex_name,
    report_execution_lease_is_active,
    try_acquire_report_execution_lease,
)


class TestReportExecutionLease(unittest.TestCase):
    def test_report_mutex_name(self) -> None:
        path = Path("test/path.json")
        name = _report_mutex_name(path)
        self.assertTrue(name.startswith("Local\\LightNovelSelector.ReportExecution."))
        self.assertEqual(len(name.split(".")[-1]), 64)  # sha256 hex digest length

    @patch("lightnovel_selector.report_execution_lease._CREATE_MUTEX_W", None)
    def test_acquire_lease_fallback_when_mutex_unsupported(self) -> None:
        lease = try_acquire_report_execution_lease(Path("test.json"))
        self.assertIsNotNone(lease)
        assert lease is not None
        self.assertIsNone(lease._handle)

        # Test release works without errors
        lease.release()
        self.assertTrue(lease._released)

    @patch("lightnovel_selector.report_execution_lease._CREATE_MUTEX_W", None)
    def test_lease_is_active_fallback_when_mutex_unsupported(self) -> None:
        is_active = report_execution_lease_is_active(Path("test.json"))
        self.assertFalse(is_active)

    def test_lease_release_idempotency(self) -> None:
        with patch("lightnovel_selector.report_execution_lease._RELEASE_MUTEX", create=True) as mock_release, \
             patch("lightnovel_selector.report_execution_lease._CLOSE_HANDLE", create=True) as mock_close:
            lease = ReportExecutionLease(_handle=123)
            lease.release()
            lease.release()

            mock_release.assert_called_once_with(123)
            mock_close.assert_called_once_with(123)
            self.assertTrue(lease._released)

    @patch("lightnovel_selector.report_execution_lease._CREATE_MUTEX_W", create=True)
    @patch("lightnovel_selector.report_execution_lease._WAIT_FOR_SINGLE_OBJECT", create=True)
    @patch("lightnovel_selector.report_execution_lease._CLOSE_HANDLE", create=True)
    def test_acquire_lease_success(
        self,
        mock_close: MagicMock,
        mock_wait: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_create.return_value = 123
        for wait_res in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
            with self.subTest(wait_res=wait_res):
                mock_wait.return_value = wait_res
                lease = try_acquire_report_execution_lease(Path("test.json"))
                self.assertIsNotNone(lease)
                assert lease is not None
                self.assertEqual(lease._handle, 123)
                mock_close.assert_not_called()

    @patch("lightnovel_selector.report_execution_lease._CREATE_MUTEX_W", create=True)
    @patch("lightnovel_selector.report_execution_lease.ctypes.get_last_error", create=True)
    def test_acquire_lease_create_mutex_fails(
        self,
        mock_get_last_error: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_create.return_value = 0
        mock_get_last_error.return_value = 5  # ERROR_ACCESS_DENIED

        with self.assertRaises(OSError) as context:
            try_acquire_report_execution_lease(Path("test.json"))

        self.assertIn("无法创建分类报告的跨进程互斥体", str(context.exception))

    @patch("lightnovel_selector.report_execution_lease._CREATE_MUTEX_W", create=True)
    @patch("lightnovel_selector.report_execution_lease._WAIT_FOR_SINGLE_OBJECT", create=True)
    @patch("lightnovel_selector.report_execution_lease._CLOSE_HANDLE", create=True)
    def test_acquire_lease_timeout(
        self,
        mock_close: MagicMock,
        mock_wait: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_create.return_value = 123
        mock_wait.return_value = _WAIT_TIMEOUT

        lease = try_acquire_report_execution_lease(Path("test.json"))
        self.assertIsNone(lease)
        mock_close.assert_called_once_with(123)

    @patch("lightnovel_selector.report_execution_lease._CREATE_MUTEX_W", create=True)
    @patch("lightnovel_selector.report_execution_lease._WAIT_FOR_SINGLE_OBJECT", create=True)
    @patch("lightnovel_selector.report_execution_lease._CLOSE_HANDLE", create=True)
    @patch("lightnovel_selector.report_execution_lease.ctypes.get_last_error", create=True)
    def test_acquire_lease_wait_failed(
        self,
        mock_get_last_error: MagicMock,
        mock_close: MagicMock,
        mock_wait: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_create.return_value = 123
        mock_wait.return_value = _WAIT_FAILED
        mock_get_last_error.return_value = 6  # ERROR_INVALID_HANDLE

        with self.assertRaises(OSError) as context:
            try_acquire_report_execution_lease(Path("test.json"))

        self.assertIn("无法检查分类报告的跨进程互斥体", str(context.exception))
        mock_close.assert_called_once_with(123)

    @patch("lightnovel_selector.report_execution_lease._CREATE_MUTEX_W", create=True)
    @patch("lightnovel_selector.report_execution_lease._WAIT_FOR_SINGLE_OBJECT", create=True)
    @patch("lightnovel_selector.report_execution_lease._CLOSE_HANDLE", create=True)
    def test_acquire_lease_unknown_wait_result(
        self,
        mock_close: MagicMock,
        mock_wait: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_create.return_value = 123
        mock_wait.return_value = 999

        with self.assertRaises(OSError) as context:
            try_acquire_report_execution_lease(Path("test.json"))

        self.assertIn("分类报告的跨进程互斥体返回未知状态", str(context.exception))
        mock_close.assert_called_once_with(123)

    @patch("lightnovel_selector.report_execution_lease.try_acquire_report_execution_lease")
    def test_lease_is_active_when_timeout(self, mock_try_acquire: MagicMock) -> None:
        mock_try_acquire.return_value = None

        is_active = report_execution_lease_is_active(Path("test.json"))
        self.assertTrue(is_active)

    @patch("lightnovel_selector.report_execution_lease.try_acquire_report_execution_lease")
    def test_lease_is_not_active_when_acquired(self, mock_try_acquire: MagicMock) -> None:
        mock_lease = MagicMock()
        mock_try_acquire.return_value = mock_lease

        is_active = report_execution_lease_is_active(Path("test.json"))
        self.assertFalse(is_active)
        mock_lease.release.assert_called_once()

if __name__ == "__main__":
    unittest.main()
