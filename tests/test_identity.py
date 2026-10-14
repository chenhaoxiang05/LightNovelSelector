import unittest

from lightnovel_selector.constants import IDENTITY_VALUE_MAX_CHARS
from lightnovel_selector.identity import (
    identity_from_filename,
    language_display_name,
    merge_book_identities,
    merge_classification_candidates,
    normalize_identity_values,
    volume_display_name,
    with_series_name,
)
from lightnovel_selector.models import BookIdentity, ClassificationCandidate


class TestNormalizeIdentityValues(unittest.TestCase):
    def test_normalize_generic_values(self):
        values = ["  Tag1 ", "tag2", "TAG1", " tag3 ", 123, None]
        normalized = normalize_identity_values(values, limit=5, kind="generic")
        self.assertEqual(normalized, ("Tag1", "tag2", "tag3"))

    def test_normalize_author_values(self):
        # author normalization should normalize names
        values = ["Author 1", "author 1", "Author 2", ""]
        normalized = normalize_identity_values(values, limit=5, kind="author")
        self.assertEqual(normalized, ("Author 1", "Author 2"))

    def test_respects_limit(self):
        values = ["tag1", "tag2", "tag3", "tag4", "tag5"]
        normalized = normalize_identity_values(values, limit=3)
        self.assertEqual(normalized, ("tag1", "tag2", "tag3"))

    def test_empty_input(self):
        self.assertEqual(normalize_identity_values([], limit=10), ())

    def test_truncates_long_values(self):
        long_val = "a" * (IDENTITY_VALUE_MAX_CHARS + 10)
        normalized = normalize_identity_values([long_val], limit=1)
        self.assertEqual(len(normalized[0]), IDENTITY_VALUE_MAX_CHARS)
        self.assertTrue(normalized[0].startswith("a" * IDENTITY_VALUE_MAX_CHARS))


class TestIdentityFromFilename(unittest.TestCase):
    def test_extracts_identity(self):
        filename = "[Author Name] Series Title v02 (zh-Hans)"
        identity = identity_from_filename(filename)
        # Assuming safe_folder_name(extract_series_guess(...)) gives '[Author Name] Series Title' for now since series_guess keeps it.
        # Let's write tests to verify exact current behaviour.
        self.assertEqual(identity.volume_number, 2)
        # title extraction: `extract_book_lookup_query` cleans tags and noise
        self.assertTrue(isinstance(identity.title, str))
        self.assertTrue(isinstance(identity.series_name, str))
        self.assertEqual(identity.language, "zh-Hans")

    def test_extracts_identity_with_hint(self):
        filename = "Series Title v02"
        identity = identity_from_filename(filename, hint="zh-Hant")
        self.assertEqual(identity.language, "zh-Hant")

