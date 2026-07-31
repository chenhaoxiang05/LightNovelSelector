import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lightnovel_selector import (
    AppSettings,
    OperationCancelled,
    PersistentScanCache,
    RecognitionCorrectionMemory,
    ScanSession,
)


class ScanSessionTests(unittest.TestCase):
    def test_session_reports_progress_without_owning_worker_thread(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Demo.Series.Vol.01.txt").write_text("volume one", encoding="utf-8")
            messages: list[str] = []
            progress: list[tuple[int, int]] = []
            session = ScanSession(
                root,
                AppSettings(use_network=False),
                metadata_providers=(),
                correction_memory=RecognitionCorrectionMemory(root / "aliases.json"),
                cancel_event=threading.Event(),
                on_message=messages.append,
                on_progress=lambda done, total: progress.append((done, total)),
                scan_cache_factory=lambda: PersistentScanCache(root / "scan-cache.json"),
            )

            result = session.run()

            self.assertEqual(len(result.plans), 1)
            self.assertEqual(result.plans[0].series_name, "Demo Series")
            self.assertTrue(messages)
            self.assertEqual(progress[-1], (1, 1))
            self.assertEqual(result.cache_stats, session.cache_stats)

    def test_session_honors_cancellation_before_file_analysis(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Demo.Series.Vol.01.txt").write_text("volume one", encoding="utf-8")
            cancel_event = threading.Event()
            cancel_event.set()
            session = ScanSession(
                root,
                AppSettings(use_network=False),
                metadata_providers=(),
                correction_memory=RecognitionCorrectionMemory(root / "aliases.json"),
                cancel_event=cancel_event,
                scan_cache_factory=lambda: PersistentScanCache(root / "scan-cache.json"),
            )

            with self.assertRaisesRegex(OperationCancelled, "扫描已取消"):
                session.run()

            self.assertEqual(session.cache_stats.reused_files, 0)

    def test_cache_initialization_failure_is_a_non_blocking_warning(self) -> None:
        def unavailable_cache() -> PersistentScanCache:
            raise OSError("cache unavailable")

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Demo.Series.Vol.01.txt").write_text("volume one", encoding="utf-8")
            session = ScanSession(
                root,
                AppSettings(use_network=False),
                metadata_providers=(),
                correction_memory=RecognitionCorrectionMemory(root / "aliases.json"),
                cancel_event=threading.Event(),
                scan_cache_factory=unavailable_cache,
            )

            result = session.run()

            self.assertEqual(len(result.plans), 1)
            self.assertEqual(result.cache_stats.write_warning, "cache unavailable")


if __name__ == "__main__":
    unittest.main()
