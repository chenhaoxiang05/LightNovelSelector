import unittest

from lightnovel_selector.parsing import contains_cjk


class TestParsing(unittest.TestCase):
    def test_contains_cjk(self) -> None:
        # Exclusively English
        self.assertFalse(contains_cjk("Hello world!"))
        self.assertFalse(contains_cjk("Light Novel Vol 1"))

        # Numbers and symbols only
        self.assertFalse(contains_cjk("1234567890!@#$%^&*()"))

        # Empty string
        self.assertFalse(contains_cjk(""))

        # Mixed English and CJK
        self.assertTrue(contains_cjk("Hello 世界!"))
        self.assertTrue(contains_cjk("This is a 測試."))
        self.assertTrue(contains_cjk("Volume 1 第1巻"))

        # Exclusively CJK
        # Chinese (Han characters)
        self.assertTrue(contains_cjk("你好，世界！"))
        self.assertTrue(contains_cjk("測試"))
        # Japanese (Hiragana/Katakana)
        self.assertTrue(contains_cjk("こんにちは世界"))
        self.assertTrue(contains_cjk("コンニチハ"))
        self.assertTrue(contains_cjk("ライトノベル"))
        # Korean (Hangul)
        self.assertTrue(contains_cjk("안녕하세요"))
        self.assertTrue(contains_cjk("라이트 노벨"))

if __name__ == "__main__":
    unittest.main()