class TestMergeBookIdentities(unittest.TestCase):
    def test_merges_with_resolved_candidate(self):
        local = BookIdentity(title="Local Title", series_name="Local Series", authors=("Author 1",), volume_number=1, language="zh", tags=("Tag 1",))
        resolved = BookIdentity(title="Resolved Title", series_name="Resolved Series", authors=("Author 2",), volume_number=2, language="ja", tags=("Tag 2",))

        merged = merge_book_identities(local, resolved)

        # Local base values are preserved for core identity, but empty ones get filled,
        # and lists are merged.
        # Actually according to the code:
        # title = candidate.title or title (resolved overrides if exists)
        # series = candidate.series_name or series (resolved overrides if exists)
        # volume_number = candidate.volume_number if candidate.volume_number is not None else volume_number
        # language = language or candidate.language (local overrides if exists)
        self.assertEqual(merged.title, "Resolved Title")
        self.assertEqual(merged.series_name, "Resolved Series")
        self.assertEqual(merged.volume_number, 2)
        self.assertEqual(merged.language, "zh") # local has "zh", language = language or candidate.language
        self.assertEqual(merged.authors, ("Author 2", "Author 1"))
        self.assertEqual(merged.tags, ("Tag 2", "Tag 1"))

    def test_merges_with_multiple_candidates(self):
        local = BookIdentity(title="Local Title", series_name="Local Series", volume_number=1)
        res1 = BookIdentity(title="Res 1", series_name="Res 1 Series", volume_number=None, language="en")
        res2 = BookIdentity(title="", series_name="", volume_number=3)

        merged = merge_book_identities(local, res1, res2)
        self.assertEqual(merged.title, "Res 1")
        self.assertEqual(merged.volume_number, 3)
        self.assertEqual(merged.language, "en")

    def test_merges_with_none_candidates(self):
        local = BookIdentity(title="Local Title", series_name="Local Series", volume_number=1)
        merged = merge_book_identities(local, None)
        self.assertEqual(merged.title, "Local Title")
        self.assertEqual(merged.series_name, "Local Series")
        self.assertEqual(merged.volume_number, 1)

    def test_merges_with_series_name_override(self):
        local = BookIdentity(title="Local Title", series_name="Local Series", volume_number=1)
        merged = merge_book_identities(local, series_name="Override Series")
        self.assertEqual(merged.series_name, "Override Series")


class TestWithSeriesName(unittest.TestCase):
    def test_updates_series_name_with_safe_folder(self):
        identity = BookIdentity(title="Title", series_name="Old Series")
        updated = with_series_name(identity, "New Series: Name?")
        self.assertEqual(updated.series_name, "New Series_ Name_")
        self.assertEqual(updated.title, "Title")

class TestMergeClassificationCandidates(unittest.TestCase):
    def test_deduplicates_by_series_name_and_keeps_highest_confidence(self):
        c1 = ClassificationCandidate(identity=BookIdentity(title="T1", series_name="Series A"), source="s1", confidence=0.5)
        c2 = ClassificationCandidate(identity=BookIdentity(title="T2", series_name="Series A"), source="s2", confidence=0.8)
        c3 = ClassificationCandidate(identity=BookIdentity(title="T3", series_name="Series B"), source="s3", confidence=0.6)

        merged = merge_classification_candidates([c1, c3], [c2])
        self.assertEqual(len(merged), 2)

        # Series A should be c2 (0.8 confidence)
        series_a_candidate = next(c for c in merged if c.identity.series_name == "Series A")
        self.assertEqual(series_a_candidate.confidence, 0.8)
        self.assertEqual(series_a_candidate.source, "s2")

    def test_skips_empty_series_name_key(self):
        c1 = ClassificationCandidate(identity=BookIdentity(title="T1", series_name=""), source="s1", confidence=0.5)
        merged = merge_classification_candidates([c1])
        self.assertEqual(len(merged), 0)

    def test_respects_max_count(self):
        from lightnovel_selector.constants import CLASSIFICATION_CANDIDATE_MAX_COUNT
        candidates = [
            ClassificationCandidate(identity=BookIdentity(title=f"T{i}", series_name=f"Series {i}"), source="s1", confidence=0.5)
            for i in range(CLASSIFICATION_CANDIDATE_MAX_COUNT + 5)
        ]
        merged = merge_classification_candidates(candidates)
        self.assertEqual(len(merged), CLASSIFICATION_CANDIDATE_MAX_COUNT)


class TestDisplayNames(unittest.TestCase):
    def test_language_display_name(self):
        self.assertEqual(language_display_name("zh-Hans"), "简体中文")
        self.assertEqual(language_display_name("ja"), "日语")
        self.assertEqual(language_display_name("unknown"), "unknown")
        self.assertEqual(language_display_name(None), "未识别")

    def test_volume_display_name(self):
        self.assertEqual(volume_display_name(1), "第 1 卷")
        self.assertEqual(volume_display_name(0), "第 0 卷")
        self.assertEqual(volume_display_name(None), "未识别")

if __name__ == "__main__":
    unittest.main()
