import argparse
import json
import os
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import lightnovel_classifier
from lightnovel_classifier import (
    CLASSIFICATION_CANDIDATE_MAX_COUNT,
    COVER_MAX_BYTES,
    FILE_FINGERPRINT_CHUNK_SIZE,
    IDENTITY_MAX_AUTHORS,
    IDENTITY_MAX_TAGS,
    IDENTITY_VALUE_MAX_CHARS,
    METADATA_TEXT_MAX_CHARS,
    SCAN_MAX_FILES,
    AppSettings,
    BookIdentity,
    BookMetadata,
    ClassificationCandidate,
    CustomRule,
    FileSnapshot,
    PersistentMetadataCache,
    PersistentScanCache,
    ResolveResult,
    archive_classification_report,
    bangumi_cover_url,
    bangumi_identity_from_item,
    bangumi_title_candidates,
    book_identity_from_dict,
    book_identity_to_dict,
    book_metadata_from_dict,
    book_metadata_to_dict,
    build_classification_plan,
    capture_file_snapshot,
    classification_plan_group_indices,
    classification_plan_to_report_item,
    classification_report_history_directory,
    clean_summary,
    count_plan_statuses,
    execute_classification_plan,
    extract_book_lookup_query,
    extract_series_guess,
    find_duplicate_files,
    find_novel_files,
    http_bytes,
    http_json,
    identity_query_for_path,
    infer_language,
    item_matches_volume,
    list_classification_reports,
    load_app_settings,
    load_classification_report,
    mark_classification_report_undone,
    merge_classification_candidates,
    normalize_for_match,
    parse_volume_number,
    plan_status_label,
    read_book_identity,
    read_epub_book_identity,
    read_local_cover_bytes,
    resolve_classification_report,
    revise_classification_plan,
    revise_classification_plans,
    run_cli,
    safe_folder_name,
    save_app_settings,
    scan_cache_path,
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

    def test_infers_explicit_file_language_without_guessing_from_short_titles(self) -> None:
        self.assertEqual(infer_language("【简中】青春物语 第03卷.epub"), "zh-Hans")
        self.assertEqual(infer_language("Mushoku Tensei [zh-TW] 13.epub"), "zh-Hant")
        self.assertEqual(infer_language("Mushoku Tensei [eng] 13.epub"), "en")
        self.assertIsNone(infer_language("86 01.epub"))

    def test_infers_language_from_long_content_samples(self) -> None:
        self.assertEqual(infer_language(None, "これは日本語の文章です。ライトノベルの本文を確認しています。"), "ja")
        self.assertEqual(
            infer_language(None, "这是一个用于识别语言的简体中文段落，包含足够多的汉字来避免短标题误判。"), "zh-Hans"
        )
        self.assertEqual(infer_language(None, "天地玄黄宇宙洪荒日月星辰山川河海草木花鸟春夏秋冬"), "zh")

    def test_preserves_volume_zero(self) -> None:
        self.assertEqual(parse_volume_number("Demo Vol.00"), 0)
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Demo Vol.00.txt"
            path.write_text("prologue", encoding="utf-8")

            self.assertEqual(read_book_identity(path).volume_number, 0)

    def test_safe_folder_name(self) -> None:
        self.assertEqual(safe_folder_name("A:B/C*D?"), "A_B_C_D_")
        self.assertEqual(safe_folder_name("CON"), "_CON")
        self.assertEqual(safe_folder_name("LPT1.txt"), "_LPT1.txt")

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

    def test_suggested_filename_preserves_volume_zero(self) -> None:
        self.assertEqual(
            suggest_renamed_filename(
                Path("Demo Vol.01.epub"),
                series_name="Demo",
                metadata=None,
                identity_query="Demo Vol.00",
            ),
            "Demo 第00卷.epub",
        )


class CandidateTests(unittest.TestCase):
    def test_candidate_merge_deduplicates_series_and_enforces_limit(self) -> None:
        candidates = tuple(
            ClassificationCandidate(
                identity=BookIdentity(title=f"Book {index}", series_name=f"Series {index}"),
                source=f"Source {index}",
                confidence=0.5,
            )
            for index in range(CLASSIFICATION_CANDIDATE_MAX_COUNT + 2)
        )
        preferred_duplicate = ClassificationCandidate(
            identity=BookIdentity(title="Preferred", series_name="Series 0"),
            source="Preferred Source",
            confidence=0.95,
        )

        merged = merge_classification_candidates(
            candidates,
            (preferred_duplicate,),
        )

        self.assertEqual(len(merged), CLASSIFICATION_CANDIDATE_MAX_COUNT)
        self.assertEqual(merged[0], preferred_duplicate)

    def test_resolver_collects_available_providers_and_keeps_partial_error(self) -> None:
        resolver = lightnovel_classifier.SeriesResolver(use_network=True)
        bangumi = ResolveResult(
            identity=BookIdentity(title="Demo", series_name="Demo"),
            source="Bangumi",
            confidence=0.9,
            local_guess="Demo",
        )
        jikan = ResolveResult(
            identity=BookIdentity(title="Demo Novel", series_name="Demo Novel"),
            source="Jikan",
            confidence=0.82,
            local_guess="Demo",
        )
        with (
            patch.object(resolver, "_search_bangumi", return_value=bangumi),
            patch.object(resolver, "_search_anilist", side_effect=OSError("offline")),
            patch.object(resolver, "_search_jikan", return_value=jikan),
        ):
            results = resolver.resolve_candidates("Demo")

        self.assertEqual(results, (bangumi, jikan))
        self.assertIn("offline", resolver.last_network_error or "")


class MovePlanTests(unittest.TestCase):
    def test_plan_payload_and_report_share_the_same_identity(self) -> None:
        from lightnovel_selector.application import plan_to_dict

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "【简中】青春物语 第03卷.txt"
            book.write_text(
                "这是一个用于语言识别的简体中文正文样本，包含足够多的汉字来建立可靠判断。",
                encoding="utf-8",
            )

            plan = build_classification_plan(root, use_network=False)[0]
            payload = plan_to_dict(plan, 0)
            report_item = classification_plan_to_report_item(plan)

            self.assertEqual(plan.identity.series_name, "青春物语")
            self.assertEqual(plan.identity.title, "青春物语 第03卷")
            self.assertEqual(plan.identity.volume_number, 3)
            self.assertEqual(plan.identity.language, "zh-Hans")
            self.assertEqual(payload["identity"], report_item["identity"])
            self.assertEqual(payload["book_title"], plan.identity.title)
            self.assertEqual(payload["language_label"], "简体中文")

    def test_file_discovery_can_be_cancelled_before_duplicate_hashing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "ignored.bin").write_bytes(b"not a novel")

            def checkpoint() -> None:
                raise RuntimeError("cancelled during discovery")

            with self.assertRaisesRegex(RuntimeError, "cancelled during discovery"):
                build_classification_plan(
                    root,
                    use_network=False,
                    checkpoint=checkpoint,
                )

    def test_file_discovery_limits_all_directory_entries(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(3):
                (root / f"ignored-{index}.bin").write_bytes(b"not a novel")

            with (
                patch("lightnovel_selector.classification.SCAN_MAX_ENTRIES", 2),
                self.assertRaisesRegex(ValueError, "最多检查 2 个目录项"),
            ):
                find_novel_files(root)

    def test_recursive_file_discovery_is_deterministic_for_matching_names(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A" / "same.txt"
            second = root / "B" / "same.txt"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")

            self.assertEqual(
                find_novel_files(root, recursive=True),
                [first, second],
            )

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

    def test_weak_filename_content_hint_never_becomes_network_query(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "1.txt"
            book.write_text("刀剑神域 第01卷 第一章", encoding="utf-8")
            with (
                patch("lightnovel_selector.metadata.SeriesResolver._resolve_with_network") as series_network,
                patch(
                    "lightnovel_selector.metadata.SeriesResolver.resolve_book_metadata_for_query"
                ) as metadata_network,
            ):
                plans = build_classification_plan(
                    root,
                    use_network=True,
                    auto_rename=True,
                )

            self.assertEqual(plans[0].series_name, "刀剑神域")
            self.assertEqual(plans[0].resolver_source, "本地内容提示")
            self.assertIsNone(plans[0].network_query)
            series_network.assert_not_called()
            metadata_network.assert_not_called()

    def test_weak_filename_without_content_hint_uses_local_rule_label(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "1.pdf"
            book.write_bytes(b"%PDF-1.4")

            plans = build_classification_plan(root, use_network=True)

            self.assertEqual(plans[0].series_name, "1")
            self.assertEqual(plans[0].resolver_source, "本地规则")
            self.assertIsNone(plans[0].network_query)

    def test_series_lookup_preserves_local_book_title_and_volume(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Demo 第03卷.txt"
            book.write_text("content", encoding="utf-8")
            remote_result = ResolveResult(
                identity=BookIdentity(
                    title="Demo",
                    series_name="Demo",
                    authors=("Remote Author",),
                    volume_number=1,
                ),
                source="Test Provider",
                confidence=0.95,
                local_guess="Demo",
            )

            with patch(
                "lightnovel_selector.classification.SeriesResolver.resolve",
                return_value=remote_result,
            ):
                plans = build_classification_plan(root, use_network=True)

            self.assertEqual(plans[0].identity.title, "Demo 第03卷")
            self.assertEqual(plans[0].identity.authors, ("Remote Author",))
            self.assertEqual(plans[0].identity.volume_number, 3)

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

    def test_duplicate_detection_runs_cancellation_checkpoint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("same", encoding="utf-8")
            second.write_text("same", encoding="utf-8")
            checkpoints = 0

            def checkpoint() -> None:
                nonlocal checkpoints
                checkpoints += 1
                if checkpoints == 2:
                    raise RuntimeError("cancelled")

            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                find_duplicate_files(
                    [first, second],
                    checkpoint=checkpoint,
                )

    def test_full_fingerprint_checks_cancellation_between_chunks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            book = Path(temp_dir) / "book.txt"
            book.write_bytes(b"0123456789")
            checkpoints = 0

            def checkpoint() -> None:
                nonlocal checkpoints
                checkpoints += 1
                if checkpoints == 2:
                    raise RuntimeError("cancelled")

            with (
                patch("lightnovel_selector.files.FILE_FINGERPRINT_CHUNK_SIZE", 4),
                self.assertRaisesRegex(RuntimeError, "cancelled"),
            ):
                lightnovel_classifier.file_fingerprint(
                    book,
                    checkpoint=checkpoint,
                )

    def test_scan_rejects_excessive_supported_file_count(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(3):
                (root / f"book-{index}.txt").write_text("content", encoding="utf-8")

            with (
                patch("lightnovel_selector.classification.SCAN_MAX_FILES", 2),
                self.assertRaisesRegex(ValueError, "单次扫描最多支持 2 个"),
            ):
                build_classification_plan(root, use_network=False)

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

    def test_plan_revalidates_stale_duplicate_candidate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A Sword.Art.Online.Vol.01.txt"
            second = root / "B Sword.Art.Online.Vol.02.txt"
            first.write_text("first content", encoding="utf-8")
            second.write_text("different content", encoding="utf-8")

            with patch(
                "lightnovel_selector.classification.find_duplicate_files",
                return_value={second: first},
            ):
                plans = build_classification_plan(root, use_network=False)

            self.assertFalse(any(plan.status == "duplicate" for plan in plans))
            self.assertTrue(all(plan.will_move for plan in plans))

    def test_duplicate_detection_skips_full_hash_for_unique_signatures(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A.txt"
            second = root / "B.txt"
            first.write_text("short", encoding="utf-8")
            second.write_text("longer unique content", encoding="utf-8")

            with patch.object(
                lightnovel_classifier, "file_fingerprint", wraps=lightnovel_classifier.file_fingerprint
            ) as full_hash:
                duplicates = find_duplicate_files([first, second])

            self.assertEqual(duplicates, {})
            self.assertEqual(full_hash.call_count, 0)

    def test_incremental_scan_cache_reuses_complete_hashes_and_local_analysis(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "library"
            root.mkdir()
            cache_path = base / "scan-cache.json"
            chunk = b"h" * 64
            payload = chunk + b"same-middle" + (b"t" * 64)
            first = root / "A Shared.Series.Vol.01.txt"
            second = root / "B Shared.Series.Vol.02.txt"
            first.write_bytes(payload)
            second.write_bytes(payload)

            with (
                patch("lightnovel_selector.files.FILE_FINGERPRINT_CHUNK_SIZE", 64),
                PersistentScanCache(cache_path) as first_cache,
            ):
                first_plans = build_classification_plan(
                    root,
                    use_network=False,
                    scan_cache=first_cache,
                )

            with (
                patch("lightnovel_selector.files.FILE_FINGERPRINT_CHUNK_SIZE", 64),
                PersistentScanCache(cache_path) as second_cache,
            ):
                second_plans = build_classification_plan(
                    root,
                    use_network=False,
                    scan_cache=second_cache,
                )

            self.assertEqual([plan.status for plan in first_plans], ["ready", "duplicate"])
            self.assertEqual([plan.status for plan in second_plans], ["ready", "duplicate"])
            self.assertEqual(second_cache.stats.reused_files, 2)
            self.assertEqual(second_cache.stats.quick_signature_hits, 2)
            self.assertEqual(second_cache.stats.fingerprint_hits, 2)
            self.assertEqual(second_cache.stats.local_analysis_hits, 1)
            self.assertIsNone(second_cache.stats.write_warning)

    def test_scan_cache_invalidates_middle_change_even_when_mtime_is_restored(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "library"
            root.mkdir()
            cache_path = base / "scan-cache.json"
            head = b"h" * 64
            tail = b"t" * 64
            first = root / "A Shared.Series.Vol.01.txt"
            second = root / "B Shared.Series.Vol.02.txt"
            first.write_bytes(head + b"111111" + tail)
            second.write_bytes(head + b"111111" + tail)

            with (
                patch("lightnovel_selector.files.FILE_FINGERPRINT_CHUNK_SIZE", 64),
                PersistentScanCache(cache_path) as initial_cache,
            ):
                initial_plans = build_classification_plan(
                    root,
                    use_network=False,
                    scan_cache=initial_cache,
                )
            self.assertEqual([plan.status for plan in initial_plans], ["ready", "duplicate"])

            original_stat = second.stat()
            time.sleep(0.01)
            second.write_bytes(head + b"222222" + tail)
            os.utime(
                second,
                ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
            )

            with (
                patch("lightnovel_selector.files.FILE_FINGERPRINT_CHUNK_SIZE", 64),
                PersistentScanCache(cache_path) as changed_cache,
            ):
                changed_plans = build_classification_plan(
                    root,
                    use_network=False,
                    scan_cache=changed_cache,
                )

            self.assertEqual([plan.status for plan in changed_plans], ["ready", "ready"])
            self.assertEqual(changed_cache.stats.invalidated_files, 1)
            self.assertEqual(changed_cache.stats.updated_files, 1)

    def test_scan_cache_corruption_and_write_failure_do_not_block_scan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "library"
            root.mkdir()
            book = root / "Reliable.Series.Vol.01.txt"
            book.write_text("Reliable Series 第一卷", encoding="utf-8")
            cache_path = base / "scan-cache.json"
            snapshot = capture_file_snapshot(book)
            cache_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "entries": {
                            f"file:{snapshot.device:x}:{snapshot.inode:x}": {
                                "snapshot": snapshot.to_dict(),
                                "last_used_at": time.time(),
                                "fingerprint": f"{snapshot.size}:not-a-sha256",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            cache = PersistentScanCache(cache_path)
            self.assertEqual(cache.stats.entries, 0)
            with (
                patch(
                    "lightnovel_selector.scan_cache.write_json_atomic",
                    side_effect=OSError("cache is locked"),
                ),
                cache,
            ):
                plans = build_classification_plan(
                    root,
                    use_network=False,
                    scan_cache=cache,
                )

            self.assertEqual(len(plans), 1)
            self.assertIn("cache is locked", cache.stats.write_warning or "")

    def test_scan_cache_file_is_bounded_and_uses_local_app_data(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            cache_path = base / "scan-cache.json"
            with patch("lightnovel_selector.scan_cache.SCAN_CACHE_MAX_BYTES", 1100):
                cache = PersistentScanCache(cache_path)
                for index in range(20):
                    book = base / f"book-{index}.txt"
                    book.write_text(f"content-{index}", encoding="utf-8")
                    snapshot = capture_file_snapshot(book)
                    cache.remember_quick_signature(
                        book,
                        snapshot,
                        f"{snapshot.size}:{index:064x}",
                    )
                cache.flush()

            self.assertLessEqual(cache_path.stat().st_size, 1100)
            self.assertLess(cache.stats.entries, 20)
            with patch.dict(os.environ, {"LOCALAPPDATA": str(base)}):
                self.assertEqual(
                    scan_cache_path(),
                    base / "LightNovelSelector" / "scan_cache.json",
                )

    def test_scan_cache_disables_reuse_without_reliable_change_token(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            book = base / "book.txt"
            book.write_text("content", encoding="utf-8")
            snapshot = FileSnapshot(
                size=book.stat().st_size,
                mtime_ns=book.stat().st_mtime_ns,
                change_token=None,
                device=book.stat().st_dev,
                inode=book.stat().st_ino,
            )
            cache = PersistentScanCache(base / "scan-cache.json")

            with (
                patch(
                    "lightnovel_selector.files.capture_file_snapshot",
                    return_value=snapshot,
                ),
                patch(
                    "lightnovel_selector.classification.capture_file_snapshot",
                    return_value=snapshot,
                ),
                cache,
            ):
                plans = build_classification_plan(
                    base,
                    use_network=False,
                    scan_cache=cache,
                )

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].status, "ready")
            self.assertEqual(cache.stats.entries, 0)
            self.assertEqual(cache.stats.uncacheable_files, 1)
            self.assertFalse((base / "scan-cache.json").exists())

    def test_cli_scan_continues_when_cache_initialization_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Demo.Vol.01.txt"
            book.write_text("content", encoding="utf-8")
            args = argparse.Namespace(
                folder=str(root),
                recursive=False,
                no_network=True,
                auto_rename=False,
                quiet=True,
                dry_run=True,
            )

            with (
                patch(
                    "lightnovel_selector.cli.PersistentScanCache",
                    side_effect=OSError("cache unavailable"),
                ),
                patch("builtins.print") as output,
            ):
                exit_code = run_cli(args)

            self.assertEqual(exit_code, 0)
            self.assertTrue(book.exists())
            self.assertTrue(any("扫描缓存不可用" in str(call.args[0]) for call in output.call_args_list if call.args))

    def test_http_bytes_rejects_oversized_response(self) -> None:
        response = unittest.mock.MagicMock()
        opened_response = response.__enter__.return_value
        opened_response.geturl.return_value = "https://example.test/cover.jpg"
        opened_response.read.return_value = b"12345"
        with (
            patch("lightnovel_selector.files._open_https", return_value=response),
            self.assertRaisesRegex(RuntimeError, "超过允许大小"),
        ):
            http_bytes("https://example.test/cover.jpg", max_bytes=4)

    def test_http_json_rejects_non_object_root(self) -> None:
        response = unittest.mock.MagicMock()
        opened_response = response.__enter__.return_value
        opened_response.geturl.return_value = "https://example.test/search"
        opened_response.headers.get_content_charset.return_value = "utf-8"
        opened_response.read.return_value = b"[]"

        with (
            patch("lightnovel_selector.files._open_https", return_value=response),
            self.assertRaisesRegex(RuntimeError, "JSON 根节点不是对象"),
        ):
            http_json("https://example.test/search")

    def test_bangumi_search_rejects_invalid_data_shape(self) -> None:
        with (
            patch("lightnovel_selector.metadata.http_json", return_value={"data": {}}),
            self.assertRaisesRegex(RuntimeError, "data 不是数组"),
        ):
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

    def test_manual_revision_preserves_unified_book_identity_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Original.Series.Vol.03.txt"
            book.write_text("content", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)
            plans[0] = replace(
                plans[0],
                identity=BookIdentity(
                    title="Original Series Volume 3",
                    series_name=plans[0].series_name,
                    authors=("Author",),
                    volume_number=3,
                    language="en",
                    tags=("Fantasy",),
                ),
            )

            revised = revise_classification_plan(plans, 0, "Corrected Series")

            self.assertEqual(revised.identity.title, "Original Series Volume 3")
            self.assertEqual(revised.identity.series_name, "Corrected Series")
            self.assertEqual(revised.identity.authors, ("Author",))
            self.assertEqual(revised.identity.volume_number, 3)
            self.assertEqual(revised.identity.language, "en")
            self.assertEqual(revised.identity.tags, ("Fantasy",))

    def test_manual_revision_rejects_oversized_series(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "book.txt"
            book.write_text("content", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)

            with self.assertRaisesRegex(ValueError, "不能超过 120"):
                revise_classification_plan(plans, 0, "x" * 121)

    def test_batch_revision_updates_only_the_original_series_group(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Demo Vol.01.txt").write_text("one", encoding="utf-8")
            (root / "Demo Vol.02.txt").write_text("two", encoding="utf-8")
            (root / "Other Vol.01.txt").write_text("other", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)
            demo_index = next(index for index, plan in enumerate(plans) if plan.series_name == "Demo")

            related = classification_plan_group_indices(plans, demo_index, "same_series")
            revised = revise_classification_plans(
                plans,
                demo_index,
                "Demo Corrected",
                scope="same_series",
            )

            self.assertEqual(revised, related)
            self.assertEqual(len(revised), 2)
            self.assertEqual({plans[index].series_name for index in revised}, {"Demo Corrected"})
            self.assertEqual(len({plans[index].target_path for index in revised}), 2)
            self.assertEqual(
                next(plan.series_name for plan in plans if plan.source_path.name.startswith("Other")),
                "Other",
            )

    def test_batch_revision_is_atomic_when_one_plan_cannot_be_edited(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Demo Vol.01.txt").write_text("one", encoding="utf-8")
            (root / "Demo Vol.02.txt").write_text("two", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)
            plans[1] = replace(plans[1], status="moved")
            before = list(plans)

            with self.assertRaisesRegex(ValueError, "已移动"):
                revise_classification_plans(
                    plans,
                    0,
                    "Demo Corrected",
                    scope="same_series",
                )

            self.assertEqual(plans, before)

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
        from shutil import move as real_move

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A Sword.Art.Online.Vol.01.txt"
            missing = root / "B Sword.Art.Online.Vol.02.txt"
            first.write_text("one", encoding="utf-8")
            missing.write_text("two", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)

            def fail_second_move(source, target):
                if Path(source) == missing:
                    raise FileNotFoundError("simulated missing source")
                return real_move(source, target)

            with (
                patch("lightnovel_selector.classification.shutil.move", side_effect=fail_second_move),
                self.assertRaises(FileNotFoundError),
            ):
                execute_classification_plan(plans, report_path=report_path)

            self.assertTrue(report_path.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["moved"], 1)
            self.assertEqual(report["items"][0]["operation"], "moved")
            self.assertTrue((root / "classification_report.recovery.jsonl").exists())

            restored, skipped = undo_classification_report(report_path)

            self.assertEqual((restored, skipped), (1, 0))
            self.assertTrue(first.exists())
            self.assertFalse((root / "classification_report.recovery.jsonl").exists())

    def test_batch_report_is_only_rewritten_at_operation_boundaries(self) -> None:
        from lightnovel_selector.classification import (
            write_classification_report as real_write_report,
        )

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for volume in range(1, 6):
                (root / f"Sword.Art.Online.Vol.{volume:02d}.txt").write_text(
                    f"volume {volume}",
                    encoding="utf-8",
                )
            report_path = root / "classification_report.json"
            journal_path = root / "classification_report.recovery.jsonl"
            plans = build_classification_plan(root, use_network=False)

            with patch(
                "lightnovel_selector.classification.write_classification_report",
                wraps=real_write_report,
            ) as writer:
                moved, skipped = execute_classification_plan(
                    plans,
                    report_path=report_path,
                )

            self.assertEqual((moved, skipped), (5, 0))
            self.assertEqual(writer.call_count, 2)
            self.assertFalse(journal_path.exists())

    def test_interrupted_batch_recovers_moved_files_from_journal(self) -> None:
        from shutil import move as real_move

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A Sword.Art.Online.Vol.01.txt"
            second = root / "B Sword.Art.Online.Vol.02.txt"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            report_path = root / "classification_report.json"
            journal_path = root / "classification_report.recovery.jsonl"
            plans = build_classification_plan(root, use_network=False)
            move_count = 0

            def interrupt_second_move(source, target):
                nonlocal move_count
                move_count += 1
                if move_count == 2:
                    raise KeyboardInterrupt
                return real_move(source, target)

            with (
                patch(
                    "lightnovel_selector.classification.shutil.move",
                    side_effect=interrupt_second_move,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                execute_classification_plan(plans, report_path=report_path)

            self.assertTrue(journal_path.exists())
            report = load_classification_report(report_path)

            self.assertEqual(report["summary"]["moved"], 1)
            self.assertEqual(report["items"][0]["operation"], "moved")
            self.assertIn("recovered_at", report)
            self.assertFalse(journal_path.exists())
            self.assertEqual(undo_classification_report(report_path), (1, 0))
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())

    def test_active_batch_report_read_does_not_consume_recovery_journal(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for volume in range(1, 3):
                (root / f"Sword.Art.Online.Vol.{volume:02d}.txt").write_text(
                    f"volume {volume}",
                    encoding="utf-8",
                )
            report_path = root / "classification_report.json"
            journal_path = root / "classification_report.recovery.jsonl"
            plans = build_classification_plan(root, use_network=False)
            observed_moved: list[int] = []

            def inspect_during_batch(done: int, _total: int) -> None:
                if done == 1:
                    report = load_classification_report(report_path)
                    observed_moved.append(report["summary"]["moved"])
                    self.assertTrue(journal_path.exists())

            execute_classification_plan(
                plans,
                report_path=report_path,
                progress_count=inspect_during_batch,
            )

            self.assertEqual(observed_moved, [0])
            self.assertEqual(load_classification_report(report_path)["summary"]["moved"], 2)
            self.assertFalse(journal_path.exists())

    def test_pending_recovery_journal_blocks_new_execution_without_overwrite(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("original", encoding="utf-8")
            report_path = root / "classification_report.json"
            journal_path = root / "classification_report.recovery.jsonl"
            original_report = '{"sentinel":true}\n'
            original_journal = '{"type":"header","execution_id":"pending"}\n'
            report_path.write_text(original_report, encoding="utf-8")
            journal_path.write_text(original_journal, encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)

            with self.assertRaisesRegex(ValueError, "尚未恢复"):
                execute_classification_plan(plans, report_path=report_path)

            self.assertEqual(report_path.read_text(encoding="utf-8"), original_report)
            self.assertEqual(journal_path.read_text(encoding="utf-8"), original_journal)
            self.assertTrue(source.exists())

    def test_initial_report_failure_releases_new_recovery_journal(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("original", encoding="utf-8")
            report_path = root / "classification_report.json"
            journal_path = root / "classification_report.recovery.jsonl"
            plans = build_classification_plan(root, use_network=False)

            with (
                patch(
                    "lightnovel_selector.classification.write_classification_report",
                    side_effect=OSError("simulated report failure"),
                ),
                self.assertRaisesRegex(OSError, "simulated report failure"),
            ):
                execute_classification_plan(plans, report_path=report_path)

            self.assertFalse(journal_path.exists())
            self.assertTrue(source.exists())

    def test_recovery_journal_rejects_ambiguous_file_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
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

            plans[0].target_path.write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "状态存在歧义"):
                load_classification_report(report_path)

            self.assertTrue(source.exists())
            self.assertTrue(plans[0].target_path.exists())
            self.assertTrue(journal_path.exists())

    def test_execute_rejects_file_changed_after_scan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Sword.Art.Online.Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)
            book.write_text("changed after preview", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "扫描后发生变化"):
                execute_classification_plan(plans, report_path=root / "classification_report.json")

            self.assertTrue(book.exists())
            self.assertFalse((root / "Sword Art Online" / book.name).exists())

    def test_execute_rejects_plan_count_above_scan_limit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "Sword.Art.Online.Vol.01.txt"
            source.write_text("one", encoding="utf-8")
            plan = build_classification_plan(root, use_network=False)[0]

            with self.assertRaisesRegex(ValueError, "单次执行最多支持"):
                execute_classification_plan([plan] * (SCAN_MAX_FILES + 1))

            self.assertTrue(source.exists())

    def test_execute_rechecks_each_source_during_long_batch(self) -> None:
        from shutil import move as real_move

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A Sword.Art.Online.Vol.01.txt"
            second = root / "B Sword.Art.Online.Vol.02.txt"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            report_path = root / "classification_report.json"
            plans = build_classification_plan(root, use_network=False)

            def change_second_after_first(source, target):
                result = real_move(source, target)
                if Path(source) == first:
                    second.write_text("changed while batch was running", encoding="utf-8")
                return result

            with (
                patch(
                    "lightnovel_selector.classification.shutil.move",
                    side_effect=change_second_after_first,
                ),
                self.assertRaisesRegex(ValueError, "扫描后发生变化"),
            ):
                execute_classification_plan(plans, report_path=report_path)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["moved"], 1)
            self.assertTrue(second.exists())
            self.assertEqual(undo_classification_report(report_path), (1, 0))
            self.assertTrue(first.exists())

    def test_unwritable_report_fails_before_moving_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Sword.Art.Online.Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)

            with (
                patch(
                    "lightnovel_selector.classification.write_json_atomic",
                    side_effect=PermissionError("blocked"),
                ),
                self.assertRaises(OSError),
            ):
                execute_classification_plan(plans, report_path=root / "report.json")

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


class ReportHistoryTests(unittest.TestCase):
    def test_archives_multiple_batches_and_undoes_a_selected_history_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "Demo Vol.01.txt"
            first.write_text("one", encoding="utf-8")
            report_path = root / "classification_report.json"

            execute_classification_plan(
                build_classification_plan(root, use_network=False),
                report_path=report_path,
            )
            first_history_path = archive_classification_report(report_path)
            self.assertIsNotNone(first_history_path)
            assert first_history_path is not None
            first_report = load_classification_report(first_history_path)
            first_id = first_report["execution_id"]

            second = root / "Other Vol.01.txt"
            second.write_text("two", encoding="utf-8")
            execute_classification_plan(
                build_classification_plan(root, use_network=False),
                report_path=report_path,
            )
            archive_classification_report(report_path)
            latest_report = load_classification_report(report_path)

            history = list_classification_reports(root)

            self.assertEqual(history["total_count"], 2)
            self.assertEqual(history["invalid_count"], 0)
            self.assertEqual(history["reports"][0]["report_id"], latest_report["execution_id"])
            self.assertTrue(history["reports"][0]["is_latest"])
            self.assertEqual(
                resolve_classification_report(root, first_id),
                first_history_path,
            )

            restored, skipped = undo_classification_report(first_history_path)
            mark_classification_report_undone(
                first_history_path,
                restored=restored,
                skipped=skipped,
            )

            refreshed = list_classification_reports(root)
            first_entry = next(item for item in refreshed["reports"] if item["report_id"] == first_id)
            self.assertEqual((restored, skipped), (1, 0))
            self.assertTrue(first.exists())
            self.assertTrue((root / "Other" / second.name).exists())
            self.assertEqual(first_entry["status"], "undone")
            self.assertFalse(first_entry["can_undo"])

    def test_history_listing_counts_corrupt_entries_and_rejects_invalid_ids(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            history_dir = classification_report_history_directory(root, create=True)
            self.assertIsNotNone(history_dir)
            assert history_dir is not None
            (history_dir / "classification_report-invalid.json").write_text(
                "not-json",
                encoding="utf-8",
            )

            history = list_classification_reports(root)

            self.assertEqual(history["total_count"], 0)
            self.assertEqual(history["invalid_count"], 1)
            with self.assertRaisesRegex(ValueError, "执行编号无效"):
                resolve_classification_report(root, "../outside")

    def test_valid_archive_remains_resolvable_when_latest_report_is_corrupt(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Demo Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            report_path = root / "classification_report.json"
            execute_classification_plan(
                build_classification_plan(root, use_network=False),
                report_path=report_path,
            )
            archived = archive_classification_report(report_path)
            self.assertIsNotNone(archived)
            assert archived is not None
            report_id = load_classification_report(archived)["execution_id"]
            report_path.write_text("corrupt", encoding="utf-8")

            resolved = resolve_classification_report(root, report_id)

            self.assertEqual(resolved, archived)
            wrong_id = "f" * 32
            mismatched = archived.with_name(f"classification_report-20260720T120000Z-{wrong_id}.json")
            mismatched.write_bytes(archived.read_bytes())
            history = list_classification_reports(root)
            self.assertEqual(history["total_count"], 1)
            self.assertEqual(history["invalid_count"], 2)

    def test_history_directory_cannot_replace_the_primary_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Demo Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            report_path = root / "classification_report.json"
            execute_classification_plan(
                build_classification_plan(root, use_network=False),
                report_path=report_path,
            )
            (root / ".lightnovel-selector").write_text("occupied", encoding="utf-8")

            with self.assertRaises(NotADirectoryError):
                archive_classification_report(report_path)

            self.assertTrue(report_path.is_file())
            self.assertEqual(load_classification_report(report_path)["summary"]["moved"], 1)

    def test_history_report_outside_its_declared_root_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "library"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            book = root / "Demo Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            report_path = root / "classification_report.json"
            execute_classification_plan(
                build_classification_plan(root, use_network=False),
                report_path=report_path,
            )
            copied_report = outside / "classification_report.json"
            copied_report.write_bytes(report_path.read_bytes())

            with self.assertRaisesRegex(ValueError, "必须保留"):
                undo_classification_report(copied_report)

    def test_history_directory_symbolic_link_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "library"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            book = root / "Demo Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            report_path = root / "classification_report.json"
            execute_classification_plan(
                build_classification_plan(root, use_network=False),
                report_path=report_path,
            )
            history_root = root / ".lightnovel-selector"
            history_root.mkdir()
            try:
                (history_root / "history").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"当前测试环境无法创建目录符号链接：{exc}")

            with self.assertRaisesRegex(ValueError, "符号链接或目录联接"):
                archive_classification_report(report_path)

            self.assertFalse(any(outside.iterdir()))

    def test_legacy_report_remains_visible_without_archive_warning(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Demo Vol.01.txt"
            book.write_text("one", encoding="utf-8")
            report_path = root / "classification_report.json"
            execute_classification_plan(
                build_classification_plan(root, use_network=False),
                report_path=report_path,
            )
            report = load_classification_report(report_path)
            report["schema_version"] = 1
            report.pop("execution_id", None)
            report.pop("root_path", None)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False),
                encoding="utf-8",
            )
            with patch(
                "lightnovel_selector.application.load_app_settings",
                return_value=AppSettings(use_network=False),
            ):
                service = ApplicationService()
            service.set_folder(str(root))

            history = service.report_history()

            self.assertIsNone(history["warning"])
            self.assertEqual(history["total_count"], 1)
            self.assertEqual(history["reports"][0]["report_id"], "latest")


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

    def test_reads_complete_epub_book_identity(self) -> None:
        with TemporaryDirectory() as temp_dir:
            epub_path = Path(temp_dir) / "weak-name.epub"
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
                    <package xmlns="http://www.idpf.org/2007/opf"
                             xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">
                      <metadata>
                        <dc:title>无职转生 第13卷</dc:title>
                        <dc:creator>理不尽な孫の手</dc:creator>
                        <dc:language>zh-CN</dc:language>
                        <dc:subject>异世界</dc:subject>
                        <dc:subject>成长</dc:subject>
                        <meta name="calibre:series" content="无职转生"/>
                        <meta name="calibre:series_index" content="13"/>
                      </metadata>
                    </package>""",
                )

            identity = read_epub_book_identity(epub_path)

            self.assertEqual(
                identity,
                BookIdentity(
                    title="无职转生 第13卷",
                    series_name="无职转生",
                    authors=("理不尽な孫の手",),
                    volume_number=13,
                    language="zh-Hans",
                    tags=("异世界", "成长"),
                ),
            )
            self.assertEqual(read_book_identity(epub_path).authors, ("理不尽な孫の手",))

    def test_bounds_untrusted_epub_identity_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            epub_path = Path(temp_dir) / "oversized.epub"
            creators = "".join(f"<dc:creator>{index}-{'A' * 300}</dc:creator>" for index in range(20))
            subjects = "".join(f"<dc:subject>{index}-{'T' * 300}</dc:subject>" for index in range(30))
            with ZipFile(epub_path, "w", ZIP_DEFLATED) as archive:
                archive.writestr(
                    "META-INF/container.xml",
                    """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
                    <rootfiles><rootfile full-path="content.opf"/></rootfiles></container>""",
                )
                archive.writestr(
                    "content.opf",
                    f"""<package xmlns="http://www.idpf.org/2007/opf"
                    xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>
                    <dc:title>{"X" * 2000}</dc:title>{creators}{subjects}
                    </metadata></package>""",
                )

            identity = read_epub_book_identity(epub_path)

            self.assertIsNotNone(identity)
            assert identity is not None
            self.assertEqual(len(identity.title), METADATA_TEXT_MAX_CHARS)
            self.assertEqual(len(identity.authors), IDENTITY_MAX_AUTHORS)
            self.assertEqual(len(identity.tags), IDENTITY_MAX_TAGS)
            self.assertTrue(
                all(len(value) <= IDENTITY_VALUE_MAX_CHARS for value in (*identity.authors, *identity.tags))
            )

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

    def test_extracts_unified_identity_from_bangumi_item(self) -> None:
        item = {
            "id": 207694,
            "name": "無職転生 ~異世界行ったら本気だす~ (13)",
            "name_cn": "无职转生 ～到了异世界就拿出真本事～ (13)",
            "infobox": [
                {"key": "作者", "value": "理不尽な孫の手"},
                {"key": "语言", "value": "日文"},
            ],
            "tags": [{"name": "异世界"}, {"name": "奇幻"}],
        }

        identity = bangumi_identity_from_item(item, query="无职转生 13")

        self.assertEqual(identity.series_name, "无职转生 ~到了异世界就拿出真本事")
        self.assertEqual(identity.authors, ("理不尽な孫の手",))
        self.assertEqual(identity.volume_number, 13)
        self.assertEqual(identity.language, "ja")
        self.assertEqual(identity.tags, ("异世界", "奇幻"))

    def test_malformed_remote_metadata_degrades_without_type_errors(self) -> None:
        item = {
            "name": {"unexpected": "object"},
            "name_cn": ["unexpected", "array"],
            "images": ["unexpected"],
            "image": "http://example.test/cover.jpg",
            "infobox": {"unexpected": "object"},
        }

        self.assertEqual(bangumi_title_candidates(item), [])
        self.assertIsNone(bangumi_cover_url(item))
        self.assertIsNone(clean_summary({"unexpected": "object"}))

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

    def test_unified_identity_serialization_is_bounded_and_legacy_compatible(self) -> None:
        identity = BookIdentity(
            title="Mushoku Tensei (13)",
            series_name="Mushoku Tensei",
            authors=("Rifujin na Magonote",),
            volume_number=13,
            language="en",
            tags=("Fantasy", "Isekai"),
        )

        self.assertEqual(book_identity_from_dict(book_identity_to_dict(identity)), identity)
        legacy = book_metadata_from_dict(
            {
                "title": "Mushoku Tensei (13)",
                "source": "legacy",
                "confidence": 0.8,
                "query": "Mushoku Tensei 13",
            }
        )
        self.assertIsNotNone(legacy)
        assert legacy is not None
        self.assertEqual(legacy.identity.series_name, "Mushoku Tensei")
        self.assertEqual(legacy.identity.volume_number, 13)
        self.assertIsNone(
            book_identity_from_dict(
                {
                    "title": "Broken",
                    "series_name": "Broken",
                    "authors": "not-an-array",
                }
            )
        )

    def test_cached_metadata_rejects_invalid_types_and_non_finite_confidence(self) -> None:
        self.assertIsNone(book_metadata_from_dict({"title": ["not", "text"]}))
        self.assertIsNone(book_metadata_from_dict({"title": "Broken", "confidence": "nan"}))

        loaded = book_metadata_from_dict(
            {
                "title": "Valid",
                "confidence": 0.75,
                "summary": {"not": "text"},
                "cover_url": ["not", "text"],
            }
        )

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertIsNone(loaded.summary)
        self.assertIsNone(loaded.cover_url)

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

    def test_persistent_metadata_cache_stays_within_size_limit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            with patch("lightnovel_selector.storage.METADATA_CACHE_MAX_BYTES", 900):
                cache = PersistentMetadataCache(cache_path)
                for index in range(12):
                    cache.set(
                        f"book:{index}",
                        {"title": f"Book {index}", "summary": "x" * 280},
                    )

                self.assertLessEqual(cache_path.stat().st_size, 900)
                self.assertLess(len(cache.data["entries"]), 12)


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
                history = service.report_history()
                self.assertEqual(history["total_count"], 1)
                self.assertIsNone(history["warning"])
                report_id = history["reports"][0]["report_id"]
                self.assertTrue(history["reports"][0]["can_undo"])
                report_summary = service.report_summary(report_id)
                self.assertEqual(report_summary["report_id"], report_id)
                self.assertTrue(report_summary["can_undo"])

                service.start_undo(report_id)
                undone = self.wait_for_operation(service)
                self.assertEqual(undone["operation"]["state"], "success")
                self.assertTrue(book.exists())
                refreshed_history = service.report_history()
                self.assertEqual(refreshed_history["reports"][0]["status"], "undone")
                refreshed_summary = service.report_summary(report_id)
                self.assertTrue(refreshed_summary["undo_completed"])
                self.assertFalse(refreshed_summary["can_undo"])
                self.assertEqual(
                    service.current_report(),
                    root / "classification_report.json",
                )

    def test_application_scan_exposes_incremental_cache_reuse(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "library"
            root.mkdir()
            cache_path = base / "scan-cache.json"
            (root / "Cached.Series.Vol.01.txt").write_text(
                "Cached Series 第一卷",
                encoding="utf-8",
            )
            with (
                patch(
                    "lightnovel_selector.application.load_app_settings",
                    return_value=AppSettings(use_network=False),
                ),
                patch("lightnovel_selector.application.try_save_app_settings", return_value=None),
                patch(
                    "lightnovel_selector.application.PersistentScanCache",
                    side_effect=lambda: PersistentScanCache(cache_path),
                ),
            ):
                service = ApplicationService()
                service.set_folder(str(root))
                service.start_scan()
                first_scan = self.wait_for_operation(service)
                service.start_scan()
                second_scan = self.wait_for_operation(service)

            self.assertEqual(first_scan["operation"]["state"], "success")
            self.assertEqual(second_scan["operation"]["state"], "success")
            self.assertEqual(second_scan["scan_cache"]["reused_files"], 1)
            self.assertEqual(second_scan["scan_cache"]["quick_signature_hits"], 1)
            self.assertEqual(second_scan["scan_cache"]["local_analysis_hits"], 1)
            self.assertIn("复用了 1 个未变化文件的缓存", second_scan["operation"]["message"])

    def test_scan_cache_initialization_failure_does_not_block_scan(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Demo.Vol.01.txt").write_text("content", encoding="utf-8")
            with (
                patch(
                    "lightnovel_selector.application.load_app_settings",
                    return_value=AppSettings(use_network=False),
                ),
                patch("lightnovel_selector.application.try_save_app_settings", return_value=None),
                patch(
                    "lightnovel_selector.application.PersistentScanCache",
                    side_effect=OSError("cache unavailable"),
                ),
            ):
                service = ApplicationService()
                service.set_folder(str(root))
                service.start_scan()
                snapshot = self.wait_for_operation(service)

            self.assertEqual(snapshot["operation"]["state"], "success")
            self.assertEqual(snapshot["counts"]["ready"], 1)
            self.assertEqual(snapshot["scan_cache"]["write_warning"], "cache unavailable")
            self.assertIsNone(snapshot["operation"]["error"])
            self.assertFalse(snapshot["operation"]["can_cancel"])

    def test_partial_apply_failure_is_archived_for_selected_undo(self) -> None:
        from shutil import move as real_move

        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "A Demo Vol.01.txt"
            second = root / "B Demo Vol.02.txt"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            with (
                patch(
                    "lightnovel_selector.application.load_app_settings",
                    return_value=AppSettings(use_network=False),
                ),
                patch("lightnovel_selector.application.try_save_app_settings", return_value=None),
            ):
                service = ApplicationService()
                service.set_folder(str(root))
                service.start_scan()
                scanned = self.wait_for_operation(service)
                self.assertEqual(scanned["operation"]["state"], "success")

                def fail_second_move(source, target):
                    if Path(source) == second:
                        raise PermissionError("simulated locked file")
                    return real_move(source, target)

                with patch(
                    "lightnovel_selector.classification.shutil.move",
                    side_effect=fail_second_move,
                ):
                    service.start_apply()
                    failed = self.wait_for_operation(service)

                self.assertEqual(failed["operation"]["state"], "error")
                history = service.report_history()
                self.assertEqual(history["total_count"], 1)
                self.assertEqual(history["reports"][0]["summary"]["moved"], 1)
                self.assertTrue(history["reports"][0]["can_undo"])

                service.start_undo(history["reports"][0]["report_id"])
                undone = self.wait_for_operation(service)

                self.assertEqual(undone["operation"]["state"], "success")
                self.assertTrue(first.exists())
                self.assertTrue(second.exists())

    def test_service_bulk_edit_returns_count_and_snapshot(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Demo Vol.01.txt").write_text("one", encoding="utf-8")
            (root / "Demo Vol.02.txt").write_text("two", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)
            with patch(
                "lightnovel_selector.application.load_app_settings",
                return_value=AppSettings(use_network=False),
            ):
                service = ApplicationService()
            service.folder = root
            service.plans = plans

            result = service.edit_plans(
                0,
                "Demo Corrected",
                scope="same_series",
            )

            self.assertEqual(result["updated_count"], 2)
            self.assertEqual(len(result["updated_indices"]), 2)
            self.assertEqual(
                {item["series_name"] for item in result["snapshot"]["plans"]},
                {"Demo Corrected"},
            )

    def test_candidate_lookup_is_cached_without_changing_plan_revision(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Demo Vol.01.txt").write_text("one", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)
            with patch(
                "lightnovel_selector.application.load_app_settings",
                return_value=AppSettings(use_network=True),
            ):
                service = ApplicationService()
            service.folder = root
            service.plans = plans
            remote = ResolveResult(
                identity=BookIdentity(
                    title="Demo Alternative",
                    series_name="Demo Alternative",
                ),
                source="Test Provider",
                confidence=0.88,
                local_guess="Demo",
            )
            revision = service.plans_revision

            with patch(
                "lightnovel_selector.application.SeriesResolver.resolve_candidates",
                return_value=(remote,),
            ):
                result = service.load_candidates(0)

            self.assertIsNone(result["warning"])
            self.assertEqual(service.plans_revision, revision)
            self.assertTrue(result["candidates"][0]["is_current"])
            self.assertEqual(
                [candidate["series_name"] for candidate in result["candidates"]],
                ["Demo", "Demo Alternative"],
            )
            with patch(
                "lightnovel_selector.application.SeriesResolver.resolve_book_metadata_for_query",
                return_value=None,
            ):
                detail = service.get_detail(0)
            self.assertEqual(detail["matching_series_count"], 1)
            self.assertTrue(detail["can_load_candidates"])
            self.assertEqual(len(detail["candidates"]), 2)

    def test_candidate_lookup_rejects_results_for_a_replaced_preview(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Demo Vol.01.txt").write_text("one", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)
            with patch(
                "lightnovel_selector.application.load_app_settings",
                return_value=AppSettings(use_network=True),
            ):
                service = ApplicationService()
            service.folder = root
            service.plans = plans
            original_candidates = service.plans[0].candidates
            remote = ResolveResult(
                identity=BookIdentity(
                    title="Stale Alternative",
                    series_name="Stale Alternative",
                ),
                source="Test Provider",
                confidence=0.88,
                local_guess="Demo",
            )

            def replace_preview(_: str) -> tuple[ResolveResult, ...]:
                service.plans_revision += 1
                return (remote,)

            with (
                patch(
                    "lightnovel_selector.application.SeriesResolver.resolve_candidates",
                    side_effect=replace_preview,
                ),
                self.assertRaisesRegex(RuntimeError, "预览已变化"),
            ):
                service.load_candidates(0)

            self.assertEqual(service.plans[0].candidates, original_candidates)

    def test_stale_detail_revision_cannot_edit_a_replaced_preview(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Demo Vol.01.txt").write_text("one", encoding="utf-8")
            plans = build_classification_plan(root, use_network=False)
            with patch(
                "lightnovel_selector.application.load_app_settings",
                return_value=AppSettings(use_network=False),
            ):
                service = ApplicationService()
            service.folder = root
            service.plans = plans
            stale_revision = service.plans_revision
            service.plans_revision += 1

            with self.assertRaisesRegex(RuntimeError, "预览已变化"):
                service.edit_plans(
                    0,
                    "Wrong Target",
                    scope="single",
                    expected_plans_revision=stale_revision,
                )

            self.assertEqual(service.plans[0].series_name, "Demo")

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

    def test_local_cover_is_loaded_only_when_detail_is_requested(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Sword.Art.Online.Vol.01.zip"
            with ZipFile(book, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("cover.png", MINIMAL_PNG)
            plans = build_classification_plan(root, use_network=False)

            with patch(
                "lightnovel_selector.application.load_app_settings",
                return_value=AppSettings(use_network=False),
            ):
                service = ApplicationService()
            service.folder = root
            service.plans = plans

            detail = service.get_detail(0)
            self.assertEqual(detail["cover_source"], "本地封面")
            self.assertTrue(detail["cover_data_url"].startswith("data:image/png;base64,"))

    def test_snapshot_only_resends_plans_after_revision_change(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with patch("lightnovel_selector.application.load_app_settings", return_value=AppSettings()):
            service = ApplicationService()
        first = service.snapshot(plans_revision=-1)
        second = service.snapshot(plans_revision=first["plans_revision"])

        self.assertEqual(first["plans"], [])
        self.assertIsNone(second["plans"])

    def test_report_view_sanitizes_malformed_field_types(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / "classification_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "total": True,
                            "moved": -1,
                            "skipped": 2,
                            "duplicates": "1",
                            "errors": 0,
                        },
                        "created_at": {"unexpected": "object"},
                        "items": [
                            {
                                "source_path": ["unexpected"],
                                "target_path": str(root / "Series" / "book.txt"),
                                "series_name": {"unexpected": "object"},
                                "confidence": float("nan"),
                                "operation": "moved",
                            },
                            "unexpected",
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "lightnovel_selector.application.load_app_settings",
                return_value=AppSettings(use_network=False),
            ):
                service = ApplicationService()
            service.folder = root
            service.report_path = report_path

            report = service.report_summary()

            self.assertEqual(report["summary"]["total"], 0)
            self.assertEqual(report["summary"]["skipped"], 2)
            self.assertIsNone(report["created_at"])
            self.assertEqual(report["item_count"], 2)
            self.assertFalse(report["items_truncated"])
            self.assertEqual(len(report["items"]), 1)
            self.assertEqual(report["items"][0]["source_path"], "")
            self.assertEqual(report["items"][0]["confidence"], 0.0)

    def test_report_view_caps_large_item_lists(self) -> None:
        from lightnovel_selector.application import ApplicationService

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / "classification_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "total": 2,
                            "moved": 2,
                            "skipped": 0,
                            "duplicates": 0,
                            "errors": 0,
                        },
                        "items": [
                            {
                                "source_path": str(root / f"book-{index}.txt"),
                                "target_path": str(root / "Series" / f"book-{index}.txt"),
                                "operation": "moved",
                            }
                            for index in range(2)
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch(
                    "lightnovel_selector.application.load_app_settings",
                    return_value=AppSettings(use_network=False),
                ),
                patch("lightnovel_selector.application.REPORT_UI_MAX_ITEMS", 1),
            ):
                service = ApplicationService()
                service.folder = root
                service.report_path = report_path
                report = service.report_summary()

            self.assertEqual(report["item_count"], 2)
            self.assertTrue(report["items_truncated"])
            self.assertEqual(len(report["items"]), 1)

    def test_rejected_concurrent_scan_does_not_change_revision(self) -> None:
        from lightnovel_selector.application import ApplicationService

        started = threading.Event()
        release = threading.Event()

        def slow_scan(*_args, **_kwargs):
            started.set()
            release.wait(timeout=2)
            return []

        with (
            TemporaryDirectory() as temp_dir,
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
