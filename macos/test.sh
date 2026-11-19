#!/usr/bin/env bash
# Compile the UI's model into a temporary copy of the finished bundle and exercise it offline.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
app="${1:-$root/dist/macos/LightNovelSelector.app}"
test -x "$app/Contents/MacOS/LightNovelSelector"
temp="$(mktemp -d)"
trap 'rm -rf "$temp"' EXIT
ditto --norsrc --noextattr "$app" "$temp/LightNovelSelector.app"
mkdir -p build/macos/module-cache "$temp/state" "$temp/books"
executable="$temp/LightNovelSelector.app/Contents/MacOS/LightNovelSelector"
xcrun --sdk macosx swiftc -swift-version 6 -parse-as-library \
    -module-cache-path "$root/build/macos/module-cache" \
    -target "$(uname -m)-apple-macosx26.0" macos/Sources/LibraryModel.swift \
    macos/Sources/Sidecar.swift macos/Tests/Workflow.swift -o "$executable"
xattr -cr "$temp/LightNovelSelector.app"
codesign --force --sign - "$temp/LightNovelSelector.app"
LOCALAPPDATA="$temp/state" "$executable" "$temp/books"
