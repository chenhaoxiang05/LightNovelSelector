from pathlib import Path
from tempfile import TemporaryDirectory
import json
import time
import threading
from unittest.mock import patch
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

import lightnovel_classifier
from lightnovel_classifier import (
    BookMetadata,
    AppSettings,
    COVER_MAX_BYTES,
    CustomRule,
    FILE_FINGERPRINT_CHUNK_SIZE,
    PersistentMetadataCache,
    bangumi_cover_url,
    bangumi_title_candidates,
    book_metadata_from_dict,
    book_metadata_to_dict,
    build_classification_plan,
    clean_summary,
    count_plan_statuses,
    execute_classification_plan,
    extract_book_lookup_query,
    extract_series_guess,
    find_duplicate_files,
    http_bytes,
    http_json,
    identity_query_for_path,
    item_matches_volume,
    normalize_for_match,
    parse_volume_number,
    plan_status_label,
    revise_classification_plan,
    read_local_cover_bytes,
    safe_folder_name,
    load_app_settings,
    save_app_settings,
    suggest_renamed_filename,
    try_save_app_settings,
    undo_classification_report,
)


MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02"
    b"\xfeA\xe2&\xb5\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FilenameParsingTests(unittest.TestCase):
    def test_chinese_volume_marker(self) -> None:
        file_name = "\u5200\u5251\u795e\u57df Sword Art Online \u7b2c01\u5377 \u827e\u6069\u845b\u6717\u7279.epub"
        self.assertEqual(
            extract_series_guess(file_name),
            "刀剑神域 Sword Art Online",
        )
        self.assertEqual(
            extract_book_lookup_query(file_name),
            "\u5200\u5251\u795e\u57df Sword Art Online \u7b2c01\u5377 \u827e\u6069\u845b\u6717\u7279",
        )

    def test_english_volume_marker(self) -> None:
        self.assertEqual(
            extract_series_guess("Sword.Art.Online.Vol.02.Aincrad.epub"),
            "Sword Art Online",
        )

    def test_leading_release_tag(self) -> None:
        self.assertEqual(
            extract_series_guess("【台版】为美好的世界献上祝福！ 第05卷.epub"),
            "为美好的世界献上祝福!",
        )

    def test_short_numeric_title(self) -> None:
        self.assertEqual(extract_series_guess("86 01.epub"), "86")

    def test_preserves_no_dot_title(self) -> None:
        self.assertEqual(extract_series_guess("No.6 第01卷.txt"), "No.6")

    def test_extracts_trailing_numeric_volume_for_details(self) -> None:
        file_name = "\u65e0\u804c\u8f6c\u751f \uff5e\u5230\u4e86\u5f02\u4e16\u754c\u5c31\u62ff\u51fa\u771f\u672c\u4e8b\uff5e 13.epub"
        self.assertEqual(
            extract_series_guess(file_name),
            "\u65e0\u804c\u8f6c\u751f ~\u5230\u4e86\u5f02\u4e16\u754c\u5c31\u62ff\u51fa\u771f\u672c\u4e8b",
        )
        self.assertEqual(
            extract_book_lookup_query(file_name),
            "\u65e0\u804c\u8f6c\u751f ~\u5230\u4e86\u5f02\u4e16\u754c\u5c31\u62ff\u51fa\u771f\u672c\u4e8b~ 13",
        )
        self.assertEqual(parse_volume_number(file_name), 13)

    def test_preserves_novel_as_title_word(self) -> None:
        self.assertEqual(
            extract_series_guess("The Novel's Extra Vol.01.epub"),
            "The Novel's Extra",
        )

    def test_safe_folder_name(self) -> None:
        self.assertEqual(safe_folder_name('A:B/C*D?'), "A_B_C_D_")

    def test_uses_content_hint_for_weak_file_name(self) -> None:
        self.assertEqual(
            identity_query_for_path(Path("1.epub"), "无职转生 ～到了异世界就拿出真本事～ 第13卷 第一章"),
            "无职转生 ～到了异世界就拿出真本事～ 第13卷 第一章",
        )

    def test_suggests_chinese_series_volume_filename(self) -> None:
        metadata = BookMetadata(
            title="無職転生 ~異世界行ったら本気だす~ (13)",
            source="Bangumi",
            confidence=0.96,
            query="無職転生 13",
        )
        self.assertEqual(
            suggest_renamed_filename(
                Path("1.epub"),
                series_name="无职转生 ～到了异世界就拿出真本事～",
                metadata=metadata,
                identity_query="無職転生 13",
            ),
            "无职转生 ~到了异世界就拿出真本事~ 第13卷.epub",
        )


