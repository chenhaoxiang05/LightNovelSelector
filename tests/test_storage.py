import unittest
from lightnovel_selector.storage import resolve_result_from_dict
from lightnovel_selector.models import ResolveResult

class TestStorage(unittest.TestCase):
    def test_resolve_result_from_dict_success(self):
        data = {
            "series_name": "Test Series",
            "source": "Bangumi",
            "confidence": 0.9,
            "local_guess": "Test Series Guess",
            "metadata_title": "Test Metadata Title",
            "metadata_summary": "Test Summary",
            "metadata_cover_url": "http://example.com/cover.jpg",
            "metadata_url": "http://example.com/book",
            "identity": {
                "title": "Test Identity Title",
                "series_name": "Test Identity Series",
                "authors": ["Author A"],
                "volume_number": 1,
                "language": "zh",
                "tags": ["Tag1"]
            }
        }
        result = resolve_result_from_dict(data)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, ResolveResult)
        self.assertEqual(result.identity.title, "Test Identity Title")
        self.assertEqual(result.identity.series_name, "Test Identity Series")
        self.assertEqual(result.source, "Bangumi")
        self.assertEqual(result.confidence, 0.9)
        self.assertEqual(result.local_guess, "Test Series Guess")
        self.assertEqual(result.metadata_summary, "Test Summary")
        self.assertEqual(result.metadata_cover_url, "http://example.com/cover.jpg")
        self.assertEqual(result.metadata_url, "http://example.com/book")

        # Test default values for identity
        data_no_identity = {
            "series_name": "Test Series No Identity"
        }
        result2 = resolve_result_from_dict(data_no_identity)
        self.assertIsNotNone(result2)
        self.assertEqual(result2.identity.title, "Test Series No Identity")
        self.assertEqual(result2.identity.series_name, "Test Series No Identity")
        self.assertEqual(result2.source, "缓存")
        self.assertEqual(result2.confidence, 0.0)

    def test_resolve_result_from_dict_errors(self):
        # Missing series_name (KeyError)
        self.assertIsNone(resolve_result_from_dict({}))

        # Invalid series_name type (TypeError in _required_text)
        self.assertIsNone(resolve_result_from_dict({"series_name": 123}))

        # Empty series_name (ValueError in _required_text)
        self.assertIsNone(resolve_result_from_dict({"series_name": "  "}))

        # Let's hit the `if identity is None: return None` branch
        # identity becomes None if book_identity_from_dict returns None
        # book_identity_from_dict returns None if data is not a dict or if _required_text throws
        # if identity_payload is a dict and its 'title' throws ValueError (e.g. empty) AND fallback_title is empty
        self.assertIsNone(resolve_result_from_dict({
            "series_name": "Valid Series",
            "metadata_title": "   ",
            "identity": {"title": "   ", "series_name": "   "}
        }))

        # Invalid confidence type
        self.assertIsNone(resolve_result_from_dict({"series_name": "Valid", "confidence": "not-a-number"}))

        # Invalid local_guess type
        self.assertIsNone(resolve_result_from_dict({"series_name": "Valid", "local_guess": 123}))

if __name__ == '__main__':
    unittest.main()
