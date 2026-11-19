#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
python="${LN_SELECTOR_PYTHON:-python3}"
"$python" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"; import defusedxml'
mkdir -p build/macos/module-cache dist/macos
# The signing workspace must be outside a File Provider synced checkout. Such providers
# can attach FinderInfo to an .app as soon as its directory appears.
stage="$(mktemp -d)"
incoming="$(mktemp -d "$root/dist/macos/.incoming.XXXXXX")"
trap 'rm -rf "$stage" "$incoming"' EXIT
app="$stage/LightNovelSelector.app"
contents="$app/Contents"
resources="$contents/Resources"
mkdir -p "$contents/MacOS" "$resources/core" "$resources/licenses"
xcrun --sdk macosx swiftc -swift-version 6 -parse-as-library -O \
    -module-cache-path "$root/build/macos/module-cache" \
    -target "$(uname -m)-apple-macosx26.0" \
    macos/Sources/*.swift -o "$contents/MacOS/LightNovelSelector"
cp macos/Info.plist "$contents/Info.plist"
version="$("$python" -c 'from lightnovel_selector.constants import APP_VERSION; print(APP_VERSION)')"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $version" "$contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $version" "$contents/Info.plist"
icon=native/LightNovelSelector.WinUI/Assets/Square150x150Logo.scale-200.png
sips -z 512 512 "$icon" --out "$stage/icon.png" >/dev/null
sips -s format icns "$stage/icon.png" --out "$resources/AppIcon.icns" >/dev/null
cp lightnovel_sidecar.py "$resources/core/"
cp LICENSE THIRD_PARTY_NOTICES.md "$resources/licenses/"
"$python" - "$resources" <<'PY'
import importlib.metadata
from pathlib import Path
import shutil
import sys
import sysconfig
import defusedxml

resources = Path(sys.argv[1])
package = Path(defusedxml.__file__).parent
ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
for src in (Path("lightnovel_selector"), package):
    shutil.copytree(src, resources / "core" / src.name, ignore=ignore)
try:
    distribution = importlib.metadata.distribution("defusedxml")
    license_file = next(distribution.locate_file(file) for file in distribution.files or ()
                        if file.name.lower() == "license")
except (importlib.metadata.PackageNotFoundError, StopIteration):
    license_file = package.parent / "LICENSE"
shutil.copyfile(license_file, resources / "licenses" / "defusedxml-LICENSE")
license_file = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
if license_file.is_file():
    shutil.copyfile(license_file, resources / "licenses" / "Python-LICENSE.txt")
try:
    pyinstaller = importlib.metadata.distribution("pyinstaller")
except importlib.metadata.PackageNotFoundError:
    pass
else:
    for file in pyinstaller.files or ():
        if file.name.upper() in ("COPYING", "COPYING.TXT", "LICENSE", "LICENSE.TXT"):
            shutil.copyfile(pyinstaller.locate_file(file), resources / "licenses" / ("PyInstaller-" + file.name))

PY

if [[ -n "${LN_SELECTOR_SIDECAR:-}" ]]; then
    mkdir -p "$contents/Helpers"
    install -m 755 "$LN_SELECTOR_SIDECAR" "$contents/Helpers/LightNovelSelector.Sidecar"
else
    # Finder has a minimal PATH. Remember the build interpreter for local source builds.
    "$python" -c 'import sys; print(sys.executable)' > "$resources/python-path"
fi
# sips can add Finder metadata to the icon; strip it from the staging copy before signing.
xattr -cr "$app"
codesign --force --sign - "$app"
codesign --verify --strict "$app"
destination="$root/dist/macos/LightNovelSelector.app"
ditto --norsrc --noextattr "$app" "$incoming/LightNovelSelector.app"
# Both directories are in this checkout. Swap atomically to keep the last good build
# available throughout an upgrade; the exit trap then discards the old bundle.
"$python" - "$incoming/LightNovelSelector.app" "$destination" <<'PYCODE'
import ctypes
import os
import sys
from pathlib import Path

source, destination = map(Path, sys.argv[1:])
if destination.exists():
    libc = ctypes.CDLL(None, use_errno=True)
    rename_swap = 2  # Darwin RENAME_SWAP in <stdio.h>
    if libc.renamex_np(os.fsencode(source), os.fsencode(destination), rename_swap) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))
else:
    source.rename(destination)
PYCODE
# File Provider can add FinderInfo to the bundle directory when it is moved into place.
xattr -d com.apple.FinderInfo "$destination" 2>/dev/null || true
codesign --verify "$destination"
echo "$destination"
