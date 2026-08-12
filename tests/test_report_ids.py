import unittest
import uuid

from lightnovel_selector.report_ids import is_valid_execution_id


class ReportExecutionIdTests(unittest.TestCase):
    def test_accepts_canonical_lowercase_uuid_hex(self) -> None:
        self.assertTrue(is_valid_execution_id(uuid.uuid4().hex))
        self.assertTrue(is_valid_execution_id("0" * 32))

    def test_rejects_noncanonical_or_malformed_values(self) -> None:
        canonical = uuid.uuid4().hex
        invalid_values: tuple[object, ...] = (
            None,
            uuid.UUID(hex=canonical),
            canonical.upper(),
            str(uuid.UUID(hex=canonical)),
            "0" * 31,
            "0" * 33,
            "g" * 32,
            b"0" * 32,
        )
        for value in invalid_values:
            with self.subTest(value=value):
                self.assertFalse(is_valid_execution_id(value))


if __name__ == "__main__":
    unittest.main()
