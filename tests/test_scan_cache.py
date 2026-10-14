import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from lightnovel_selector.scan_cache import (
    FileSnapshot,
    PersistentScanCache,
    LocalFileAnalysis,
    _valid_fingerprint,
    capture_file_snapshot,
)
from lightnovel_selector.models import BookIdentity


class ScanCacheTests(unittest.TestCase):
    def test_file_snapshot_to_from_dict(self) -> None:
        snapshot = FileSnapshot(
            size=1024,
            mtime_ns=1234567890,
            change_token=1,
            device=10,
            inode=20,
        )
        data = snapshot.to_dict()
        restored = FileSnapshot.from_dict(data)
        self.assertEqual(snapshot, restored)

    def test_file_snapshot_from_dict_invalid(self) -> None:
        self.assertIsNone(FileSnapshot.from_dict("not a dict"))
        self.assertIsNone(FileSnapshot.from_dict({"size": -1, "mtime_ns": 0, "change_token": None, "device": 0, "inode": 0}))
        self.assertIsNone(FileSnapshot.from_dict({"size": 1, "mtime_ns": "not an int", "change_token": None, "device": 0, "inode": 0}))
        self.assertIsNone(FileSnapshot.from_dict({"size": 1, "mtime_ns": 1, "change_token": "not an int", "device": 0, "inode": 0}))

    def test_persistent_scan_cache_quick_signature(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = root / "scan-cache.json"
            test_file = root / "test.txt"
            test_file.write_text("hello world")

            snapshot = capture_file_snapshot(test_file)
            signature = f"{snapshot.size}:{'0' * 64}"

            with PersistentScanCache(cache_path) as cache:
                self.assertIsNone(cache.get_quick_signature(test_file, snapshot))
                cache.remember_quick_signature(test_file, snapshot, signature)
                self.assertEqual(cache.get_quick_signature(test_file, snapshot), signature)

            # Reload to check persistence
            with PersistentScanCache(cache_path) as cache:
                self.assertEqual(cache.get_quick_signature(test_file, snapshot), signature)

    def test_persistent_scan_cache_fingerprint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = root / "scan-cache.json"
            test_file = root / "test.txt"
            test_file.write_text("hello world")

            snapshot = capture_file_snapshot(test_file)
            fingerprint = f"{snapshot.size}:{'1' * 64}"

            with PersistentScanCache(cache_path) as cache:
                self.assertIsNone(cache.get_fingerprint(test_file, snapshot))
                cache.remember_fingerprint(test_file, snapshot, fingerprint)
                self.assertEqual(cache.get_fingerprint(test_file, snapshot), fingerprint)

            # Reload to check persistence
            with PersistentScanCache(cache_path) as cache:
                self.assertEqual(cache.get_fingerprint(test_file, snapshot), fingerprint)

    def test_persistent_scan_cache_local_analysis(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = root / "scan-cache.json"
            test_file = root / "test.txt"
            test_file.write_text("hello world")

            snapshot = capture_file_snapshot(test_file)
            analysis = LocalFileAnalysis(
                identity=BookIdentity(title="Test Series Vol 1", series_name="Test Series", volume_number=1),
                identity_query="Test Series Vol 1",
                used_content_hint=False,
            )

            with PersistentScanCache(cache_path) as cache:
                self.assertIsNone(cache.get_local_analysis(test_file, snapshot))
                cache.remember_local_analysis(test_file, snapshot, analysis)
                retrieved = cache.get_local_analysis(test_file, snapshot)
                self.assertIsNotNone(retrieved)
                self.assertEqual(retrieved.identity, analysis.identity)
                self.assertEqual(retrieved.identity_query, analysis.identity_query)
                self.assertEqual(retrieved.used_content_hint, analysis.used_content_hint)

            # Reload to check persistence
            with PersistentScanCache(cache_path) as cache:
                retrieved = cache.get_local_analysis(test_file, snapshot)
                self.assertIsNotNone(retrieved)
                self.assertEqual(retrieved.identity, analysis.identity)

    def test_cache_invalidation_on_change(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = root / "scan-cache.json"
            test_file = root / "test.txt"
            test_file.write_text("hello world")

            snapshot1 = capture_file_snapshot(test_file)
            fingerprint = f"{snapshot1.size}:{'1' * 64}"

            with PersistentScanCache(cache_path) as cache:
                cache.remember_fingerprint(test_file, snapshot1, fingerprint)

            # Modify the file, let it sleep for 0.1 sec just to be sure mtime is changed
            time.sleep(0.1)
            test_file.write_text("hello world 2")
            snapshot2 = capture_file_snapshot(test_file)

            # The size actually increased here too, which means different size so validation fails right away
            # We want to be sure it invalidates even if size is the same but token/mtime is different
            test_file.write_text("hello world !")
            snapshot2 = capture_file_snapshot(test_file)

            with PersistentScanCache(cache_path) as cache:
                self.assertIsNone(cache.get_fingerprint(test_file, snapshot2))

    def test_invalid_fingerprint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = root / "scan-cache.json"
            test_file = root / "test.txt"
            test_file.write_text("hello")

            snapshot = capture_file_snapshot(test_file)

            with PersistentScanCache(cache_path) as cache:
                with self.assertRaisesRegex(ValueError, "快速签名格式无效"):
                    cache.remember_quick_signature(test_file, snapshot, "invalid")

                with self.assertRaisesRegex(ValueError, "完整文件指纹格式无效"):
                    cache.remember_fingerprint(test_file, snapshot, "invalid")

    def test_invalid_local_analysis(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = root / "scan-cache.json"
            test_file = root / "test.txt"
            test_file.write_text("hello")

            snapshot = capture_file_snapshot(test_file)
            analysis = LocalFileAnalysis(
                identity=BookIdentity(title="Test Series Vol 1", series_name="Test Series", volume_number=1),
                identity_query="", # Empty query should be invalid
                used_content_hint=False,
            )

            with PersistentScanCache(cache_path) as cache:
                with self.assertRaisesRegex(ValueError, "本地识别查询格式无效"):
                    cache.remember_local_analysis(test_file, snapshot, analysis)


if __name__ == "__main__":
    unittest.main()
