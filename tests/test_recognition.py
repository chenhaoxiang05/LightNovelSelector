import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from lightnovel_classifier import (
    AppSettings,
    BookIdentity,
    CustomRule,
    RecognitionCorrectionMemory,
    ResolveResult,
    assess_recognition,
    build_classification_plan,
    classification_plan_to_report_item,
    extract_series_guess,
    identity_from_filename,
    normalize_identity_values,
    parse_volume_number,
    read_book_identity,
    score_title,
)
from lightnovel_selector.application import ApplicationService, plan_to_dict

CORPUS_PATH = Path(__file__).parent / "fixtures" / "recognition_corpus.json"


def _load_corpus() -> dict:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def _write_epub(path: Path, case: dict) -> None:
    creators = "".join(f"<dc:creator>{escape(value)}</dc:creator>" for value in case["creators"])
    subjects = "".join(f"<dc:subject>{escape(value)}</dc:subject>" for value in case["subjects"])
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         version="3.0">
  <metadata>
    <dc:title>{escape(case["title"])}</dc:title>
    {creators}
    <dc:language>{escape(case["language"])}</dc:language>
    {subjects}
    <meta property="belongs-to-collection">{escape(case["series"])}</meta>
    <meta name="calibre:series_index" content="{escape(case["series_index"])}" />
  </metadata>
  <manifest />
  <spine />
</package>
"""
    container = """<?xml version="1.0" encoding="utf-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
