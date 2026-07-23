import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from lightnovel_selector import (
    APP_NAME,
    REMOTE_JSON_MAX_BYTES,
    REPORT_SCHEMA_VERSION,
    build_classification_plan,
    execute_classification_plan,
    http_json,
    undo_classification_report,
)


class RemoteResponseSafetyTests(unittest.TestCase):
    def test_http_json_rejects_oversized_response(self) -> None:
        response = MagicMock()
        opened_response = response.__enter__.return_value
        opened_response.headers.get_content_charset.return_value = "utf-8"
        opened_response.read.return_value = b"x" * (REMOTE_JSON_MAX_BYTES + 1)

        with patch("lightnovel_selector.files.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "超过允许大小"):
                http_json("https://example.test/search")

        opened_response.read.assert_called_once_with(REMOTE_JSON_MAX_BYTES + 1)

    def test_http_json_normalizes_invalid_json_error(self) -> None:
        response = MagicMock()
        opened_response = response.__enter__.return_value
        opened_response.headers.get_content_charset.return_value = "utf-8"
        opened_response.read.return_value = b"{invalid"

        with patch("lightnovel_selector.files.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "无效 JSON"):
                http_json("https://example.test/search")


class UndoReportSafetyTests(unittest.TestCase):
    @staticmethod
    def write_report(
        report_path: Path,
        *,
        root_path: Path,
        source_path: Path,
        target_path: Path,
        schema_version: int | None = REPORT_SCHEMA_VERSION,
    ) -> None:
        report = {
            "app": APP_NAME,
            "version": "2.0.0",
            "items": [
                {
                    "operation": "moved",
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "actual_target_path": str(target_path),
                }
            ],
        }
        if schema_version is not None:
            report["schema_version"] = schema_version
            report["root_path"] = str(root_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    def test_generated_report_records_schema_and_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Sword.Art.Online.Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            report_path = root / "classification_report.json"

            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(report["schema_version"], REPORT_SCHEMA_VERSION)
            self.assertEqual(Path(report["root_path"]), root.resolve())
            self.assertEqual(undo_classification_report(report_path), (1, 0))

    def test_undo_rejects_source_outside_classification_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            root = workspace / "library"
            target = root / "Series" / "book.txt"
            target.parent.mkdir(parents=True)
            target.write_text("content", encoding="utf-8")
            report_path = root / "classification_report.json"
            self.write_report(
                report_path,
                root_path=root,
                source_path=workspace / "outside.txt",
                target_path=target,
            )

            with self.assertRaisesRegex(ValueError, "source_path 超出分类根目录"):
                undo_classification_report(report_path)

            self.assertTrue(target.exists())

    def test_undo_rejects_target_outside_classification_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            root = workspace / "library"
            root.mkdir()
            target = workspace / "outside.txt"
            target.write_text("content", encoding="utf-8")
            report_path = root / "classification_report.json"
            self.write_report(
                report_path,
                root_path=root,
                source_path=root / "book.txt",
                target_path=target,
            )

            with self.assertRaisesRegex(ValueError, "target_path 超出分类根目录"):
                undo_classification_report(report_path)

            self.assertTrue(target.exists())

    def test_undo_rejects_report_moved_out_of_classification_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "library"
            target = root / "Series" / "book.txt"
            target.parent.mkdir(parents=True)
            target.write_text("content", encoding="utf-8")
            report_path = root / "reports" / "classification_report.json"
            self.write_report(
                report_path,
                root_path=root,
                source_path=root / "book.txt",
                target_path=target,
            )

            with self.assertRaisesRegex(ValueError, "必须保留在生成它的分类根目录"):
                undo_classification_report(report_path)

            self.assertTrue(target.exists())

    def test_legacy_report_remains_usable_in_original_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "book.txt"
            target = root / "Series" / "book.txt"
            target.parent.mkdir()
            target.write_text("content", encoding="utf-8")
            report_path = root / "classification_report.json"
            self.write_report(
                report_path,
                root_path=root,
                source_path=source,
                target_path=target,
                schema_version=None,
            )

            self.assertEqual(undo_classification_report(report_path), (1, 0))
            self.assertTrue(source.exists())
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
