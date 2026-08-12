import unittest

from lightnovel_selector.corrections import series_alias_key
from lightnovel_selector.parsing import (
    clean_file_stem,
    collapse_spaces,
    contains_cjk,
    extract_book_lookup_query,
    extract_series_guess,
    is_noise_tag,
    normalize_title_text,
    parse_volume_number,
)


class TextNormalizationTests(unittest.TestCase):
    def test_collapses_unicode_whitespace(self) -> None:
        self.assertEqual(collapse_spaces("  Project\tAurora\n 03  "), "Project Aurora 03")

    def test_normalizes_width_punctuation_and_unsafe_controls(self) -> None:
        self.assertEqual(normalize_title_text("\u202eＰｒｏｊｅｃｔ　Ａ—03"), "Project A-03")

    def test_detects_cjk_scripts_without_marking_latin_text(self) -> None:
        for value in ("星界旅人", "星界の旅人", "별의 여행자"):
            with self.subTest(value=value):
                self.assertTrue(contains_cjk(value))
        self.assertFalse(contains_cjk("Project Aurora 03"))

    def test_noise_tags_respect_numeric_position(self) -> None:
        self.assertTrue(is_noise_tag("EPUB", position="leading"))
        self.assertTrue(is_noise_tag("03", position="trailing"))
        self.assertFalse(is_noise_tag("03", position="leading"))
        self.assertFalse(is_noise_tag("Project Aurora", position="trailing"))


class FilenameParsingContractTests(unittest.TestCase):
    def tearDown(self) -> None:
        extract_book_lookup_query.cache_clear()
        extract_series_guess.cache_clear()

    def test_only_strips_supported_novel_extensions(self) -> None:
        self.assertEqual(clean_file_stem("Project Aurora Vol.03"), "Project Aurora Vol 03")
        self.assertEqual(clean_file_stem("Project Aurora Vol.03.epub"), "Project Aurora Vol 03")
        self.assertEqual(clean_file_stem("Project Aurora Vol.03.backup"), "Project Aurora Vol 03 backup")

    def test_decimal_volume_suffix_is_not_mistaken_for_an_extension(self) -> None:
        for value in ("Project Aurora Vol.03", "Project Aurora Vol.03.epub"):
            with self.subTest(value=value):
                self.assertEqual(parse_volume_number(value), 3)
                self.assertEqual(extract_series_guess(value), "Project Aurora")
                self.assertEqual(series_alias_key(value), "projectaurora")

    def test_lookup_query_preserves_volume_evidence(self) -> None:
        self.assertEqual(extract_book_lookup_query("Project Aurora Vol.03"), "Project Aurora Vol 03")

    def test_volume_parser_handles_supported_notations(self) -> None:
        cases = {
            "星界旅人 第十二卷": 12,
            "Astral Traveler Vol. IV": 4,
            "Astral Traveler (007)": 7,
            "Project Aurora Vol. 3 / Side Story": 3,
            "Demo Vol.00.txt": 0,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(parse_volume_number(value), expected)

        for value in ("Civilization", "Astral Traveler Vol. IIX", "Project Aurora.backup"):
            with self.subTest(value=value):
                self.assertIsNone(parse_volume_number(value))


if __name__ == "__main__":
    unittest.main()
