import unittest

from lightnovel_selector.cancellation import OperationCancelled


class CancellationTests(unittest.TestCase):
    def test_operation_cancelled_is_runtime_error(self) -> None:
        self.assertTrue(issubclass(OperationCancelled, RuntimeError))

    def test_operation_cancelled_initialization(self) -> None:
        exc = OperationCancelled("User clicked cancel")
        self.assertEqual(str(exc), "User clicked cancel")
        self.assertIsInstance(exc, RuntimeError)

    def test_operation_cancelled_can_be_raised(self) -> None:
        with self.assertRaises(OperationCancelled) as cm:
            raise OperationCancelled("test msg")
        self.assertEqual(str(cm.exception), "test msg")


if __name__ == "__main__":
    unittest.main()
