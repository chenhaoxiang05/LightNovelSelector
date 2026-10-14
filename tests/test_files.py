import unittest
import urllib.error

from lightnovel_selector.files import (
    decode_bytes,
    is_image_zip_member,
    resolve_zip_member,
    validate_https_url,
    xml_local_name,
)

class FilesTests(unittest.TestCase):
    def test_validate_https_url_valid(self):
        self.assertEqual(validate_https_url("https://example.com/api"), "https://example.com/api")
        self.assertEqual(validate_https_url("HTTPS://EXAMPLE.COM/API"), "HTTPS://EXAMPLE.COM/API")

    def test_validate_https_url_invalid_scheme(self):
        with self.assertRaisesRegex(ValueError, "仅允许访问不含登录信息的 HTTPS 地址"):
            validate_https_url("http://example.com")
        with self.assertRaisesRegex(ValueError, "仅允许访问不含登录信息的 HTTPS 地址"):
            validate_https_url("ftp://example.com")

    def test_validate_https_url_invalid_format(self):
        with self.assertRaises(ValueError):
            validate_https_url("")
        with self.assertRaises(ValueError):
            validate_https_url("   ")

    def test_validate_https_url_local_addresses(self):
        with self.assertRaisesRegex(ValueError, "不允许访问本机或内部网络地址"):
            validate_https_url("https://localhost")
        with self.assertRaisesRegex(ValueError, "不允许访问本机或内部网络地址"):
            validate_https_url("https://127.0.0.1")
        with self.assertRaisesRegex(ValueError, "不允许访问本机或内部网络地址"):
            validate_https_url("https://192.168.1.1")
        with self.assertRaisesRegex(ValueError, "不允许访问本机或内部网络地址"):
            validate_https_url("https://10.0.0.1")
        with self.assertRaisesRegex(ValueError, "不允许访问本机或内部网络地址"):
            validate_https_url("https://example.local")

    def test_validate_https_url_credentials(self):
        with self.assertRaisesRegex(ValueError, "仅允许访问不含登录信息的 HTTPS 地址"):
            validate_https_url("https://user:pass@example.com")

    def test_xml_local_name(self):
        self.assertEqual(xml_local_name("tag"), "tag")
        self.assertEqual(xml_local_name("{http://www.w3.org/1999/xhtml}html"), "html")
        self.assertEqual(xml_local_name("{namespace}element"), "element")

    def test_is_image_zip_member(self):
        self.assertTrue(is_image_zip_member("cover.jpg"))
        self.assertTrue(is_image_zip_member("images/cover.PNG"))
        self.assertTrue(is_image_zip_member("folder/image.webp"))
        self.assertFalse(is_image_zip_member("document.txt"))
        self.assertFalse(is_image_zip_member("images/"))
        self.assertFalse(is_image_zip_member("cover.jpg/"))

    def test_resolve_zip_member(self):
        self.assertEqual(resolve_zip_member("OEBPS/content.opf", "images/cover.jpg"), "OEBPS/images/cover.jpg")
        self.assertEqual(resolve_zip_member("content.opf", "cover.jpg"), "cover.jpg")
        self.assertEqual(resolve_zip_member("OEBPS/content.opf", "../cover.jpg"), "cover.jpg")
        self.assertEqual(resolve_zip_member("OEBPS/content.opf", "/images/cover.jpg"), "images/cover.jpg")

    def test_decode_bytes(self):
        self.assertEqual(decode_bytes(b"hello world"), "hello world")
        self.assertEqual(decode_bytes("你好".encode("utf-8")), "你好")
        self.assertEqual(decode_bytes("你好".encode("gb18030")), "你好")

        # Test fallback (ignore errors)
        invalid_bytes = b"\xff\xfe\x00"
        self.assertEqual(decode_bytes(invalid_bytes), "\x00")

if __name__ == "__main__":
    unittest.main()
