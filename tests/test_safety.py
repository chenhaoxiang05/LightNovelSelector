import json
import os
import socket
import unittest
import zipfile
from datetime import datetime
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
from lightnovel_selector.storage import load_app_settings, write_json_atomic


class RemoteResponseSafetyTests(unittest.TestCase):
    def test_http_json_rejects_oversized_response(self) -> None:
        response = MagicMock()
        opened_response = response.__enter__.return_value
        opened_response.headers.get_content_charset.return_value = "utf-8"
        opened_response.read.return_value = b"x" * (REMOTE_JSON_MAX_BYTES + 1)

        opened_response.geturl.return_value = "https://example.test/search"
        with (
            patch("lightnovel_selector.files._open_https", return_value=response),
            self.assertRaisesRegex(RuntimeError, "超过允许大小"),
        ):
            http_json("https://example.test/search")

        opened_response.read.assert_called_once_with(REMOTE_JSON_MAX_BYTES + 1)

    def test_http_json_normalizes_invalid_json_error(self) -> None:
        response = MagicMock()
        opened_response = response.__enter__.return_value
        opened_response.headers.get_content_charset.return_value = "utf-8"
        opened_response.read.return_value = b"{invalid"

        opened_response.geturl.return_value = "https://example.test/search"
        with (
            patch("lightnovel_selector.files._open_https", return_value=response),
            self.assertRaisesRegex(RuntimeError, "无效 JSON"),
        ):
            http_json("https://example.test/search")

    def test_http_json_normalizes_excessive_nesting(self) -> None:
        response = MagicMock()
        opened_response = response.__enter__.return_value
        opened_response.geturl.return_value = "https://example.test/search"
        opened_response.headers.get_content_charset.return_value = "utf-8"
        opened_response.read.return_value = b"{}"

        with (
            patch("lightnovel_selector.files._open_https", return_value=response),
            patch("lightnovel_selector.files.json.loads", side_effect=RecursionError),
            self.assertRaisesRegex(RuntimeError, "无效 JSON"),
        ):
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
            with self.subTest(url=url), patch("lightnovel_selector.files._open_https") as opener:
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

    def test_remote_request_rejects_domain_resolving_to_private_address(self) -> None:
        with (
            patch(
                "lightnovel_selector.files.socket.getaddrinfo",
                return_value=[
                    (
                        socket.AddressFamily.AF_INET,
                        socket.SocketKind.SOCK_STREAM,
                        socket.IPPROTO_TCP,
                        "",
                        ("127.0.0.1", 443),
                    )
                ],
            ),
            patch("lightnovel_selector.files._HTTPS_OPENER.open") as opener,
        ):
            with self.assertRaisesRegex(OSError, "内部网络"):
                http_bytes("https://example.test/cover.jpg", max_bytes=32)
            opener.assert_not_called()

    def test_remote_request_allows_trusted_provider_proxy_synthetic_address(self) -> None:
        response = MagicMock()
        opened_response = response.__enter__.return_value
        opened_response.geturl.return_value = "https://api.bgm.tv/cover.jpg"
        opened_response.read.return_value = b"image"
        with (
            patch(
                "lightnovel_selector.files.socket.getaddrinfo",
                return_value=[
                    (
                        socket.AddressFamily.AF_INET,
                        socket.SocketKind.SOCK_STREAM,
                        socket.IPPROTO_TCP,
                        "",
                        ("198.18.0.1", 443),
                    )
                ],
            ),
            patch("lightnovel_selector.files._HTTPS_OPENER.open", return_value=response) as opener,
        ):
            self.assertEqual(http_bytes("https://api.bgm.tv/cover.jpg", max_bytes=32), b"image")
            opener.assert_called_once()

    def test_remote_request_rejects_untrusted_proxy_synthetic_address(self) -> None:
        with (
            patch(
                "lightnovel_selector.files.socket.getaddrinfo",
                return_value=[
                    (
                        socket.AddressFamily.AF_INET,
                        socket.SocketKind.SOCK_STREAM,
                        socket.IPPROTO_TCP,
                        "",
                        ("198.18.0.1", 443),
                    )
                ],
            ),
            patch("lightnovel_selector.files._HTTPS_OPENER.open") as opener,
        ):
            with self.assertRaisesRegex(OSError, "内部网络"):
                http_bytes("https://example.test/cover.jpg", max_bytes=32)
            opener.assert_not_called()

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

    def test_excessively_nested_settings_fall_back_to_defaults(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text("{}", encoding="utf-8")

            with patch("lightnovel_selector.storage.json.loads", side_effect=RecursionError):
                self.assertEqual(load_app_settings(path).last_folder, "")

    def test_atomic_json_write_does_not_reuse_predictable_temporary_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "settings.json"
            predictable_path = root / f".settings.json.{os.getpid()}.tmp"
            predictable_path.write_text("sentinel", encoding="utf-8")

            write_json_atomic(path, {"saved": True})

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"saved": True},
            )
            self.assertEqual(
                predictable_path.read_text(encoding="utf-8"),
                "sentinel",
            )

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

    def test_malformed_rule_types_and_oversized_folder_are_ignored_on_load(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "last_folder": "x" * 40_000,
                        "custom_rules": [
                            {"pattern": ["not", "text"], "series": "Series"},
                            {"pattern": "valid", "series": {"not": "text"}},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            settings = load_app_settings(path)

            self.assertEqual(settings.last_folder, "")
            self.assertEqual(settings.custom_rules, ())

    def test_sidecar_settings_reject_non_string_rule_fields(self) -> None:
        service = ApplicationService()

        with self.assertRaisesRegex(ValueError, "必须是字符串"):
            service.save_settings(
                {
                    "use_network": False,
                    "recursive": False,
                    "auto_rename": False,
                    "custom_rules": [
                        {"pattern": ["not", "text"], "series": "Series"},
                    ],
                }
            )


class ReportSafetyTests(unittest.TestCase):
    def test_oversized_report_is_rejected_without_unbounded_read(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "classification_report.json"
            report_path.write_text('{"payload":"too large"}', encoding="utf-8")
            with (
                patch("lightnovel_selector.classification.REPORT_MAX_BYTES", 8),
                self.assertRaisesRegex(ValueError, "超过允许大小"),
            ):
                load_classification_report(report_path)

    def test_excessively_nested_report_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "classification_report.json"
            report_path.write_text("{}", encoding="utf-8")

            with (
                patch("lightnovel_selector.classification.json.loads", side_effect=RecursionError),
                self.assertRaisesRegex(ValueError, "格式无效"),
            ):
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
            self.assertIsNotNone(datetime.fromisoformat(report["created_at"]).utcoffset())
            self.assertEqual(report["items"][0]["source_size"], 3)
            self.assertIsInstance(report["items"][0]["source_mtime_ns"], int)
            self.assertEqual(undo_classification_report(report_path), (1, 0))
            self.assertEqual(undo_classification_report(report_path), (0, 1))

    def test_recovery_journal_rejects_target_outside_classification_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            root = workspace / "library"
            root.mkdir()
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("original", encoding="utf-8")
            report_path = root / "classification_report.json"
            journal_path = root / "classification_report.recovery.jsonl"
            plans = build_classification_plan(root, use_network=False)

            with (
                patch(
                    "lightnovel_selector.classification.shutil.move",
                    side_effect=KeyboardInterrupt,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                execute_classification_plan(plans, report_path=report_path)

            records = [
                json.loads(line)
                for line in journal_path.read_text(encoding="utf-8").splitlines()
            ]
            records[1]["actual_target_path"] = str(workspace / "outside.txt")
            journal_path.write_text(
                "".join(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "超出分类根目录"):
                load_classification_report(report_path)

            self.assertTrue(source.exists())
            self.assertTrue(journal_path.exists())

    def test_recovery_journal_rejects_invalid_identity_metadata(self) -> None:
        for mutation, expected_message in (
            ("boolean schema", "不匹配"),
            ("floating schema", "不匹配"),
            ("invalid execution id", "无效执行编号"),
        ):
            with self.subTest(mutation=mutation), TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                source = root / "Sword.Art.Online.Vol.01.txt"
                source.write_text("original", encoding="utf-8")
                report_path = root / "classification_report.json"
                journal_path = root / "classification_report.recovery.jsonl"
                plans = build_classification_plan(root, use_network=False)

                with (
                    patch(
                        "lightnovel_selector.classification.shutil.move",
                        side_effect=KeyboardInterrupt,
                    ),
                    self.assertRaises(KeyboardInterrupt),
                ):
                    execute_classification_plan(plans, report_path=report_path)

                report = json.loads(report_path.read_text(encoding="utf-8"))
                records = [
                    json.loads(line)
                    for line in journal_path.read_text(encoding="utf-8").splitlines()
                ]
                if mutation == "boolean schema":
                    records[0]["schema_version"] = True
                elif mutation == "floating schema":
                    records[0]["schema_version"] = 1.0
                else:
                    report["execution_id"] = "not-a-valid-execution-id"
                    records[0]["execution_id"] = report["execution_id"]
                report_path.write_text(
                    json.dumps(report, ensure_ascii=False),
                    encoding="utf-8",
                )
                journal_path.write_text(
                    "".join(
                        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                        for record in records
                    ),
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ValueError, expected_message):
                    load_classification_report(report_path)

                self.assertTrue(source.exists())
                self.assertTrue(journal_path.exists())

    def test_undo_rejects_file_modified_after_classification(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("original", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            target = Path(report["items"][0]["actual_target_path"])
            target.write_text("changed after classification", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "已发生变化"):
                undo_classification_report(report_path)

            self.assertFalse(source.exists())
            self.assertTrue(target.exists())

    def test_undo_rejects_target_replaced_by_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("original", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            target = Path(report["items"][0]["actual_target_path"])
            target.unlink()
            target.mkdir()

            with self.assertRaisesRegex(ValueError, "不再是原来的普通文件"):
                undo_classification_report(report_path)

            self.assertFalse(source.exists())
            self.assertTrue(target.is_dir())

    def test_undo_rejects_target_replaced_by_symbolic_link(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("original", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            target = Path(report["items"][0]["actual_target_path"])
            replacement = target.with_name("replacement.txt")
            target.replace(replacement)
            try:
                target.symlink_to(replacement)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"当前测试环境无法创建符号链接：{exc}")

            with self.assertRaisesRegex(ValueError, "符号链接"):
                undo_classification_report(report_path)

            self.assertFalse(source.exists())
            self.assertTrue(target.is_symlink())
            self.assertTrue(replacement.exists())

    def test_undo_rejects_ambiguous_batch_before_restoring_any_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A Sword.Art.Online.Vol.01.txt"
            second = root / "B Sword.Art.Online.Vol.02.txt"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)
            first.write_text("unexpected source occupant", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "同时存在.*状态存在歧义"):
                undo_classification_report(report_path)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(first.exists())
            self.assertFalse(second.exists())
            self.assertTrue(Path(report["items"][0]["actual_target_path"]).exists())
            self.assertTrue(Path(report["items"][1]["actual_target_path"]).exists())

    def test_undo_rejects_when_source_and_target_are_both_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("original", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            target = Path(report["items"][0]["actual_target_path"])
            target.unlink()

            with self.assertRaisesRegex(ValueError, "均不存在.*状态存在歧义"):
                undo_classification_report(report_path)

            self.assertFalse(source.exists())
            self.assertFalse(target.exists())

    def test_repeated_undo_rejects_restored_file_changed_afterwards(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("original", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)
            self.assertEqual(undo_classification_report(report_path), (1, 0))
            source.write_text("changed after restoration", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "源位置的文件已发生变化"):
                undo_classification_report(report_path)

            self.assertTrue(source.exists())

    def test_undo_can_resume_after_forced_interruption(self) -> None:
        from shutil import move as real_move

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A Sword.Art.Online.Vol.01.txt"
            second = root / "B Sword.Art.Online.Vol.02.txt"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)
            move_count = 0

            def interrupt_second_restore(source_path, target_path):
                nonlocal move_count
                move_count += 1
                if move_count == 2:
                    raise KeyboardInterrupt
                return real_move(source_path, target_path)

            with (
                patch(
                    "lightnovel_selector.classification.shutil.move",
                    side_effect=interrupt_second_restore,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                undo_classification_report(report_path)

            self.assertEqual(undo_classification_report(report_path), (1, 1))
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())

    def test_undo_rejects_partial_copy_left_by_failed_move(self) -> None:
        from shutil import copy2

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("original", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            target = Path(report["items"][0]["actual_target_path"])

            def copy_then_fail(source_path, target_path):
                copy2(source_path, target_path)
                raise OSError("simulated cross-volume cleanup failure")

            with (
                patch(
                    "lightnovel_selector.classification.shutil.move",
                    side_effect=copy_then_fail,
                ),
                self.assertRaisesRegex(OSError, "cross-volume"),
            ):
                undo_classification_report(report_path)

            self.assertTrue(source.exists())
            self.assertTrue(target.exists())
            with self.assertRaisesRegex(ValueError, "同时存在.*状态存在歧义"):
                undo_classification_report(report_path)

    def test_undo_verifies_move_postcondition(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("original", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            target = Path(report["items"][0]["actual_target_path"])

            with (
                patch("lightnovel_selector.classification.shutil.move", return_value=None),
                self.assertRaisesRegex(RuntimeError, "文件状态未达到预期"),
            ):
                undo_classification_report(report_path)

            self.assertFalse(source.exists())
            self.assertTrue(target.exists())

    def test_undo_rejects_incomplete_file_state_fields(self) -> None:
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
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["items"][0]["source_size"] = target.stat().st_size
            report_path.write_text(json.dumps(report), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "必须同时存在或同时省略"):
                undo_classification_report(report_path)

            self.assertFalse(source.exists())
            self.assertTrue(target.exists())

    def test_undo_rechecks_each_target_during_long_batch(self) -> None:
        from shutil import move as real_move

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A Sword.Art.Online.Vol.01.txt"
            second = root / "B Sword.Art.Online.Vol.02.txt"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            execute_classification_plan(plans, report_path=report_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            first_target = Path(report["items"][0]["actual_target_path"])
            move_count = 0

            def change_next_target_after_first_restore(source_path, target_path):
                nonlocal move_count
                result = real_move(source_path, target_path)
                move_count += 1
                if move_count == 1:
                    first_target.write_text(
                        "changed while undo was running",
                        encoding="utf-8",
                    )
                return result

            with patch(
                "lightnovel_selector.classification.shutil.move",
                side_effect=change_next_target_after_first_restore,
            ), self.assertRaisesRegex(ValueError, "已发生变化"):
                undo_classification_report(report_path)

            self.assertFalse(first.exists())
            self.assertTrue(first_target.exists())
            self.assertTrue(second.exists())

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

    def test_execute_rejects_source_replaced_by_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("content", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)

            source.unlink()
            source.mkdir()

            with self.assertRaisesRegex(ValueError, "不再是普通文件"):
                execute_classification_plan(plans, report_path=root / "classification_report.json")

            self.assertTrue(source.is_dir())
            self.assertFalse((root / "classification_report.json").exists())

    def test_execute_rejects_target_directory_replaced_by_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("content", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)
            target_dir = plans[0].target_dir
            target_dir.write_text("occupied", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "目标目录已被其他文件占用"):
                execute_classification_plan(
                    plans,
                    report_path=root / "classification_report.json",
                )

            self.assertTrue(source.exists())
            self.assertTrue(target_dir.is_file())

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
