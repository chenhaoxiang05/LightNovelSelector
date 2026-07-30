from __future__ import annotations

import json
import subprocess
import sys
import unittest
from io import StringIO
from pathlib import Path

from lightnovel_selector.sidecar import PROTOCOL_VERSION, SidecarServer

ROOT = Path(__file__).resolve().parents[1]


class FakeService:
    def snapshot(self, log_cursor: int = 0, plans_revision: int = -1) -> dict:
        return {"log_cursor": log_cursor, "plans_revision": plans_revision}

    def edit_plan(self, index: int, series_name: str) -> dict:
        return {"index": index, "series_name": series_name}


class SidecarProtocolTests(unittest.TestCase):
    def run_server(self, *requests: str) -> list[dict]:
        input_stream = StringIO("\n".join(requests) + "\n")
        output_stream = StringIO()
        server = SidecarServer(FakeService(), input_stream=input_stream, output_stream=output_stream)  # type: ignore[arg-type]

        self.assertEqual(server.serve_forever(), 0)

        return [json.loads(line) for line in output_stream.getvalue().splitlines()]

    def test_ping_poll_and_shutdown_keep_request_ids(self) -> None:
        responses = self.run_server(
            '{"id":1,"method":"ping"}',
            '{"id":8,"method":"poll","params":{"log_cursor":7,"plans_revision":3}}',
            '{"id":2,"method":"shutdown"}',
        )

        self.assertEqual(responses[0]["id"], 1)
        self.assertTrue(responses[0]["ok"])
        self.assertEqual(responses[0]["result"]["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(responses[1]["result"], {"log_cursor": 7, "plans_revision": 3})
        self.assertEqual(responses[2], {"id": 2, "ok": True, "result": {"accepted": True}})

    def test_invalid_json_and_unknown_method_return_structured_errors(self) -> None:
        responses = self.run_server(
            "not-json",
            '{"id":9,"method":"missing"}',
            '{"id":10,"method":"shutdown"}',
        )

        self.assertFalse(responses[0]["ok"])
        self.assertEqual(responses[0]["error"]["type"], "JSONDecodeError")
        self.assertEqual(responses[1]["id"], 9)
        self.assertEqual(responses[1]["error"]["type"], "ProtocolError")

    def test_rejects_non_integer_id_and_numeric_parameter(self) -> None:
        responses = self.run_server(
            '{"id":"1","method":"ping"}',
            '{"id":2,"method":"poll","params":{"log_cursor":"7","plans_revision":3}}',
            '{"id":3,"method":"shutdown"}',
        )

        self.assertIsNone(responses[0]["id"])
        self.assertEqual(responses[0]["error"]["type"], "ProtocolError")
        self.assertEqual(responses[1]["id"], 2)
        self.assertEqual(responses[1]["error"]["type"], "ProtocolError")

    def test_rejects_oversized_manual_series_name(self) -> None:
        responses = self.run_server(
            json.dumps(
                {
                    "id": 1,
                    "method": "edit_plan",
                    "params": {
                        "index": 0,
                        "series_name": "x" * 121,
                    },
                }
            ),
            '{"id":2,"method":"shutdown"}',
        )

        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[0]["error"]["type"], "ProtocolError")
        self.assertIn("不能超过 120", responses[0]["error"]["message"])

    def test_sidecar_module_has_clean_process_protocol(self) -> None:
        payload = '{"id":1,"method":"ping"}\n{"id":2,"method":"shutdown"}\n'
        completed = subprocess.run(
            [sys.executable, "-m", "lightnovel_selector.sidecar"],
            cwd=ROOT,
            input=payload,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=15,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual([item["id"] for item in responses], [1, 2])
        self.assertEqual(responses[0]["result"]["protocol_version"], PROTOCOL_VERSION)


if __name__ == "__main__":
    unittest.main()
