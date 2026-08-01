from __future__ import annotations

import io
import json
import math
import random
import re
import shutil
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lightnovel_selector import (
    build_classification_plan,
    clean_file_stem,
    execute_classification_plan,
    extract_book_lookup_query,
    extract_series_guess,
    infer_language,
    load_classification_report,
    normalize_title_text,
    parse_volume_number,
    read_epub_book_identity,
    read_epub_cover_bytes,
    read_epub_identity_hint,
    read_local_cover_bytes,
    read_zip_member,
    safe_folder_name,
    score_title,
    undo_classification_report,
)
from lightnovel_selector.constants import SERIES_NAME_MAX_CHARS
from lightnovel_selector.models import ClassificationPlan
from lightnovel_selector.sidecar import SidecarServer

_UNSAFE_TEXT_CONTROLS = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u061c\u200e\u200f"
    r"\u202a-\u202e\u2066-\u206f\ud800-\udfff]"
)


class FilenamePropertyTests(unittest.TestCase):
    def test_filename_parsers_preserve_bounded_utf8_safe_invariants(self) -> None:
        random_source = random.Random(0x51DEC0DE)
        alphabet = list("abcXYZ01239 ._-[]()<>:\\/?*|轻小说魔法少女日本語テスト") + [
            "\x00",
            "\x1f",
            "\x7f",
            "\u061c",
            "\u202e",
            "\u2066",
            "\ud800",
            "\udfff",
            "\u0301",
        ]
        cases = [
            "",
            ".",
            "CON.txt",
            "\ud800\u202eSword Art Online Vol.01.txt",
            "A" * 1024,
        ]
        cases.extend(
            "".join(random_source.choice(alphabet) for _ in range(random_source.randrange(0, 180))) for _ in range(512)
        )

        self.addCleanup(extract_book_lookup_query.cache_clear)
        self.addCleanup(extract_series_guess.cache_clear)
        for case_number, value in enumerate(cases):
            with self.subTest(case_number=case_number):
                outputs = (
                    normalize_title_text(value),
                    clean_file_stem(value),
                    extract_book_lookup_query(value),
                    extract_series_guess(value),
                )
                for output in outputs:
                    self.assertIsInstance(output, str)
                    output.encode("utf-8", errors="strict")
                    self.assertIsNone(_UNSAFE_TEXT_CONTROLS.search(output))

                folder_name = safe_folder_name(value)
                folder_name.encode("utf-8", errors="strict")
                self.assertTrue(folder_name)
                self.assertLessEqual(len(folder_name), SERIES_NAME_MAX_CHARS)
                self.assertEqual(folder_name, folder_name.rstrip(" ."))
                self.assertIsNone(_UNSAFE_TEXT_CONTROLS.search(folder_name))
                self.assertIsNone(re.search(r'[<>:"/\\|?*]', folder_name))

                volume = parse_volume_number(value)
                self.assertTrue(volume is None or 0 <= volume <= 999)
                self.assertIn(infer_language(value), {None, "zh-Hans", "zh-Hant", "ja", "ko", "en"})
                similarity = score_title(value, value[::-1])
                self.assertTrue(math.isfinite(similarity))
                self.assertGreaterEqual(similarity, 0.0)
                self.assertLessEqual(similarity, 1.0)


