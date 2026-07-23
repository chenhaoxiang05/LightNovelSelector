import json
import unittest
import zipfile
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from lightnovel_selector import (
    APP_NAME,
    REMOTE_JSON_MAX_BYTES,
    REPORT_SCHEMA_VERSION,
    build_classification_plan,
    execute_classification_plan,
    http_bytes,
    http_json,
    load_classification_report,
    read_epub_cover_bytes,
    read_epub_identity_hint,
    undo_classification_report,
    validate_https_url,
)
from lightnovel_selector.application import ApplicationService
from lightnovel_selector.constants import SETTINGS_MAX_BYTES
from lightnovel_selector.models import ClassificationPlan
from lightnovel_selector.sidecar import MAX_REQUEST_CHARS, SidecarServer
from lightnovel_selector.storage import load_app_settings


class RemoteResponseSafetyTests(unittest.TestCase):
    def test_http_json_rejects_oversized_response(self) -> None:
        response = MagicMock()
        opened_response = response.__enter__.return_value
        opened_response.headers.get_content_charset.return_value = "utf-8"
        opened_response.read.return_value = b"x" * (REMOTE_JSON_MAX_BYTES + 1)

        opened_response.geturl.return_value = "https://example.test/search"
        with patch("lightnovel_selector.files._open_https", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "超过允许大小"):
                http_json("https://example.test/search")

        opened_response.read.assert_called_once_with(REMOTE_JSON_MAX_BYTES + 1)

    def test_http_json_normalizes_invalid_json_error(self) -> None:
        response = MagicMock()
        opened_response = response.__enter__.return_value
        opened_response.headers.get_content_charset.return_value = "utf-8"
        opened_response.read.return_value = b"{invalid"

        opened_response.geturl.return_value = "https://example.test/search"
        with patch("lightnovel_selector.files._open_https", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "无效 JSON"):
                http_json("https://example.test/search")

    def test_remote_requests_reject_unsafe_urls_before_opening(self) -> None:
        for url in (
            "file:///C:/Windows/win.ini",
            "http://example.test/cover.jpg",
            "https://user:secret@example.test/cover.jpg",
            "https://localhost/cover.jpg",
            "https://127.0.0.1/cover.jpg",
            "https://[::1]/cover.jpg",
        ):
            with self.subTest(url=url):
                with patch("lightnovel_selector.files._open_https") as opener:
                    with self.assertRaises(ValueError):
                        http_bytes(url, max_bytes=32)
                    opener.assert_not_called()

    def test_remote_request_rejects_https_redirect_downgrade(self) -> None:
        from lightnovel_selector.files import _HttpsOnlyRedirectHandler

        handler = _HttpsOnlyRedirectHandler()
        with self.assertRaises(ValueError):
            handler.redirect_request(
                MagicMock(),
                MagicMock(),
                302,
                "Found",
                MagicMock(),
                "http://example.test/cover.jpg",
            )

    def test_validate_https_url_accepts_public_https(self) -> None:
        self.assertEqual(
            validate_https_url("https://api.bgm.tv/v0/search/subjects"),
            "https://api.bgm.tv/v0/search/subjects",
        )


class EpubSafetyTests(unittest.TestCase):
    @staticmethod
    def malicious_epub(path: Path) -> None:
        container = b"""<?xml version="1.0"?>
<!DOCTYPE container [<!ENTITY xxe SYSTEM "file:///C:/Windows/win.ini">]>
<container><rootfiles><rootfile full-path="&xxe;"/></rootfiles></container>"""
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("META-INF/container.xml", container)

    def test_epub_dtd_is_rejected_without_reading_external_entity(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "unsafe.epub"
            self.malicious_epub(path)
            self.assertIsNone(read_epub_cover_bytes(path))
            self.assertIsNone(read_epub_identity_hint(path))


class SettingsSafetyTests(unittest.TestCase):
    def test_oversized_settings_file_falls_back_to_defaults(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_bytes(b" " * (SETTINGS_MAX_BYTES + 1))
            self.assertEqual(load_app_settings(path).last_folder, "")

    def test_string_booleans_are_not_treated_as_true(self) -> None:
        service = ApplicationService()
        with self.assertRaisesRegex(ValueError, "必须是布尔值"):
            service.save_settings(
                {
                    "use_network": "false",
                    "recursive": False,
                    "auto_rename": False,
                    "custom_rules": [],
                }
            )


class ReportSafetyTests(unittest.TestCase):
    def test_oversized_report_is_rejected_without_unbounded_read(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "classification_report.json"
            report_path.write_text('{"payload":"too large"}', encoding="utf-8")
            with patch("lightnovel_selector.classification.REPORT_MAX_BYTES", 8):
                with self.assertRaisesRegex(ValueError, "超过允许大小"):
                    load_classification_report(report_path)


class SidecarSafetyTests(unittest.TestCase):
    def test_oversized_request_is_rejected_and_next_request_still_works(self) -> None:
        oversized = "x" * (MAX_REQUEST_CHARS + 8) + "\n"
        input_stream = StringIO(oversized + '{"id":2,"method":"ping","params":{}}\n')
        output_stream = StringIO()
        SidecarServer(input_stream=input_stream, output_stream=output_stream).serve_forever()
        responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        self.assertFalse(responses[0]["ok"])
        self.assertEqual(responses[0]["error"]["type"], "ProtocolError")
        self.assertTrue(responses[1]["ok"])


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
        report: dict[str, object] = {
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

    def test_execute_rejects_source_outside_root_before_moving(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            root = workspace / "library"
            root.mkdir()
            outside = workspace / "outside.txt"
            outside.write_text("content", encoding="utf-8")
            target_dir = root / "Series"
            plan = ClassificationPlan(
                source_path=outside,
                series_name="Series",
                target_dir=target_dir,
                target_path=target_dir / outside.name,
                resolver_source="test",
                confidence=1.0,
                local_guess="Series",
            )

            with self.assertRaisesRegex(ValueError, "source_path 超出分类根目录"):
                execute_classification_plan([plan], report_path=root / "classification_report.json")

            self.assertTrue(outside.exists())
            self.assertFalse(target_dir.exists())

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