"""
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as epub:
        epub.writestr("META-INF/container.xml", container)
        epub.writestr("content.opf", opf)


class SanitizedRecognitionCorpusTests(unittest.TestCase):
    def test_filename_corpus(self) -> None:
        for case in _load_corpus()["filename_cases"]:
            with self.subTest(file_name=case["file_name"]):
                identity = identity_from_filename(case["file_name"])
                self.assertEqual(identity.series_name, case["series"])
                self.assertEqual(identity.volume_number, case["volume"])
                self.assertEqual(identity.language, case["language"])

    def test_epub_corpus(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for case in _load_corpus()["epub_cases"]:
                with self.subTest(file_name=case["file_name"]):
                    path = root / case["file_name"]
                    _write_epub(path, case)
                    identity = read_book_identity(path)
                    expected = case["expected"]
                    self.assertEqual(identity.title, expected["title"])
                    self.assertEqual(identity.series_name, expected["series"])
                    self.assertEqual(identity.authors, tuple(expected["authors"]))
                    self.assertEqual(identity.volume_number, expected["volume"])
                    self.assertEqual(identity.language, expected["language"])
                    self.assertEqual(identity.tags, tuple(expected["tags"]))

    def test_corpus_declares_privacy_boundary(self) -> None:
        corpus = _load_corpus()
        self.assertEqual(corpus["schema_version"], 1)
        self.assertIn("不含用户路径", corpus["privacy_note"])


class RecognitionNormalizationTests(unittest.TestCase):
    def test_parses_chinese_japanese_and_roman_volume_numbers(self) -> None:
        self.assertEqual(parse_volume_number("星界旅人 第十二卷"), 12)
        self.assertEqual(parse_volume_number("星界の旅人 第〇七巻"), 7)
        self.assertEqual(parse_volume_number("Astral Traveler Vol. IV"), 4)
        self.assertIsNone(parse_volume_number("Civilization"))

    def test_parse_volume_number_edge_cases(self) -> None:
        # Boundary conditions (0 to 999)
        self.assertEqual(parse_volume_number("Title 000"), 0)
        self.assertEqual(parse_volume_number("Title 999"), 999)
        self.assertIsNone(parse_volume_number("Title 1000"))

        # File extension stripping for supported extensions vs unsupported
        self.assertEqual(parse_volume_number("file_vol_1.epub"), 1)
        self.assertEqual(parse_volume_number("archive_book_2.zip"), 2)

        # Different format markers
        self.assertEqual(parse_volume_number("Title book 3"), 3)
        self.assertEqual(parse_volume_number("Title v 4"), 4)
        self.assertEqual(parse_volume_number("Title (5)"), 5)
        self.assertEqual(parse_volume_number("Title （6）"), 6)
        self.assertEqual(parse_volume_number("Title - 7"), 7)
        self.assertEqual(parse_volume_number("Title ~ 8 ~"), 8)

        # Chinese numeral variations and different volume markers
        self.assertEqual(parse_volume_number("第一卷"), 1)
        self.assertEqual(parse_volume_number("第二冊"), 2)
        self.assertEqual(parse_volume_number("第十集"), 10)
        self.assertEqual(parse_volume_number("第二十部"), 20)
        self.assertEqual(parse_volume_number("第一百巻"), 100)

        # Decimal numbers (will parse the first integer matched, e.g. Vol 1)
        self.assertEqual(parse_volume_number("Vol. 1.5"), 1)

        # Empty string and unrelated alphabetical characters
        self.assertIsNone(parse_volume_number(""))
        self.assertIsNone(parse_volume_number("No Numbers Here"))

    def test_subtitle_variant_improves_matching_without_changing_display(self) -> None:
        title = "Project Aurora ~Afterglow~"
        self.assertEqual(
            extract_series_guess(f"{title} Vol.03.epub"),
            "Project Aurora ~Afterglow",
        )
        self.assertGreaterEqual(score_title(title, "Project Aurora"), 0.9)
        self.assertLess(
            score_title(
                "Project Aurora ~Afterglow~",
                "Project Aurora ~Midnight~",
            ),
            0.9,
        )

    def test_author_normalization_deduplicates_roles_and_punctuation(self) -> None:
        authors = normalize_identity_values(
            (
                "作者: Mira Vale",
                "Mira Vale [Writer]",
                "Mira, Vale",
            ),
            limit=8,
            kind="author",
        )
        self.assertEqual(authors, ("Mira Vale",))


class CorrectionMemoryTests(unittest.TestCase):
    def test_manual_correction_is_persisted_and_reused(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            memory_path = root / "aliases.json"
            book = root / "Astral.Traveler.Vol.01.txt"
            book.write_text("content", encoding="utf-8")
            memory = RecognitionCorrectionMemory(memory_path)
            plan = build_classification_plan(root, use_network=False)[0]

            with patch(
                "lightnovel_selector.application.load_app_settings",
                return_value=AppSettings(),
            ):
                service = ApplicationService(
                    metadata_providers=(),
                    correction_memory=memory,
                )
            service.folder = root
            service.plans = [plan]
            result = service.edit_plans(0, "星界旅人", scope="single")

            self.assertEqual(result["updated_count"], 1)
            self.assertGreater(memory.count, 0)
            reloaded = RecognitionCorrectionMemory(memory_path)
            rescanned = build_classification_plan(
                root,
                use_network=False,
                correction_memory=reloaded,
            )[0]
            self.assertEqual(rescanned.series_name, "星界旅人")
            self.assertEqual(rescanned.resolver_source, "本地修正记忆")
            self.assertEqual(rescanned.confidence_level, "高")
            self.assertIn("手动确认", rescanned.classification_reason)

    def test_custom_rule_keeps_precedence_over_correction_memory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Astral.Traveler.Vol.01.txt"
            book.write_text("content", encoding="utf-8")
            memory = RecognitionCorrectionMemory(root / "aliases.json")
            original = build_classification_plan(root, use_network=False)[0]
            memory.remember_plans((original,), "记忆系列")

            revised = build_classification_plan(
                root,
                use_network=False,
                custom_rules=(CustomRule(pattern="Astral*", series="规则系列"),),
                correction_memory=memory,
            )[0]

            self.assertEqual(revised.series_name, "规则系列")
            self.assertEqual(revised.resolver_source, "自定义规则")

    def test_provider_result_can_be_remapped_after_network_resolution(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Unrelated.Query.Vol.01.txt"
            book.write_text("content", encoding="utf-8")
            memory = RecognitionCorrectionMemory(root / "aliases.json")
            memory.remember(("Provider Canonical",), "用户确认系列")
            provider_result = ResolveResult(
                identity=BookIdentity(
                    title="Provider Canonical",
                    series_name="Provider Canonical",
                ),
                source="测试来源",
                confidence=0.93,
                local_guess="Unrelated Query",
            )

            with patch(
                "lightnovel_selector.classification_planning.SeriesResolver.resolve",
                return_value=provider_result,
            ):
                plan = build_classification_plan(
                    root,
                    use_network=True,
                    correction_memory=memory,
                )[0]

            self.assertEqual(plan.series_name, "用户确认系列")
            self.assertEqual(plan.resolver_source, "本地修正记忆")

    def test_corrupted_memory_degrades_to_empty(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "aliases.json"
            path.write_text("{broken", encoding="utf-8")
            memory = RecognitionCorrectionMemory(path)

            self.assertEqual(memory.count, 0)
            self.assertIsNone(memory.lookup("Astral Traveler"))

    def test_memory_file_is_pruned_to_the_bounded_read_limit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "aliases.json"
            memory = RecognitionCorrectionMemory(path)
            aliases = tuple(f"匿名系列别名 {index} " + "长" * 30 for index in range(20))

            with patch(
                "lightnovel_selector.corrections.CORRECTION_MEMORY_MAX_BYTES",
                700,
            ):
                memory.remember(aliases, "确认后的系列")
                self.assertLessEqual(path.stat().st_size, 700)
                reloaded = RecognitionCorrectionMemory(path)
                self.assertGreater(reloaded.count, 0)
                self.assertLess(reloaded.count, len(aliases))

    def test_memory_write_failure_does_not_undo_manual_correction(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Astral.Traveler.Vol.01.txt"
            book.write_text("content", encoding="utf-8")
            memory = RecognitionCorrectionMemory(root / "aliases.json")
            plan = build_classification_plan(root, use_network=False)[0]
            with patch(
                "lightnovel_selector.application.load_app_settings",
                return_value=AppSettings(),
            ):
                service = ApplicationService(
                    metadata_providers=(),
                    correction_memory=memory,
                )
            service.folder = root
            service.plans = [plan]

            with patch.object(
                memory,
                "try_remember_plans",
                return_value=(0, OSError("locked")),
            ):
                result = service.edit_plans(0, "星界旅人", scope="single")

            self.assertEqual(result["snapshot"]["plans"][0]["series_name"], "星界旅人")
            self.assertTrue(any("未能保存" in item["message"] for item in result["snapshot"]["logs"]))


class ConfidenceExplanationTests(unittest.TestCase):
    def test_calibration_is_monotonic_bounded_and_explainable(self) -> None:
        identity = BookIdentity(title="Demo", series_name="Demo")
        low = assess_recognition(
            raw_confidence=0.55,
            source="测试来源",
            identity_query="Demo",
            chosen_identity=identity,
            local_identity=identity,
            used_content_hint=False,
            has_book_metadata=False,
        )
        high = assess_recognition(
            raw_confidence=0.95,
            source="测试来源",
            identity_query="Demo",
            chosen_identity=identity,
            local_identity=identity,
            used_content_hint=False,
            has_book_metadata=True,
        )

        self.assertLess(low.confidence, high.confidence)
        self.assertLessEqual(high.confidence, 0.99)
        self.assertEqual(high.level, "高")
        self.assertIn("测试来源", high.reason)
        self.assertIn("标题与系列完全一致", high.evidence)

    def test_plan_and_payload_expose_calibrated_reason(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "Astral.Traveler.Vol.02.txt"
            book.write_text("content", encoding="utf-8")

            plan = build_classification_plan(root, use_network=False)[0]
            payload = plan_to_dict(plan, 0)
            report_item = classification_plan_to_report_item(plan)

            self.assertLess(plan.confidence, 0.6)
            self.assertEqual(plan.confidence_level, "需复核")
            self.assertIn("文件名", plan.classification_reason)
            self.assertIn("识别到第 2 卷", plan.classification_evidence)
            self.assertEqual(payload["classification_reason"], plan.classification_reason)
            self.assertEqual(
                payload["classification_evidence"],
                list(plan.classification_evidence),
            )
            self.assertEqual(
                report_item["classification_reason"],
                plan.classification_reason,
            )
