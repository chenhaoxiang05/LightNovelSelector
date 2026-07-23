from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def verify_sidecar(executable: Path) -> None:
    payload = '{"id":1,"method":"ping"}\n{"id":2,"method":"shutdown"}\n'
    process = subprocess.run(
        [str(executable)],
        input=payload,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )
    if process.returncode != 0 or process.stderr:
        raise RuntimeError(
            f"Sidecar failed: stdout={process.stdout!r}, stderr={process.stderr!r}, exit={process.returncode}"
        )

    responses = [json.loads(line) for line in process.stdout.splitlines()]
    if len(responses) != 2 or not all(response.get("ok") for response in responses):
        raise RuntimeError(f"Unexpected Sidecar responses: {responses!r}")
    if responses[0]["result"].get("protocol_version") != 1:
        raise RuntimeError(f"Unexpected protocol version: {responses[0]!r}")
    if responses[1]["result"].get("accepted") is not True:
        raise RuntimeError(f"Sidecar did not accept shutdown: {responses[1]!r}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: verify_sidecar.py <LightNovelSelector.Sidecar.exe>")
    verify_sidecar(Path(sys.argv[1]))
