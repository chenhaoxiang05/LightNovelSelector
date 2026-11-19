import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lightnovel_selector.models import BookIdentity, BookMetadata, ResolveResult
from lightnovel_selector.storage import (
    app_data_dir,
    book_identity_from_dict,
    book_identity_to_dict,
    book_metadata_from_dict,
    book_metadata_to_dict,
    metadata_cache_path,
    resolve_result_from_dict,
    resolve_result_to_dict,
)


class PlatformStorageTests(unittest.TestCase):
    def test_new_install_and_existing_cli_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            locations = [
                ("darwin", "", home / "Library" / "Application Support"),
                ("linux", "relative", home / ".local" / "share"),
                ("linux", str(home / "xdg"), home / "xdg"),
            ]
            for platform, xdg, parent in locations:
                with (
                    self.subTest(platform=platform, xdg=xdg),
                    patch("lightnovel_selector.storage.sys.platform", platform),
                    patch.object(Path, "home", return_value=home),
                    patch.dict(os.environ, {"LOCALAPPDATA": "", "XDG_DATA_HOME": xdg}),
                ):
                    self.assertEqual(app_data_dir(), parent / "LightNovelSelector")
                    self.assertEqual(metadata_cache_path().parent, app_data_dir())
                    legacy = home / ".lightnovel_selector"
                    legacy.mkdir()
                    self.assertEqual(app_data_dir(), legacy)
                    legacy.rmdir()


class IdentityStorageContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = BookIdentity(
            title="Project Aurora Vol.03",
            series_name="Project Aurora",
            authors=("Example Author",),
            volume_number=3,
            language="en",
            tags=("Fantasy", "Adventure"),
        )

    def test_identity_schema_and_round_trip(self) -> None:
        payload = {
            "title": "Project Aurora Vol.03",
            "series_name": "Project Aurora",
            "authors": ["Example Author"],
            "volume_number": 3,
            "language": "en",
            "tags": ["Fantasy", "Adventure"],
        }
        self.assertEqual(book_identity_to_dict(self.identity), payload)
        self.assertEqual(book_identity_from_dict(payload), self.identity)

    def test_identity_rejects_malformed_fields(self) -> None:
        invalid_payloads: tuple[object, ...] = (
            None,
            {"title": ["Project Aurora"]},
            {"title": "Project Aurora", "authors": "Example Author"},
            {"title": "Project Aurora", "volume_number": True},
            {"title": "Project Aurora", "volume_number": 1000},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.assertIsNone(book_identity_from_dict(payload))


class MetadataStorageContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = BookIdentity(
            title="Project Aurora Vol.03",
            series_name="Project Aurora",
            authors=("Example Author",),
            volume_number=3,
            language="en",
            tags=("Fantasy",),
        )

    def test_metadata_schema_and_round_trip(self) -> None:
        metadata = BookMetadata(
            identity=self.identity,
            source="TestProvider",
            confidence=0.91,
            query="Project Aurora 03",
            summary="A test summary.",
            cover_url="https://example.test/cover.jpg",
            url="https://example.test/book/3",
        )
        payload = book_metadata_to_dict(metadata)

        self.assertEqual(
            set(payload),
            {
                "title",
                "series_name",
                "authors",
                "volume_number",
                "language",
                "tags",
                "identity",
                "source",
                "confidence",
                "query",
                "summary",
                "cover_url",
                "url",
            },
        )
        self.assertEqual(payload["identity"], book_identity_to_dict(self.identity))
        self.assertEqual(book_metadata_from_dict(payload), metadata)

    def test_metadata_rejects_invalid_required_values(self) -> None:
        invalid_payloads: tuple[dict[str, object], ...] = (
            {},
            {"title": ["Project Aurora"]},
            {"title": "Project Aurora", "confidence": "nan"},
            {"title": "Project Aurora", "identity": {"title": "Project Aurora", "authors": "invalid"}},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.assertIsNone(book_metadata_from_dict(payload))

    def test_resolve_result_schema_and_round_trip(self) -> None:
        result = ResolveResult(
            identity=self.identity,
            source="TestProvider",
            confidence=0.91,
            local_guess="Project Aurora",
            metadata_summary="A test summary.",
            metadata_cover_url="https://example.test/cover.jpg",
            metadata_url="https://example.test/book/3",
        )
        payload = {
            "series_name": "Project Aurora",
            "identity": book_identity_to_dict(self.identity),
            "source": "TestProvider",
            "confidence": 0.91,
            "local_guess": "Project Aurora",
            "metadata_title": "Project Aurora Vol.03",
            "metadata_summary": "A test summary.",
            "metadata_cover_url": "https://example.test/cover.jpg",
            "metadata_url": "https://example.test/book/3",
        }
        self.assertEqual(resolve_result_to_dict(result), payload)
        self.assertEqual(resolve_result_from_dict(payload), result)

    def test_resolve_result_supports_legacy_payload_and_rejects_invalid_data(self) -> None:
        legacy = resolve_result_from_dict(
            {
                "series_name": "Project Aurora",
                "metadata_title": "Project Aurora Vol.03",
                "confidence": 0.8,
            }
        )
        self.assertIsNotNone(legacy)
        assert legacy is not None
        self.assertEqual(legacy.identity.volume_number, 3)
        self.assertEqual(legacy.local_guess, "Project Aurora")

        invalid_payloads: tuple[dict[str, object], ...] = (
            {},
            {"series_name": []},
            {"series_name": "Project Aurora", "confidence": "nan"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.assertIsNone(resolve_result_from_dict(payload))


if __name__ == "__main__":
    unittest.main()
