from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from lightnovel_classifier import (
    BookMetadata,
    PersistentMetadataCache,
    bangumi_cover_url,
    bangumi_title_candidates,
    book_metadata_from_dict,
    book_metadata_to_dict,
    build_classification_plan,
    clean_summary,
    execute_classification_plan,
    extract_book_lookup_query,
    extract_series_guess,
    identity_query_for_path,
    item_matches_volume,
    normalize_for_match,
    parse_volume_number,
    read_local_cover_bytes,
    safe_folder_name,
    suggest_renamed_filename,
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


if __name__ == "__main__":
    unittest.main()
