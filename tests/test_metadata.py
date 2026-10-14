import unittest
from pathlib import Path

from lightnovel_selector.models import BookIdentity, BookMetadata
from lightnovel_selector.metadata import suggest_renamed_filename


class MetadataTests(unittest.TestCase):
    def test_volume_number_from_identity(self) -> None:
        metadata = BookMetadata(
            identity=BookIdentity(
                title="Demo Book",
                series_name="Demo",
                volume_number=5,
            ),
            source="Test",
            confidence=1.0,
            query="",
        )
        self.assertEqual(
            suggest_renamed_filename(
                Path("any.epub"),
                series_name="Series",
                metadata=metadata,
                identity_query="",
            ),
            "Series 第05卷.epub",
        )

    def test_volume_number_from_metadata_query(self) -> None:
        metadata = BookMetadata(
            identity=BookIdentity(
                title="Demo Book",
                series_name="Demo",
            ),
            source="Test",
            confidence=1.0,
            query="Demo Vol.03",
        )
        self.assertEqual(
            suggest_renamed_filename(
                Path("any.epub"),
                series_name="Series",
                metadata=metadata,
                identity_query="",
            ),
            "Series 第03卷.epub",
        )

    def test_volume_number_from_identity_query(self) -> None:
        self.assertEqual(
            suggest_renamed_filename(
                Path("any.epub"),
                series_name="Series",
                metadata=None,
                identity_query="Demo Vol.02",
            ),
            "Series 第02卷.epub",
        )

    def test_volume_number_from_original_path_name(self) -> None:
        self.assertEqual(
            suggest_renamed_filename(
                Path("Demo Vol.08.epub"),
                series_name="Series",
                metadata=None,
                identity_query="",
            ),
            "Series 第08卷.epub",
        )

    def test_fallback_to_metadata_title(self) -> None:
        metadata = BookMetadata(
            identity=BookIdentity(
                title="Special Book Title",
                series_name="Demo",
            ),
            source="Test",
            confidence=1.0,
            query="Demo",
        )
        self.assertEqual(
            suggest_renamed_filename(
                Path("any.epub"),
                series_name="",
                metadata=metadata,
                identity_query="",
            ),
            "Special Book Title.epub",
        )

    def test_fallback_to_extract_series_guess(self) -> None:
        self.assertEqual(
            suggest_renamed_filename(
                Path("Sword.Art.Online.Aincrad.epub"),
                series_name="",
                metadata=None,
                identity_query="",
            ),
            "Sword Art Online Aincrad.epub",
        )
