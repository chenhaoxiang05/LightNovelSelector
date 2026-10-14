import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lightnovel_selector.models import AppSettings, CustomRule, MetadataProviderSetting
from lightnovel_selector.constants import METADATA_CACHE_TTL_SECONDS
from lightnovel_selector.storage import (
    PersistentMetadataCache,
    append_json_line_durable,
    app_settings_from_dict,
    app_settings_to_dict,
    load_app_settings,
    read_json_bounded,
    save_app_settings,
    try_save_app_settings,
    write_json_atomic,
    write_json_lines_exclusive,
)


class StorageIOTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.test_file = self.dir_path / "test_io.json"
        self.test_file_lines = self.dir_path / "test_lines.jsonl"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_write_and_read_json_atomic(self) -> None:
        payload = {"key": "value", "list": [1, 2, 3]}
        write_json_atomic(self.test_file, payload)
        self.assertTrue(self.test_file.exists())

        # Test read_json_bounded
        data = read_json_bounded(self.test_file, max_bytes=1024)
        self.assertEqual(data, payload)

    def test_read_json_bounded_exceeds_max_bytes(self) -> None:
        payload = {"key": "value"}
        write_json_atomic(self.test_file, payload)

        # Payload {"key":"value"} is ~14 bytes without formatting.
        # It's larger due to `indent=2` in `write_json_atomic` and a newline.
        # Set max_bytes to 5 to force it to return None.
        data = read_json_bounded(self.test_file, max_bytes=5)
        self.assertIsNone(data)

    def test_write_json_lines_exclusive_success(self) -> None:
        payloads = [{"id": 1}, {"id": 2}]
        write_json_lines_exclusive(self.test_file_lines, payloads)

        with self.test_file_lines.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), {"id": 1})
        self.assertEqual(json.loads(lines[1]), {"id": 2})

    def test_write_json_lines_exclusive_fails_if_exists(self) -> None:
        payloads = [{"id": 1}]
        write_json_lines_exclusive(self.test_file_lines, payloads)

        with self.assertRaises(FileExistsError):
            write_json_lines_exclusive(self.test_file_lines, payloads)

    def test_append_json_line_durable(self) -> None:
        # File must exist before appending
        write_json_lines_exclusive(self.test_file_lines, [{"initial": True}])

        payload = {"appended": True}
        append_json_line_durable(self.test_file_lines, payload, max_bytes=1024)

        with self.test_file_lines.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1]), payload)

    def test_append_json_line_durable_exceeds_max_bytes(self) -> None:
        write_json_lines_exclusive(self.test_file_lines, [{"initial": True}])

        # Test file size limit exceeded
        with self.assertRaises(OSError) as context:
            append_json_line_durable(self.test_file_lines, {"too": "big"}, max_bytes=10)

        self.assertIn("超过允许大小", str(context.exception))


class StorageSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_file = Path(self.temp_dir.name) / "settings.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_app_settings_schema_and_round_trip(self) -> None:
        settings = AppSettings(
            use_network=False,
            recursive=True,
            auto_rename=True,
            custom_rules=(CustomRule(pattern="Rule1", series="Series1"),),
            provider_settings=(
                MetadataProviderSetting(provider_id="bangumi", enabled=True, priority=10),
            ),
            last_folder="C:\\Test",
        )
        payload = app_settings_to_dict(settings)

        self.assertEqual(payload["use_network"], False)
        self.assertEqual(payload["recursive"], True)
        self.assertEqual(payload["auto_rename"], True)
        self.assertEqual(payload["last_folder"], "C:\\Test")
        self.assertEqual(payload["custom_rules"][0]["pattern"], "Rule1")
        self.assertEqual(payload["provider_settings"][0]["provider_id"], "bangumi")

        parsed = app_settings_from_dict(payload)
        self.assertEqual(parsed, settings)

    def test_app_settings_defaults(self) -> None:
        # Empty payload should use defaults
        parsed = app_settings_from_dict({})
        self.assertEqual(parsed.use_network, True)
        self.assertEqual(parsed.recursive, False)
        self.assertEqual(parsed.auto_rename, False)
        self.assertEqual(len(parsed.custom_rules), 0)
        self.assertEqual(len(parsed.provider_settings), 0)
        self.assertEqual(parsed.last_folder, "")

    def test_load_save_app_settings(self) -> None:
        # Load from non-existent file gives default settings
        settings = load_app_settings(self.settings_file)
        self.assertIsInstance(settings, AppSettings)

        settings = AppSettings(last_folder="/new/path")
        save_app_settings(settings, self.settings_file)
        self.assertTrue(self.settings_file.exists())

        loaded = load_app_settings(self.settings_file)
        self.assertEqual(loaded.last_folder, "/new/path")

    def test_try_save_app_settings(self) -> None:
        settings = AppSettings(last_folder="/new/path")
        err = try_save_app_settings(settings, self.settings_file)
        self.assertIsNone(err)

        loaded = load_app_settings(self.settings_file)
        self.assertEqual(loaded.last_folder, "/new/path")


class PersistentMetadataCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = Path(self.temp_dir.name) / "cache.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_cache_set_and_get(self) -> None:
        cache = PersistentMetadataCache(path=self.cache_file)
        payload = {"data": "test"}

        cache.set("key1", payload)
        self.assertEqual(cache.get("key1"), payload)

        # Test reloading from file
        cache2 = PersistentMetadataCache(path=self.cache_file)
        self.assertEqual(cache2.get("key1"), payload)

    @patch("lightnovel_selector.storage.time.time")
    def test_cache_expiration(self, mock_time) -> None:
        mock_time.return_value = 1000.0

        cache = PersistentMetadataCache(path=self.cache_file)
        cache.set("key1", {"data": "test"})
        self.assertIsNotNone(cache.get("key1"))

        # Advance time beyond TTL
        mock_time.return_value = 1000.0 + METADATA_CACHE_TTL_SECONDS + 1
        self.assertIsNone(cache.get("key1"))

    def test_cache_pruning_on_load(self) -> None:
        # Pre-populate cache with invalid/expired data directly
        expired_data = {
            "version": 1,
            "entries": {
                "key_expired": {"cached_at": 10.0, "payload": {"a": 1}},
                "key_invalid": {"cached_at": "invalid", "payload": {"a": 1}},
                "key_no_payload": {"cached_at": 10000000000.0},
            }
        }
        write_json_atomic(self.cache_file, expired_data)

        cache = PersistentMetadataCache(path=self.cache_file)
        # Should prune invalid/expired entries
        self.assertIsNone(cache.get("key_expired"))
        self.assertIsNone(cache.get("key_invalid"))
        self.assertIsNone(cache.get("key_no_payload"))
        self.assertEqual(len(cache.data.get("entries", {})), 0)


if __name__ == "__main__":
    unittest.main()