class ArchiveFaultInjectionTests(unittest.TestCase):
    @staticmethod
    def _valid_epub_bytes() -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("mimetype", "application/epub+zip")
            archive.writestr(
                "META-INF/container.xml",
                """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
            )
            archive.writestr(
                "OEBPS/content.opf",
                """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Fault Matrix Vol. 1</dc:title>
  </metadata>
  <manifest>
    <item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="chapter"/></spine>
</package>""",
            )
            archive.writestr("OEBPS/cover.jpg", b"not-a-real-image")
            archive.writestr("OEBPS/chapter.xhtml", "<html><body>chapter</body></html>")
        return output.getvalue()

    def _assert_archive_readers_are_bounded(self, path: Path) -> None:
        cover = read_epub_cover_bytes(path)
        hint = read_epub_identity_hint(path)
        identity = read_epub_book_identity(path)
        local_cover = read_local_cover_bytes(path)

        self.assertTrue(cover is None or isinstance(cover, bytes))
        self.assertTrue(hint is None or isinstance(hint, str))
        self.assertTrue(identity is None or isinstance(identity.title, str))
        self.assertTrue(local_cover is None or isinstance(local_cover, bytes))

    def test_random_and_truncated_epubs_degrade_without_escaping_readers(self) -> None:
        random_source = random.Random(0xE9B0F00D)
        valid_epub = self._valid_epub_bytes()
        truncation_points = {0, 1, len(valid_epub) - 1}
        truncation_points.update(random_source.randrange(0, len(valid_epub)) for _ in range(48))

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "damaged.epub"
            for point in sorted(truncation_points):
                with self.subTest(kind="truncated", point=point):
                    path.write_bytes(valid_epub[:point])
                    self._assert_archive_readers_are_bounded(path)

            for sample in range(40):
                with self.subTest(kind="random", sample=sample):
                    payload = random_source.randbytes(random_source.randrange(0, 4096))
                    path.write_bytes(payload)
                    self._assert_archive_readers_are_bounded(path)

            valid_container = """<?xml version="1.0"?>
<container><rootfiles><rootfile full-path="content.opf"/></rootfiles></container>"""
            for sample in range(40):
                with self.subTest(kind="malformed-xml", sample=sample):
                    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                        if sample % 2:
                            archive.writestr("META-INF/container.xml", valid_container)
                            archive.writestr("content.opf", random_source.randbytes(random_source.randrange(0, 2048)))
                        else:
                            archive.writestr(
                                "META-INF/container.xml",
                                random_source.randbytes(random_source.randrange(0, 2048)),
                            )
                    self._assert_archive_readers_are_bounded(path)

    def test_zip_member_limit_is_enforced_before_returning_data(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "oversized.epub"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("payload.bin", b"x" * 4096)

            with zipfile.ZipFile(path) as archive:
                self.assertIsNone(read_zip_member(archive, "payload.bin", max_bytes=32))
                self.assertEqual(read_zip_member(archive, "payload.bin", max_bytes=4096), b"x" * 4096)


class _FaultService:
    def snapshot(self, log_cursor: int = 0, plans_revision: int = -1) -> dict:
        return {"log_cursor": log_cursor, "plans_revision": plans_revision}

    def edit_plan(self, index: int, series_name: str) -> dict:
        return {"index": index, "series_name": series_name}

    def edit_plans(
        self,
        index: int,
        series_name: str,
        *,
        scope: str,
        expected_plans_revision: int | None = None,
    ) -> dict:
        return {
            "index": index,
            "series_name": series_name,
            "scope": scope,
            "plans_revision": expected_plans_revision,
        }

    def load_candidates(
        self,
        index: int,
        *,
        expected_plans_revision: int | None = None,
    ) -> dict:
        return {"index": index, "plans_revision": expected_plans_revision, "candidates": []}

    def start_undo(self, report_id: str | None = None) -> dict:
        return {"report_id": report_id}

    def report_summary(self, report_id: str | None = None) -> dict:
        return {"report_id": report_id, "items": []}

    def report_history(self) -> dict:
        return {"reports": [], "total_count": 0}


class SidecarFaultInjectionTests(unittest.TestCase):
    def test_malformed_request_stream_remains_structured_and_recovers(self) -> None:
        random_source = random.Random(0x51DECA7)
        methods: list[object] = [
            None,
            "",
            "ping",
            "poll",
            "edit_plan",
            "edit_plans",
            "missing",
            42,
            ["ping"],
        ]
        values: list[object] = [
            None,
            True,
            False,
            -1,
            0,
            1,
            2**64,
            1.5,
            "text",
            "\ud800\u202e",
            [],
            {},
        ]
        lines: list[str] = []
        for index in range(128):
            if index % 7 == 0:
                lines.append(random_source.choice(["{", "[1,", '"unterminated', "not-json"]))
                continue
            request = {
                "id": random_source.choice(values),
                "method": random_source.choice(methods),
                "params": random_source.choice(values),
            }
            lines.append(json.dumps(request, ensure_ascii=True))
        lines.extend(
            [
                '{"id":9001,"method":"ping","params":{}}',
                '{"id":9002,"method":"shutdown","params":{}}',
            ]
        )

        input_stream = io.StringIO("\n".join(lines) + "\n")
        output_stream = io.StringIO()
        server = SidecarServer(
            _FaultService(),  # type: ignore[arg-type]
            input_stream=input_stream,
            output_stream=output_stream,
        )

        self.assertEqual(server.serve_forever(), 0)
        responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        self.assertEqual(len(responses), len(lines))
        for response in responses:
            self.assertIsInstance(response, dict)
            self.assertIsInstance(response.get("ok"), bool)
            if not response["ok"]:
                self.assertIsInstance(response.get("error"), dict)
                self.assertTrue(response["error"].get("type"))
                self.assertTrue(response["error"].get("message"))
        self.assertEqual(responses[-2]["id"], 9001)
        self.assertTrue(responses[-2]["ok"])
        self.assertEqual(responses[-1], {"id": 9002, "ok": True, "result": {"accepted": True}})


class FileTransactionFaultInjectionTests(unittest.TestCase):
    @staticmethod
    def _create_batch(root: Path, count: int) -> tuple[list[Path], list[ClassificationPlan]]:
        sources = []
        for volume in range(1, count + 1):
            source = root / f"Fault.Matrix.Vol.{volume:02d}.txt"
            source.write_text(f"volume {volume}", encoding="utf-8")
            sources.append(source)
        plans = build_classification_plan(root, use_network=False)
        if len(plans) != count or not all(plan.will_move for plan in plans):
            raise AssertionError("测试批次未生成完整可移动计划。")
        return sources, plans

    def test_every_pre_move_failure_position_can_be_recovered_and_undone(self) -> None:
        real_move = shutil.move
        for failure_position in range(1, 5):
            with self.subTest(failure_position=failure_position), TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                sources, plans = self._create_batch(root, 4)
                report_path = root / "classification_report.json"
                move_count = 0

                def injected_move(
                    source: str,
                    target: str,
                    expected_failure_position: int = failure_position,
                ) -> str:
                    nonlocal move_count
                    move_count += 1
                    if move_count == expected_failure_position:
                        raise PermissionError("injected locked file")
                    return real_move(source, target)

                with (
                    patch(
                        "lightnovel_selector.classification_execution.shutil.move",
                        side_effect=injected_move,
                    ),
                    self.assertRaises(PermissionError),
                ):
                    execute_classification_plan(plans, report_path=report_path)

                report = load_classification_report(report_path)
                moved_before_failure = failure_position - 1
                self.assertEqual(report["summary"]["moved"], moved_before_failure)
                self.assertEqual(undo_classification_report(report_path), (moved_before_failure, 0))
                self.assertTrue(all(source.is_file() for source in sources))
                self.assertFalse((root / "classification_report.recovery.jsonl").exists())

    def test_post_move_exception_is_recovered_from_durable_intent(self) -> None:
        real_move = shutil.move
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sources, plans = self._create_batch(root, 1)
            report_path = root / "classification_report.json"

            def move_then_fail(source: str, target: str) -> str:
                real_move(source, target)
                raise OSError("injected failure after move")

            with (
                patch(
                    "lightnovel_selector.classification_execution.shutil.move",
                    side_effect=move_then_fail,
                ),
                self.assertRaisesRegex(OSError, "after move"),
            ):
                execute_classification_plan(plans, report_path=report_path)

            report = load_classification_report(report_path)
            self.assertEqual(report["summary"]["moved"], 1)
            self.assertEqual(report["items"][0]["operation"], "moved")
            self.assertEqual(undo_classification_report(report_path), (1, 0))
            self.assertTrue(sources[0].is_file())

    def test_failed_partial_report_rewrite_keeps_recoverable_journal(self) -> None:
        from lightnovel_selector.classification_reporting import (
            write_classification_report as real_write_report,
        )

        real_move = shutil.move
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sources, plans = self._create_batch(root, 2)
            report_path = root / "classification_report.json"
            move_count = 0
            write_count = 0

            def fail_second_move(source: str, target: str) -> str:
                nonlocal move_count
                move_count += 1
                if move_count == 2:
                    raise PermissionError("injected locked file")
                return real_move(source, target)

            def fail_second_report_write(*args, **kwargs) -> None:
                nonlocal write_count
                write_count += 1
                if write_count == 2:
                    raise OSError("injected report lock")
                real_write_report(*args, **kwargs)

            with (
                patch(
                    "lightnovel_selector.classification_execution.shutil.move",
                    side_effect=fail_second_move,
                ),
                patch(
                    "lightnovel_selector.classification_execution.write_classification_report",
                    side_effect=fail_second_report_write,
                ),
                self.assertRaisesRegex(RuntimeError, "部分撤销报告无法更新"),
            ):
                execute_classification_plan(plans, report_path=report_path)

            self.assertTrue((root / "classification_report.recovery.jsonl").is_file())
            report = load_classification_report(report_path)
            self.assertEqual(report["summary"]["moved"], 1)
            self.assertEqual(undo_classification_report(report_path), (1, 0))
            self.assertTrue(all(source.is_file() for source in sources))


if __name__ == "__main__":
    unittest.main()
