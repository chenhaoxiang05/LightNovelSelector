import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lightnovel_selector.constants import APP_NAME, REPORT_SCHEMA_VERSION
from lightnovel_selector.models import ClassificationPlan
from lightnovel_selector.classification_safety import (
    classification_report_root,
    _report_root,
    _validate_source_state,
)


class ClassificationSafetyReportRootTests(unittest.TestCase):
    def test_report_root_rejects_invalid_app_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "应用标识不匹配"):
            _report_root({"app": "WrongApp"}, Path("/tmp/report.json"))

    def test_report_root_rejects_invalid_schema(self) -> None:
        with self.assertRaisesRegex(ValueError, "schema_version 必须是整数"):
            _report_root({"app": APP_NAME, "schema_version": "2"}, Path("/tmp/report.json"))

        with self.assertRaisesRegex(ValueError, "不支持的撤销报告版本"):
            _report_root({"app": APP_NAME, "schema_version": 999}, Path("/tmp/report.json"))

    def test_report_root_v1_returns_parent(self) -> None:
        report_path = Path("/tmp/my_dir/report.json")
        root = _report_root({"app": APP_NAME, "schema_version": 1}, report_path)
        self.assertEqual(root, Path("/tmp/my_dir"))

    def test_report_root_v2_validates_root_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir).resolve()

            # Missing root_path
            with self.assertRaisesRegex(ValueError, "缺少分类根目录"):
                _report_root({"app": APP_NAME, "schema_version": 2}, Path("/tmp/report.json"))

            # Non-absolute root_path
            with self.assertRaisesRegex(ValueError, "必须是绝对路径"):
                _report_root({"app": APP_NAME, "schema_version": 2, "root_path": "relative/path"}, Path("/tmp/report.json"))

            # Valid root path (history path)
            from lightnovel_selector.constants import REPORT_HISTORY_ROOT_DIR_NAME, REPORT_HISTORY_DIR_NAME
            report_path = temp_path / REPORT_HISTORY_ROOT_DIR_NAME / REPORT_HISTORY_DIR_NAME / "report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)

            # Different parent
            with self.assertRaisesRegex(ValueError, "必须保留在生成它的分类根目录或历史目录中"):
                _report_root({
                    "app": APP_NAME,
                    "schema_version": 2,
                    "root_path": str(temp_path)
                }, temp_path / "other_dir" / "report.json")

            # Correct parent (history dir)
            root = _report_root({
                "app": APP_NAME,
                "schema_version": 2,
                "root_path": str(temp_path)
            }, report_path)
            self.assertEqual(root, temp_path)

            # Correct parent (root dir)
            root_direct = _report_root({
                "app": APP_NAME,
                "schema_version": 2,
                "root_path": str(temp_path)
            }, temp_path / "report.json")
            self.assertEqual(root_direct, temp_path)

class ClassificationSafetyValidateSourceStateTests(unittest.TestCase):
    def _create_mock_plan(self, source_path: Path, size: int | None = None, mtime: int | None = None) -> ClassificationPlan:
        # Dummy ClassificationPlan for testing validate_source_state
        from lightnovel_selector.models import BookIdentity
        return ClassificationPlan(
            source_path=source_path,
            identity=BookIdentity(title="Dummy", series_name="Dummy", authors=("Dummy",)),
            target_dir=Path("/dummy"),
            target_path=Path("/dummy/dummy.txt"),
            resolver_source="dummy",
            confidence=1.0,
            confidence_level="high",
            classification_reason="dummy",
            classification_evidence=("dummy",),
            local_guess="dummy",
            source_size=size,
            source_mtime_ns=mtime,
        )

    def test_validate_source_state_rejects_symlink(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            actual_file = temp_path / "actual.txt"
            actual_file.write_text("content", encoding="utf-8")

            symlink_file = temp_path / "link.txt"
            os.symlink(actual_file, symlink_file)

            plan = self._create_mock_plan(symlink_file)
            with self.assertRaisesRegex(ValueError, "变为符号链接"):
                _validate_source_state(plan)

    def test_validate_source_state_rejects_missing_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            missing_file = temp_path / "missing.txt"

            plan = self._create_mock_plan(missing_file)
            with self.assertRaisesRegex(ValueError, "已不存在或不再是普通文件"):
                _validate_source_state(plan)

    def test_validate_source_state_rejects_changed_size_or_mtime(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "test.txt"
            test_file.write_text("content", encoding="utf-8")

            stat = test_file.stat()

            # Changed size
            plan_wrong_size = self._create_mock_plan(test_file, size=stat.st_size + 1, mtime=stat.st_mtime_ns)
            with self.assertRaisesRegex(ValueError, "发生变化"):
                _validate_source_state(plan_wrong_size)

            # Changed mtime
            plan_wrong_mtime = self._create_mock_plan(test_file, size=stat.st_size, mtime=stat.st_mtime_ns + 1)
            with self.assertRaisesRegex(ValueError, "发生变化"):
                _validate_source_state(plan_wrong_mtime)

    def test_validate_source_state_accepts_valid_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "test.txt"
            test_file.write_text("content", encoding="utf-8")

            # With none checking
            plan_no_check = self._create_mock_plan(test_file)
            _validate_source_state(plan_no_check)  # Should not raise

            # With exact matching checking
            stat = test_file.stat()
            plan_exact = self._create_mock_plan(test_file, size=stat.st_size, mtime=stat.st_mtime_ns)
            _validate_source_state(plan_exact)  # Should not raise
