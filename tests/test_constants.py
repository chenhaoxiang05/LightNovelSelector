import unittest

from lightnovel_selector import constants

class ConstantsTests(unittest.TestCase):
    def test_app_constants_are_valid(self) -> None:
        self.assertTrue(constants.APP_NAME)
        self.assertTrue(constants.APP_VERSION)
        self.assertTrue(constants.APP_VERSION in constants.USER_AGENT)
        self.assertTrue(constants.USER_AGENT.startswith("LightNovelSelector/"))

    def test_bangumi_constants(self) -> None:
        self.assertTrue(constants.BANGUMI_SEARCH_URL.startswith("https://"))
        self.assertTrue("{subject_id}" in constants.BANGUMI_SUBJECT_WEB_URL)
        self.assertGreater(constants.BANGUMI_SEARCH_LIMIT, 0)
        self.assertGreater(constants.BANGUMI_DETAIL_PAGES, 0)

    def test_local_cover_extensions(self) -> None:
        for ext in constants.LOCAL_COVER_EXTENSIONS:
            self.assertTrue(ext.startswith("."))
            self.assertEqual(ext, ext.lower())

    def test_metadata_cache_version(self) -> None:
        self.assertGreaterEqual(constants.METADATA_CACHE_VERSION, 1)
