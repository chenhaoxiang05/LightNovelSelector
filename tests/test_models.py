import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from lightnovel_selector.models import (
    BookIdentity,
    BookMetadata,
    ClassificationPlan,
    ResolveResult,
)


class TestModels(unittest.TestCase):
    def test_book_identity_required_fields(self):
        identity = BookIdentity(title="Title", series_name="Series")
        self.assertEqual(identity.title, "Title")
        self.assertEqual(identity.series_name, "Series")
        self.assertEqual(identity.authors, ())
        self.assertIsNone(identity.volume_number)
        self.assertIsNone(identity.language)
        self.assertEqual(identity.tags, ())

    def test_book_identity_all_fields(self):
        identity = BookIdentity(
            title="Title",
            series_name="Series",
            authors=("Author1", "Author2"),
            volume_number=1,
            language="zh-Hans",
            tags=("Tag1", "Tag2"),
        )
        self.assertEqual(identity.title, "Title")
        self.assertEqual(identity.series_name, "Series")
        self.assertEqual(identity.authors, ("Author1", "Author2"))
        self.assertEqual(identity.volume_number, 1)
        self.assertEqual(identity.language, "zh-Hans")
        self.assertEqual(identity.tags, ("Tag1", "Tag2"))

    def test_book_identity_is_frozen(self):
        identity = BookIdentity(title="Title", series_name="Series")
        with self.assertRaises(FrozenInstanceError):
            identity.title = "New Title"

    def test_resolve_result_with_identity(self):
        identity = BookIdentity(title="Title", series_name="Series")
        result = ResolveResult(identity=identity, source="Source", confidence=0.9, local_guess="Local")
        self.assertEqual(result.identity, identity)
        self.assertEqual(result.source, "Source")
        self.assertEqual(result.confidence, 0.9)
        self.assertEqual(result.local_guess, "Local")
        self.assertEqual(result.series_name, "Series")
        self.assertEqual(result.metadata_title, "Title")

    def test_resolve_result_with_series_name(self):
        result = ResolveResult(
            series_name="Series",
            metadata_title="Metadata Title",
            source="Source",
            confidence=0.9,
            local_guess="Local"
        )
        self.assertEqual(result.identity.title, "Metadata Title")
        self.assertEqual(result.identity.series_name, "Series")
        self.assertEqual(result.source, "Source")
        self.assertEqual(result.confidence, 0.9)
        self.assertEqual(result.local_guess, "Local")

    def test_resolve_result_with_series_name_fallback_title(self):
        result = ResolveResult(
            series_name="Series",
            source="Source",
            confidence=0.9,
            local_guess="Local"
        )
        self.assertEqual(result.identity.title, "Series")
        self.assertEqual(result.identity.series_name, "Series")

    def test_resolve_result_with_identity_and_series_name_override(self):
        identity = BookIdentity(title="Title", series_name="Old Series")
        result = ResolveResult(identity=identity, series_name="New Series")
        self.assertEqual(result.identity.title, "Title")
        self.assertEqual(result.identity.series_name, "New Series")

    def test_resolve_result_missing_identity_and_series_name(self):
        with self.assertRaisesRegex(TypeError, "ResolveResult 需要 identity 或 series_name。"):
            ResolveResult()

    def test_book_metadata_with_identity(self):
        identity = BookIdentity(title="Title", series_name="Series")
        metadata = BookMetadata(identity=identity, source="Source", confidence=0.9, query="Query")
        self.assertEqual(metadata.identity, identity)
        self.assertEqual(metadata.source, "Source")
        self.assertEqual(metadata.confidence, 0.9)
        self.assertEqual(metadata.query, "Query")
        self.assertEqual(metadata.title, "Title")

    def test_book_metadata_with_title(self):
        metadata = BookMetadata(title="Title", source="Source", confidence=0.9, query="Query")
        self.assertEqual(metadata.identity.title, "Title")
        self.assertEqual(metadata.identity.series_name, "Title")
        self.assertEqual(metadata.source, "Source")
        self.assertEqual(metadata.confidence, 0.9)
        self.assertEqual(metadata.query, "Query")

    def test_book_metadata_with_identity_and_title_override(self):
        identity = BookIdentity(title="Old Title", series_name="Series")
        metadata = BookMetadata(identity=identity, title="New Title")
        self.assertEqual(metadata.identity.title, "New Title")
        self.assertEqual(metadata.identity.series_name, "Series")

    def test_book_metadata_missing_identity_and_title(self):
        with self.assertRaisesRegex(TypeError, "BookMetadata 需要 identity 或 title。"):
            BookMetadata()

    def test_classification_plan_with_identity(self):
        identity = BookIdentity(title="Title", series_name="Series")
        source_path = Path("source.txt")
        target_dir = Path("target_dir")
        target_path = Path("target_dir/target.txt")
        plan = ClassificationPlan(
            source_path=source_path,
            identity=identity,
            target_dir=target_dir,
            target_path=target_path
        )
        self.assertEqual(plan.source_path, source_path)
        self.assertEqual(plan.identity, identity)
        self.assertEqual(plan.target_dir, target_dir)
        self.assertEqual(plan.target_path, target_path)
        self.assertEqual(plan.series_name, "Series")
        self.assertEqual(plan.metadata_title, "Title")
        self.assertTrue(plan.will_move)

    def test_classification_plan_with_series_name(self):
        source_path = Path("source.txt")
        target_dir = Path("target_dir")
        target_path = Path("target_dir/target.txt")
        plan = ClassificationPlan(
            source_path=source_path,
            series_name="Series",
            metadata_title="Metadata Title",
            target_dir=target_dir,
            target_path=target_path
        )
        self.assertEqual(plan.identity.title, "Metadata Title")
        self.assertEqual(plan.identity.series_name, "Series")

    def test_classification_plan_with_series_name_fallback_title(self):
        source_path = Path("source.txt")
        target_dir = Path("target_dir")
        target_path = Path("target_dir/target.txt")
        plan = ClassificationPlan(
            source_path=source_path,
            series_name="Series",
            target_dir=target_dir,
            target_path=target_path
        )
        self.assertEqual(plan.identity.title, "source") # source_path.stem
        self.assertEqual(plan.identity.series_name, "Series")

    def test_classification_plan_with_identity_and_series_name_override(self):
        identity = BookIdentity(title="Title", series_name="Old Series")
        source_path = Path("source.txt")
        target_dir = Path("target_dir")
        target_path = Path("target_dir/target.txt")
        plan = ClassificationPlan(
            source_path=source_path,
            identity=identity,
            series_name="New Series",
            target_dir=target_dir,
            target_path=target_path
        )
        self.assertEqual(plan.identity.title, "Title")
        self.assertEqual(plan.identity.series_name, "New Series")

    def test_classification_plan_missing_target_dir(self):
        identity = BookIdentity(title="Title", series_name="Series")
        with self.assertRaisesRegex(TypeError, "ClassificationPlan 需要 target_dir 和 target_path。"):
            ClassificationPlan(source_path=Path("source.txt"), identity=identity, target_path=Path("target.txt"))

    def test_classification_plan_missing_target_path(self):
        identity = BookIdentity(title="Title", series_name="Series")
        with self.assertRaisesRegex(TypeError, "ClassificationPlan 需要 target_dir 和 target_path。"):
            ClassificationPlan(source_path=Path("source.txt"), identity=identity, target_dir=Path("target_dir"))

    def test_classification_plan_missing_identity_and_series_name(self):
        with self.assertRaisesRegex(TypeError, "ClassificationPlan 需要 identity 或 series_name。"):
            ClassificationPlan(
                source_path=Path("source.txt"),
                target_dir=Path("target_dir"),
                target_path=Path("target_dir/target.txt")
            )

    def test_classification_plan_will_move_false_status(self):
        identity = BookIdentity(title="Title", series_name="Series")
        plan = ClassificationPlan(
            source_path=Path("source.txt"),
            identity=identity,
            target_dir=Path("target_dir"),
            target_path=Path("target_dir/target.txt"),
            status="duplicate"
        )
        self.assertFalse(plan.will_move)

    def test_classification_plan_will_move_false_same_path(self):
        identity = BookIdentity(title="Title", series_name="Series")
        plan = ClassificationPlan(
            source_path=Path("source.txt"),
            identity=identity,
            target_dir=Path("."),
            target_path=Path("source.txt")
        )
        self.assertFalse(plan.will_move)

if __name__ == "__main__":
    unittest.main()
