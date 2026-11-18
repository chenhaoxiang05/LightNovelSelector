#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")/.."

# Normalize tar headers and the gzip timestamp for identical builds from identical sources.
python3 - <<'PY'
import gzip
import os
from pathlib import Path
import tarfile
from tempfile import NamedTemporaryFile

output = Path("dist/LightNovelSelector-linux.tar.gz")
sources = [
    Path("LICENSE"),
    Path("THIRD_PARTY_NOTICES.md"),
    Path("requirements-runtime.txt"),
    Path("lightnovel_classifier.py"),
    Path("linux/README.md"),
    Path("linux/run.sh"),
    *Path("linux").glob("*.py"),
    *Path("lightnovel_selector").rglob("*.py"),
]
output.parent.mkdir(exist_ok=True)
with NamedTemporaryFile(dir=output.parent, delete=False) as raw:
    temporary = Path(raw.name)
    try:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                for path in sorted(sources):
                    info = tarfile.TarInfo(f"LightNovelSelector/{path.as_posix()}")
                    info.size = path.stat().st_size
                    info.mode = 0o755 if path == Path("linux/run.sh") else 0o644
                    with path.open("rb") as source:
                        archive.addfile(info, source)
        raw.flush()
        os.chmod(temporary, 0o644)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
print(output)
PY
