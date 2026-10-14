import unittest

import lightnovel_selector.classification as classification


class ClassificationFacadeTests(unittest.TestCase):
    def test_all_exports_are_available_and_sorted(self) -> None:
        expected = [
            "build_classification_plan",
            "classification_plan_group_indices",
            "classification_plan_to_report_item",
            "classification_report_root",
            "count_plan_statuses",
            "execute_classification_plan",
            "find_novel_files",
            "load_classification_report",
            "plan_status_label",
            "revise_classification_plan",
            "revise_classification_plans",
            "undo_classification_report",
            "unique_target_path",
            "validate_classification_root",
            "write_classification_report",
        ]

        # Verify the __all__ list exactly matches our expectation
        self.assertEqual(classification.__all__, expected)

        # Verify __all__ is sorted alphabetically
        self.assertEqual(classification.__all__, sorted(classification.__all__))

        # Verify every item in __all__ can be accessed as an attribute
        for item in classification.__all__:
            self.assertTrue(hasattr(classification, item), f"Missing expected export: {item}")

    def test_no_extra_public_exports(self) -> None:
        # Verify that all public (non-underscore) attributes of the module are in __all__
        public_attrs = [
            attr for attr in dir(classification)
            if not attr.startswith("_") and attr != "annotations"
        ]
        self.assertCountEqual(public_attrs, classification.__all__)


if __name__ == "__main__":
    unittest.main()