class MovePlanTests(unittest.TestCase):
    def test_dry_plan_and_move_without_network(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "Sword.Art.Online.Vol.01.epub"
            second = root / "Sword.Art.Online.Vol.02.epub"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")

            plans = build_classification_plan(root, use_network=False)

            self.assertEqual(len(plans), 2)
            self.assertEqual({plan.series_name for plan in plans}, {"Sword Art Online"})

            moved, skipped = execute_classification_plan(plans)

            self.assertEqual((moved, skipped), (2, 0))
            self.assertTrue((root / "Sword Art Online" / first.name).exists())
            self.assertTrue((root / "Sword Art Online" / second.name).exists())

    def test_duplicate_file_is_marked_and_skipped(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A Sword.Art.Online.Vol.01.epub"
            duplicate = root / "B SAO copy.epub"
            first.write_text("same", encoding="utf-8")
            duplicate.write_text("same", encoding="utf-8")

            plans = build_classification_plan(root, use_network=False)

            duplicate_plans = [plan for plan in plans if plan.status == "duplicate"]
            self.assertEqual(len(duplicate_plans), 1)
            self.assertEqual(duplicate_plans[0].duplicate_of, first)
            self.assertFalse(duplicate_plans[0].will_move)

            moved, skipped = execute_classification_plan(plans, report_path=root / "report.json")

            self.assertEqual((moved, skipped), (1, 1))
            report = json.loads((root / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["duplicates"], 1)
            self.assertEqual(report["summary"]["moved"], 1)

    def test_find_duplicate_files_uses_content_not_name(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A.txt"
            same = root / "B.txt"
            different = root / "C.txt"
            first.write_text("book", encoding="utf-8")
            same.write_text("book", encoding="utf-8")
            different.write_text("other", encoding="utf-8")

            duplicates = find_duplicate_files([first, same, different])

            self.assertEqual(duplicates, {same: first})

    def test_duplicate_detection_checks_full_file_content(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A.txt"
            second = root / "B.txt"
            shared_head = b"h" * FILE_FINGERPRINT_CHUNK_SIZE
            shared_tail = b"t" * FILE_FINGERPRINT_CHUNK_SIZE
            first.write_bytes(shared_head + b"middle-one" + shared_tail)
            second.write_bytes(shared_head + b"middle-two" + shared_tail)

            duplicates = find_duplicate_files([first, second])

            self.assertEqual(duplicates, {})

    def test_duplicate_detection_skips_full_hash_for_unique_signatures(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A.txt"
            second = root / "B.txt"
            first.write_text("short", encoding="utf-8")
            second.write_text("longer unique content", encoding="utf-8")

            with patch.object(lightnovel_classifier, "file_fingerprint", wraps=lightnovel_classifier.file_fingerprint) as full_hash:
                duplicates = find_duplicate_files([first, second])

            self.assertEqual(duplicates, {})
            self.assertEqual(full_hash.call_count, 0)

    def test_http_bytes_rejects_oversized_response(self) -> None:
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"12345"
        with patch("lightnovel_selector.files.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "超过允许大小"):
                http_bytes("https://example.test/cover.jpg", max_bytes=4)

    def test_http_json_rejects_non_object_root(self) -> None:
        response = unittest.mock.MagicMock()
        opened_response = response.__enter__.return_value
        opened_response.headers.get_content_charset.return_value = "utf-8"
        opened_response.read.return_value = b"[]"

        with patch("lightnovel_selector.files.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "JSON 根节点不是对象"):
                http_json("https://example.test/search")

    def test_bangumi_search_rejects_invalid_data_shape(self) -> None:
        with patch("lightnovel_selector.metadata.http_json", return_value={"data": {}}):
            with self.assertRaisesRegex(RuntimeError, "data 不是数组"):
                lightnovel_classifier.bangumi_search_items("Sword Art Online", timeout=1.0)

    def test_recursive_scan_keeps_already_classified_file_in_place(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            series_dir = root / "Sword Art Online"
            series_dir.mkdir()
            book = series_dir / "Sword.Art.Online.Vol.01.txt"
            book.write_text("volume one", encoding="utf-8")

            plans = build_classification_plan(root, recursive=True, use_network=False)

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].status, "unchanged")
            self.assertEqual(plans[0].target_path, book)
            self.assertFalse(plans[0].will_move)

            moved, skipped = execute_classification_plan(plans)

            self.assertEqual((moved, skipped), (0, 1))
            self.assertTrue(book.exists())
            self.assertFalse((series_dir / "Sword.Art.Online.Vol.01 (1).txt").exists())

    def test_execute_and_undo_report_structured_progress(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "Sword.Art.Online.Vol.01.txt"
            second = root / "Sword.Art.Online.Vol.02.txt"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            report_path = root / "classification_report.json"
            execute_progress = []
            undo_progress = []
            plans = build_classification_plan(root, use_network=False)

            moved, skipped = execute_classification_plan(
                plans,
                report_path=report_path,
                progress_count=lambda done, total: execute_progress.append((done, total)),
            )
            restored, undo_skipped = undo_classification_report(
                report_path,
                progress_count=lambda done, total: undo_progress.append((done, total)),
            )

            self.assertEqual((moved, skipped), (2, 0))
            self.assertEqual(execute_progress, [(1, 2), (2, 2)])
            self.assertEqual((restored, undo_skipped), (2, 0))
            self.assertEqual(undo_progress, [(1, 2), (2, 2)])

    def test_scan_reports_structured_progress(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Sword.Art.Online.Vol.01.txt").write_text("one", encoding="utf-8")
            (root / "Sword.Art.Online.Vol.02.txt").write_text("two", encoding="utf-8")
            progress = []

            plans = build_classification_plan(
                root,
                use_network=False,
                progress_count=lambda done, total: progress.append((done, total)),
            )

            self.assertEqual(len(plans), 2)
            self.assertEqual(progress, [(1, 2), (2, 2)])

    def test_manual_revision_clears_duplicate_status(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A.txt"
            duplicate = root / "B.txt"
            first.write_text("same", encoding="utf-8")
            duplicate.write_text("same", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)
            duplicate_index = next(index for index, plan in enumerate(plans) if plan.status == "duplicate")

            revised = revise_classification_plan(plans, duplicate_index, "手动系列")

            self.assertEqual(revised.status, "ready")
            self.assertEqual(revised.series_name, "手动系列")
            self.assertEqual(revised.resolver_source, "手动修正")
            self.assertIsNone(revised.duplicate_of)

    def test_custom_rule_overrides_local_guess(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "mystery-file-01.txt"
            book.write_text("content", encoding="utf-8")

            plans = build_classification_plan(
                root,
                use_network=False,
                custom_rules=[CustomRule(pattern="*mystery*", series="手动系列")],
            )

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].series_name, "手动系列")
            self.assertEqual(plans[0].resolver_source, "自定义规则")

    def test_app_settings_roundtrip(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            settings = AppSettings(
                use_network=False,
                recursive=True,
                auto_rename=True,
                custom_rules=(CustomRule(pattern="*SAO*", series="Sword Art Online"),),
                last_folder=str(Path(temp_dir)),
            )

            save_app_settings(settings, path)
            loaded = load_app_settings(path)

            self.assertEqual(loaded, settings)

    def test_try_save_app_settings_returns_os_error(self) -> None:
        with TemporaryDirectory() as temp_dir:
            parent_file = Path(temp_dir) / "not-a-directory"
            parent_file.write_text("blocks directory creation", encoding="utf-8")
            error = try_save_app_settings(AppSettings(), parent_file / "settings.json")

            self.assertIsInstance(error, OSError)

    def test_undo_classification_report_restores_moved_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Sword.Art.Online.Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            moved, skipped = execute_classification_plan(plans, report_path=report_path)

            self.assertEqual((moved, skipped), (1, 0))
            self.assertFalse(book.exists())

            restored, undo_skipped = undo_classification_report(report_path)

            self.assertEqual((restored, undo_skipped), (1, 0))
            self.assertTrue(book.exists())
            self.assertEqual(book.read_text(encoding="utf-8"), "one")

    def test_failed_move_writes_partial_report_for_undo(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A Sword.Art.Online.Vol.01.txt"
            missing = root / "B Sword.Art.Online.Vol.02.txt"
            first.write_text("one", encoding="utf-8")
            missing.write_text("two", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)
            missing.unlink()

            with self.assertRaises(FileNotFoundError):
                execute_classification_plan(plans, report_path=report_path)

            self.assertTrue(report_path.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["moved"], 1)
            self.assertEqual(report["items"][0]["operation"], "moved")

            restored, skipped = undo_classification_report(report_path)

            self.assertEqual((restored, skipped), (1, 0))
            self.assertTrue(first.exists())

    def test_unwritable_report_fails_before_moving_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Sword.Art.Online.Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("blocked", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)

            with self.assertRaises(OSError):
                execute_classification_plan(plans, report_path=blocked_parent / "report.json")

            self.assertTrue(book.exists())
            self.assertFalse((root / "Sword Art Online" / book.name).exists())

    def test_undo_rejects_non_object_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "classification_report.json"
            report_path.write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "根节点必须是对象"):
                undo_classification_report(report_path)

    def test_plan_status_label(self) -> None:
        self.assertEqual(plan_status_label("ready"), "可执行")
        self.assertEqual(plan_status_label("duplicate"), "重复")
        self.assertEqual(plan_status_label("error"), "错误")
        self.assertEqual(plan_status_label("moved"), "已移动")
        self.assertEqual(plan_status_label("unchanged"), "无需移动")
        self.assertEqual(plan_status_label("custom"), "custom")

    def test_count_plan_statuses(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "Sword.Art.Online.Vol.01.txt"
            duplicate = root / "Sword.Art.Online.Vol.02.txt"
            first.write_text("same", encoding="utf-8")
            duplicate.write_text("same", encoding="utf-8")

            plans = build_classification_plan(root, use_network=False)

            self.assertEqual(
                count_plan_statuses(plans),
                {"total": 2, "ready": 1, "duplicate": 1, "error": 0},
            )


class LocalCoverTests(unittest.TestCase):
    def test_reads_epub_cover_image(self) -> None:
        with TemporaryDirectory() as temp_dir:
            epub_path = Path(temp_dir) / "book.epub"
            with ZipFile(epub_path, "w", ZIP_DEFLATED) as archive:
                archive.writestr(
                    "META-INF/container.xml",
                    """<?xml version="1.0"?>
                    <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
                      <rootfiles>
                        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
                      </rootfiles>
                    </container>""",
                )
                archive.writestr(
                    "OEBPS/content.opf",
                    """<?xml version="1.0"?>
                    <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
                      <manifest>
                        <item id="cover" href="images/cover.png" media-type="image/png" properties="cover-image"/>
                      </manifest>
                    </package>""",
                )
                archive.writestr("OEBPS/images/cover.png", MINIMAL_PNG)

            self.assertEqual(read_local_cover_bytes(epub_path), MINIMAL_PNG)

    def test_skips_oversized_archive_cover(self) -> None:
        with TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "book.cbz"
            with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
                archive.writestr("cover.jpg", b"x" * (COVER_MAX_BYTES + 1))

            self.assertIsNone(read_local_cover_bytes(archive_path))


class BangumiMetadataTests(unittest.TestCase):
    def test_extracts_titles_and_cover_from_search_item(self) -> None:
        item = {
            "name": "ソードアート・オンライン",
            "name_cn": "刀剑神域",
            "images": {"common": "https://example.test/common.jpg", "large": "https://example.test/large.jpg"},
            "infobox": [
                {"key": "别名", "value": [{"v": "Sword Art Online"}, {"v": "SAO"}]},
            ],
        }

        self.assertEqual(
            bangumi_title_candidates(item),
            ["刀剑神域", "ソードアート・オンライン", "Sword Art Online", "SAO"],
        )
        self.assertEqual(bangumi_cover_url(item), "https://example.test/common.jpg")

    def test_clean_summary_removes_empty_lines(self) -> None:
        self.assertEqual(clean_summary(" A\r\n\r\n B "), "A\nB")

    def test_detects_matching_volume_in_bangumi_item(self) -> None:
        item = {
            "name": "\u7121\u8077\u8ee2\u751f ~\u7570\u4e16\u754c\u884c\u3063\u305f\u3089\u672c\u6c17\u3060\u3059~ (13)",
            "name_cn": "",
            "infobox": [],
        }
        self.assertTrue(item_matches_volume(item, 13))
        self.assertFalse(item_matches_volume(item, 12))

    def test_persistent_metadata_cache_roundtrip(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = PersistentMetadataCache(Path(temp_dir) / "cache.json")
            key = "book:" + normalize_for_match("Mushoku Tensei 13")
            metadata = BookMetadata(
                title="Mushoku Tensei (13)",
                source="Bangumi",
                confidence=0.96,
                query="Mushoku Tensei 13",
                summary="volume summary",
                cover_url="https://example.test/cover.jpg",
                url="https://bgm.tv/subject/207694",
            )

            cache.set(key, book_metadata_to_dict(metadata))
            loaded = book_metadata_from_dict(PersistentMetadataCache(Path(temp_dir) / "cache.json").get(key) or {})

            self.assertEqual(loaded, metadata)

    def test_persistent_metadata_cache_ignores_bad_timestamp(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "entries": {
                            "book:bad": {
                                "cached_at": "not-a-number",
                                "payload": {"title": "Broken"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            cache = PersistentMetadataCache(cache_path)

            self.assertIsNone(cache.get("book:bad"))
            self.assertNotIn("book:bad", PersistentMetadataCache(cache_path).data["entries"])

    def test_persistent_metadata_cache_ignores_non_object_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            cache_path.write_text("[]", encoding="utf-8")

            cache = PersistentMetadataCache(cache_path)

            self.assertEqual(cache.data, {"version": 1, "entries": {}})


class ApplicationServiceTests(unittest.TestCase):
    @staticmethod
    def wait_for_operation(service, timeout: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = service.snapshot()
            if snapshot["operation"]["state"] != "running":
                return snapshot
            time.sleep(0.02)
        raise AssertionError("后台操作未在测试时限内完成")

    def test_scan_edit_apply_and_undo_workflow(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Sword.Art.Online.Vol.01.txt"
            book.write_text("volume one", encoding="utf-8")
            with (
                patch("lightnovel_selector.application.load_app_settings", return_value=AppSettings()),
                patch("lightnovel_selector.application.try_save_app_settings", return_value=None),
            ):
                service = ApplicationService()
                service.set_folder(str(root))
                self.assertEqual(service.snapshot()["operation"]["message"], "等待扫描预览")
                service.save_settings(
                    {
                        "use_network": False,
                        "recursive": False,
                        "auto_rename": False,
                        "custom_rules": [],
                    }
                )

                service.start_scan()
                scanned = self.wait_for_operation(service)
                self.assertEqual(scanned["operation"]["state"], "success")
                self.assertEqual(scanned["counts"]["ready"], 1)
                self.assertEqual(len(scanned["plans"]), 1)

                service.edit_plan(0, "SAO 手动分类")
                edited = service.snapshot(plans_revision=-1)
                self.assertEqual(edited["plans"][0]["series_name"], "SAO 手动分类")

                service.start_apply()
                applied = self.wait_for_operation(service)
                moved_path = root / "SAO 手动分类" / book.name
                self.assertEqual(applied["operation"]["state"], "success")
                self.assertTrue(moved_path.exists())
                self.assertTrue((root / "classification_report.json").exists())

                service.start_undo()
                undone = self.wait_for_operation(service)
                self.assertEqual(undone["operation"]["state"], "success")
                self.assertTrue(book.exists())

    def test_restored_folder_starts_ready_for_scan(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            settings = AppSettings(last_folder=temp_dir)
            with patch("lightnovel_selector.application.load_app_settings", return_value=settings):
                service = ApplicationService()

            snapshot = service.snapshot()
            self.assertEqual(snapshot["folder"], str(Path(temp_dir).resolve()))
            self.assertEqual(snapshot["operation"]["message"], "等待扫描预览")
            self.assertIn("已恢复上次目录", snapshot["logs"][0]["message"])

    def test_snapshot_only_resends_plans_after_revision_change(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with patch("lightnovel_selector.application.load_app_settings", return_value=AppSettings()):
            service = ApplicationService()
        first = service.snapshot(plans_revision=-1)
        second = service.snapshot(plans_revision=first["plans_revision"])

        self.assertEqual(first["plans"], [])
        self.assertIsNone(second["plans"])

    def test_rejected_concurrent_scan_does_not_change_revision(self) -> None:
        from lightnovel_selector.application import ApplicationService

        started = threading.Event()
        release = threading.Event()

        def slow_scan(*_args, **_kwargs):
            started.set()
            release.wait(timeout=2)
            return []

        with TemporaryDirectory() as temp_dir:
            with (
                patch("lightnovel_selector.application.load_app_settings", return_value=AppSettings()),
                patch("lightnovel_selector.application.try_save_app_settings", return_value=None),
                patch("lightnovel_selector.application.build_classification_plan", side_effect=slow_scan),
            ):
                service = ApplicationService()
                service.set_folder(temp_dir)
                service.start_scan()
                self.assertTrue(started.wait(timeout=1))
                revision = service.snapshot()["plans_revision"]

                with self.assertRaisesRegex(RuntimeError, "尚未完成"):
                    service.start_scan()

                self.assertEqual(service.snapshot()["plans_revision"], revision)
                release.set()
                self.wait_for_operation(service)


if __name__ == "__main__":
    unittest.main()
