import tempfile
import unittest
from pathlib import Path

from lightnovel_selector.corrections import (
    RecognitionCorrectionMemory,
    correction_aliases_for_plan,
    series_alias_key,
)
from lightnovel_selector.models import ClassificationPlan


class CorrectionAliasKeyTests(unittest.TestCase):
    def test_series_alias_key_handles_valid_strings(self) -> None:
        self.assertEqual(series_alias_key("Project Aurora"), "projectaurora")
        self.assertEqual(series_alias_key("  Project  Aurora  "), "projectaurora")
        self.assertEqual(series_alias_key("星界旅人 第十二卷"), "星界旅人")

    def test_series_alias_key_returns_empty_for_invalid_strings(self) -> None:
        self.assertEqual(series_alias_key(""), "")
        self.assertEqual(series_alias_key("  "), "")
        self.assertEqual(series_alias_key("A"), "")  # Too short
        self.assertEqual(series_alias_key("123"), "")  # Decimal


class CorrectionMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.memory_path = Path(self.temp_dir.name) / "memory.json"
        self.memory = RecognitionCorrectionMemory(path=self.memory_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_remember_and_lookup(self) -> None:
        aliases = ("Aurora Project", "project aurora")  # "project aurora" shares same key as canonical "Project Aurora"
        canonical = "Project Aurora"

        changed = self.memory.remember(aliases, canonical)
        self.assertEqual(
            changed, 1
        )  # Only "Aurora Project" is added, "project aurora" is ignored because it has the same key as canonical
        self.assertEqual(self.memory.count, 1)

        # Exact match
        result = self.memory.lookup("Aurora Project")
        self.assertIsNotNone(result)
        if result:
            self.assertEqual(result.canonical_series, canonical)
            self.assertEqual(result.alias, "Aurora Project")

        # Different alias format but same key
        result2 = self.memory.lookup(" aurora  project ")
        self.assertIsNotNone(result2)
        if result2:
            self.assertEqual(result2.canonical_series, canonical)

    def test_lookup_returns_none_if_not_found(self) -> None:
        result = self.memory.lookup("Unknown Series")
        self.assertIsNone(result)
        result2 = self.memory.lookup(None, "Another Unknown")
        self.assertIsNone(result2)

    def test_remember_ignores_canonical_name_as_alias(self) -> None:
        aliases = ("Project Aurora", "Another Alias")
        canonical = "Project Aurora"
        changed = self.memory.remember(aliases, canonical)
        self.assertEqual(changed, 1)  # Only "Another Alias" should be added
        self.assertEqual(self.memory.count, 1)
        self.assertIsNone(self.memory.lookup("Project Aurora"))

    def test_clear_removes_all_entries(self) -> None:
        self.memory.remember(("Alias1", "Alias2"), "Canonical")
        self.assertEqual(self.memory.count, 2)

        self.memory.clear()
        self.assertEqual(self.memory.count, 0)
        self.assertIsNone(self.memory.lookup("Alias1"))

    def test_correction_aliases_for_plan(self) -> None:
        plan = ClassificationPlan(
            source_path=Path("dummy/path/Project Aurora Vol.03.epub"),
            series_name="Project Aurora Series",
            target_dir=Path("dummy/target"),
            target_path=Path("dummy/target/Project Aurora Vol.03.epub"),
            metadata_title="Project Aurora 3",
        )
        aliases = correction_aliases_for_plan(plan)
        # series_name, source_path.name, identity.title -> "Project Aurora Series", "Project Aurora Vol.03.epub", "Project Aurora 3"
        # After extraction:
        # "Project Aurora Series" -> "Project Aurora Series"
        # "Project Aurora Vol.03.epub" -> "Project Aurora"
        # "Project Aurora 3" -> "Project Aurora"
        # The key for the last two is the same, so only 2 aliases are returned.
        self.assertEqual(len(aliases), 2)
        self.assertIn("Project Aurora Series", aliases)
        self.assertIn("Project Aurora", aliases)

    def test_load_and_payload(self) -> None:
        import json

        now = "2023-01-01T00:00:00+00:00"
        with open(self.memory_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": 1,
                    "entries": [{"alias": "Aurora Proj", "canonical_series": "Project Aurora", "updated_at": now}],
                },
                f,
            )

        mem = RecognitionCorrectionMemory(self.memory_path)
        self.assertEqual(mem.count, 1)
        res = mem.lookup("Aurora Proj")
        self.assertIsNotNone(res)
        if res:
            self.assertEqual(res.canonical_series, "Project Aurora")
            self.assertEqual(res.alias, "Aurora Proj")
            self.assertEqual(res.updated_at, now)

    def test_remember_plans_and_try_remember_plans(self) -> None:
        plan = ClassificationPlan(
            source_path=Path("dummy/path/Project Aurora Vol.03.epub"),
            series_name="Aurora Proj",
            target_dir=Path("dummy/target"),
            target_path=Path("dummy/target/Project Aurora Vol.03.epub"),
        )
        canonical = "Project Aurora"

        changed = self.memory.remember_plans((plan,), canonical)
        # correction_aliases_for_plan returns ('Aurora Proj', 'Project Aurora')
        # 'Project Aurora' has the same key as canonical 'Project Aurora', so it is ignored.
        self.assertEqual(changed, 1)  # only "Aurora Proj"

        self.memory.clear()

        changed2, exc = self.memory.try_remember_plans((plan,), canonical)
        self.assertEqual(changed2, 1)
        self.assertIsNone(exc)


if __name__ == "__main__":
    unittest.main()
