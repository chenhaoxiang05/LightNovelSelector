from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

PROJECT_NAME = "LightNovelSelector"
REPOSITORY_URL = "https://github.com/chenhaoxiang05/LightNovelSelector"
CHECKSUM_FILE_NAME = "SHA256SUMS.txt"
BUILD_INFO_SCHEMA_VERSION = 1
READ_LIMIT_BYTES = 32 * 1024 * 1024
SAFE_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.-]+)?$")
COMMIT_PATTERN = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64}|unknown)$")
CHECKSUM_LINE = re.compile(r"^([0-9a-fA-F]{64}) [ *](.+)$")
REQUIRED_SBOM_PACKAGES = (
    "LightNovelSelector",
    "defusedxml",
    "pyinstaller",
    "Microsoft.Web.WebView2",
    "Microsoft.WindowsAppSDK",
    "CPython",
    "Inno Setup",
)


class ReleaseAssetError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file_name(value: str) -> str:
    if (
        not SAFE_FILE_NAME.fullmatch(value)
        or value in {".", ".."}
        or Path(value).name != value
        or "/" in value
        or "\\" in value
    ):
        raise ReleaseAssetError(f"Unsafe release asset name: {value!r}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ReleaseAssetError(f"Required JSON file is missing or unsafe: {path}")
    if path.stat().st_size > READ_LIMIT_BYTES:
        raise ReleaseAssetError(f"JSON file exceeds the {READ_LIMIT_BYTES}-byte limit: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseAssetError(f"Unable to read JSON file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseAssetError(f"JSON root must be an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(encoded, encoding="utf-8", newline="\n")


def _spdx_package_id(name: str, version: str) -> str:
    token = re.sub(r"[^A-Za-z0-9.-]+", "-", f"{name}-{version}").strip("-.")
    suffix = hashlib.sha256(f"{name}\0{version}".encode()).hexdigest()[:12]
    return f"SPDXRef-Package-{token}-{suffix}"


def _add_spdx_package(
    sbom: dict[str, Any],
    *,
    name: str,
    version: str,
    supplier: str,
    purl_name: str,
    license_id: str,
) -> None:
    packages = sbom.get("packages")
    relationships = sbom.get("relationships")
    if not isinstance(packages, list) or not isinstance(relationships, list):
        raise ReleaseAssetError("SBOM packages and relationships must be arrays.")
    if any(isinstance(item, dict) and item.get("name") == name for item in packages):
        return

    package_id = _spdx_package_id(name, version)
    package = {
        "SPDXID": package_id,
        "copyrightText": "NOASSERTION",
        "downloadLocation": "NOASSERTION",
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceLocator": f"pkg:generic/{quote(purl_name, safe='-._~')}@{quote(version, safe='-._~')}",
                "referenceType": "purl",
            }
        ],
        "filesAnalyzed": False,
        "licenseConcluded": license_id,
        "licenseDeclared": license_id,
        "name": name,
        "supplier": supplier,
        "versionInfo": version,
    }
    packages.append(package)
    relationships.append(
        {
            "relatedSpdxElement": package_id,
            "relationshipType": "DEPENDS_ON",
            "spdxElementId": "SPDXRef-RootPackage",
        }
    )


def _find_installer_checksum(sbom: dict[str, Any], installer_name: str) -> str:
    files = sbom.get("files")
    if not isinstance(files, list):
        raise ReleaseAssetError("SBOM files must be an array.")

    matches: list[str] = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        raw_name = entry.get("fileName")
        if not isinstance(raw_name, str):
            continue
        normalized = raw_name.removeprefix("./")
        posix_path = PurePosixPath(normalized)
        if posix_path.is_absolute() or ".." in posix_path.parts:
            raise ReleaseAssetError(f"SBOM contains an unsafe file path: {raw_name!r}")
        if len(posix_path.parts) != 1 or posix_path.name != installer_name:
            continue
        checksums = entry.get("checksums")
        if not isinstance(checksums, list):
            continue
        for checksum in checksums:
            if (
                isinstance(checksum, dict)
                and str(checksum.get("algorithm", "")).upper() == "SHA256"
                and isinstance(checksum.get("checksumValue"), str)
            ):
                matches.append(checksum["checksumValue"].lower())

    if len(matches) != 1:
        raise ReleaseAssetError(
            f"SBOM must contain exactly one SHA-256 entry for {installer_name}; found {len(matches)}."
        )
    return matches[0]


def _validate_sbom(
    sbom: dict[str, Any],
    *,
    installer_name: str,
    installer_hash: str,
    version: str,
    require_augmented_packages: bool,
) -> None:
    if sbom.get("spdxVersion") != "SPDX-2.2":
        raise ReleaseAssetError("Only SPDX 2.2 release SBOMs are accepted.")
    if sbom.get("SPDXID") != "SPDXRef-DOCUMENT" or sbom.get("dataLicense") != "CC0-1.0":
        raise ReleaseAssetError("SBOM document metadata is incomplete.")
    if _find_installer_checksum(sbom, installer_name) != installer_hash:
        raise ReleaseAssetError("SBOM installer checksum does not match the release installer.")

    packages = sbom.get("packages")
    if not isinstance(packages, list):
        raise ReleaseAssetError("SBOM packages must be an array.")
    package_ids: set[str] = set()
    package_names: set[str] = set()
    root_package: dict[str, Any] | None = None
    for package in packages:
        if not isinstance(package, dict):
            raise ReleaseAssetError("SBOM package entries must be objects.")
        package_id = package.get("SPDXID")
        name = package.get("name")
        if not isinstance(package_id, str) or not isinstance(name, str):
            raise ReleaseAssetError("SBOM package entries require SPDXID and name.")
        if package_id in package_ids:
            raise ReleaseAssetError(f"SBOM contains duplicate package ID: {package_id}")
        package_ids.add(package_id)
        package_names.add(name.casefold())
        if package_id == "SPDXRef-RootPackage":
            root_package = package

    if root_package is None or root_package.get("name") != PROJECT_NAME:
        raise ReleaseAssetError("SBOM root package is missing.")
    if root_package.get("versionInfo") != version:
        raise ReleaseAssetError("SBOM root package version does not match the release version.")
    if not any(name.startswith("microsoft.netcore.app.runtime.") for name in package_names):
        raise ReleaseAssetError("SBOM does not list the bundled .NET runtime.")
    if require_augmented_packages:
        missing = [name for name in REQUIRED_SBOM_PACKAGES if name.casefold() not in package_names]
        if missing:
            raise ReleaseAssetError(f"SBOM is missing required components: {', '.join(missing)}")


def _augment_sbom(
    sbom: dict[str, Any],
    *,
    python_version: str,
    inno_version: str,
) -> None:
    _add_spdx_package(
        sbom,
        name="CPython",
        version=python_version,
        supplier="Organization: Python Software Foundation",
        purl_name="cpython",
        license_id="PSF-2.0",
    )
    _add_spdx_package(
        sbom,
        name="Inno Setup",
        version=inno_version,
        supplier="Organization: Jordan Russell and Martijn Laan",
        purl_name="inno-setup",
        license_id="NOASSERTION",
    )
    creation_info = sbom.get("creationInfo")
    if not isinstance(creation_info, dict):
        raise ReleaseAssetError("SBOM creationInfo must be an object.")
    creators = creation_info.get("creators")
    if not isinstance(creators, list) or not all(isinstance(item, str) for item in creators):
        raise ReleaseAssetError("SBOM creators must be an array of strings.")
    marker = "Tool: LightNovelSelector-release-assets"
    if marker not in creators:
        creators.append(marker)


def parse_checksum_manifest(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise ReleaseAssetError(f"Checksum manifest is missing or unsafe: {path}")
    if path.stat().st_size > 256 * 1024:
        raise ReleaseAssetError("Checksum manifest is unexpectedly large.")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ReleaseAssetError(f"Unable to read checksum manifest: {exc}") from exc
    if not lines:
        raise ReleaseAssetError("Checksum manifest is empty.")

    entries: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        match = CHECKSUM_LINE.fullmatch(line)
        if match is None:
            raise ReleaseAssetError(f"Invalid checksum line {line_number}.")
        digest, raw_name = match.groups()
        name = _safe_file_name(raw_name)
        if name == CHECKSUM_FILE_NAME:
            raise ReleaseAssetError("Checksum manifest cannot list itself.")
        if name in entries:
            raise ReleaseAssetError(f"Duplicate checksum entry: {name}")
        entries[name] = digest.lower()
    return entries


def _write_checksum_manifest(dist_dir: Path, asset_names: list[str]) -> Path:
    checksum_path = dist_dir / CHECKSUM_FILE_NAME
    lines = [f"{sha256_file(dist_dir / name)} *{name}" for name in sorted(asset_names)]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return checksum_path


def finalize_release_assets(
    *,
    dist_dir: Path,
    installer_name: str,
    sbom_source: Path,
    version: str,
    signature_status: str,
    signer_subject: str | None,
    source_commit: str,
    source_ref: str,
    source_dirty: bool,
    python_version: str,
    inno_version: str,
) -> dict[str, Any]:
    if not VERSION_PATTERN.fullmatch(version):
        raise ReleaseAssetError(f"Invalid release version: {version!r}")
    if not COMMIT_PATTERN.fullmatch(source_commit):
        raise ReleaseAssetError(f"Invalid source commit: {source_commit!r}")
    if signature_status not in {"verified", "unsigned"}:
        raise ReleaseAssetError(f"Invalid signature status: {signature_status!r}")
    if signature_status == "verified" and not signer_subject:
        raise ReleaseAssetError("A verified signature requires a signer subject.")
    installer_name = _safe_file_name(installer_name)
    dist_dir = dist_dir.resolve()
    installer_path = dist_dir / installer_name
    if not installer_path.is_file() or installer_path.is_symlink():
        raise ReleaseAssetError(f"Installer is missing or unsafe: {installer_path}")

    installer_hash = sha256_file(installer_path)
    sbom = _read_json(sbom_source)
    _validate_sbom(
        sbom,
        installer_name=installer_name,
        installer_hash=installer_hash,
        version=version,
        require_augmented_packages=False,
    )
    _augment_sbom(sbom, python_version=python_version, inno_version=inno_version)
    _validate_sbom(
        sbom,
        installer_name=installer_name,
        installer_hash=installer_hash,
        version=version,
        require_augmented_packages=True,
    )

    asset_stem = f"{PROJECT_NAME}-v{version}-win-x64"
    sbom_name = _safe_file_name(f"{asset_stem}-sbom.spdx.json")
    build_info_name = _safe_file_name(f"{asset_stem}-build-info.json")
    sbom_path = dist_dir / sbom_name
    build_info_path = dist_dir / build_info_name
    _write_json(sbom_path, sbom)
    sbom_hash = sha256_file(sbom_path)

    build_info: dict[str, Any] = {
        "artifact": {
            "authenticode": {
                "status": signature_status,
                "subject": signer_subject if signature_status == "verified" else None,
                "timestamped": signature_status == "verified",
            },
            "file": installer_name,
            "sha256": installer_hash,
            "size_bytes": installer_path.stat().st_size,
        },
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "checksum_manifest": CHECKSUM_FILE_NAME,
        "project": PROJECT_NAME,
        "repository": REPOSITORY_URL,
        "sbom": {
            "file": sbom_name,
            "format": "SPDX-2.2",
            "generator": "Microsoft.SBOMTool 4.1.5",
            "sha256": sbom_hash,
        },
        "schema_version": BUILD_INFO_SCHEMA_VERSION,
        "source": {
            "commit": source_commit.lower(),
            "dirty": source_dirty,
            "ref": source_ref or "unknown",
        },
        "version": version,
    }
    _write_json(build_info_path, build_info)
    _write_checksum_manifest(dist_dir, [installer_name, sbom_name, build_info_name])
    return verify_release_directory(dist_dir)


def verify_release_directory(dist_dir: Path) -> dict[str, Any]:
    dist_dir = dist_dir.resolve()
    if not dist_dir.is_dir() or dist_dir.is_symlink():
        raise ReleaseAssetError(f"Release directory is missing or unsafe: {dist_dir}")
    checksum_path = dist_dir / CHECKSUM_FILE_NAME
    checksums = parse_checksum_manifest(checksum_path)

    actual_entries = list(dist_dir.iterdir())
    if any(entry.is_dir() or entry.is_symlink() for entry in actual_entries):
        raise ReleaseAssetError("Release directory must contain regular files only.")
    actual_names = {entry.name for entry in actual_entries}
    expected_names = set(checksums) | {CHECKSUM_FILE_NAME}
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        unexpected = sorted(actual_names - expected_names)
        raise ReleaseAssetError(
            f"Release asset set mismatch; missing={missing or 'none'}, unexpected={unexpected or 'none'}."
        )
    for name, expected_hash in checksums.items():
        path = dist_dir / name
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise ReleaseAssetError(f"SHA-256 mismatch for {name}.")

    build_info_names = [name for name in checksums if name.endswith("-build-info.json")]
    if len(build_info_names) != 1:
        raise ReleaseAssetError("Release must contain exactly one build-info JSON file.")
    build_info = _read_json(dist_dir / build_info_names[0])
    if build_info.get("schema_version") != BUILD_INFO_SCHEMA_VERSION:
        raise ReleaseAssetError("Unsupported build-info schema version.")
    if build_info.get("project") != PROJECT_NAME or build_info.get("repository") != REPOSITORY_URL:
        raise ReleaseAssetError("Build-info project identity is invalid.")
    version = build_info.get("version")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise ReleaseAssetError("Build-info version is invalid.")

    artifact = build_info.get("artifact")
    sbom_info = build_info.get("sbom")
    source = build_info.get("source")
    if not isinstance(artifact, dict) or not isinstance(sbom_info, dict) or not isinstance(source, dict):
        raise ReleaseAssetError("Build-info sections are incomplete.")
    installer_name = _safe_file_name(str(artifact.get("file", "")))
    sbom_name = _safe_file_name(str(sbom_info.get("file", "")))
    if installer_name not in checksums or sbom_name not in checksums:
        raise ReleaseAssetError("Build-info references an unlisted release asset.")
    installer_path = dist_dir / installer_name
    installer_hash = sha256_file(installer_path)
    if artifact.get("sha256") != installer_hash or artifact.get("size_bytes") != installer_path.stat().st_size:
        raise ReleaseAssetError("Build-info installer metadata does not match the release asset.")
    if sbom_info.get("format") != "SPDX-2.2" or sbom_info.get("sha256") != sha256_file(dist_dir / sbom_name):
        raise ReleaseAssetError("Build-info SBOM metadata does not match the release asset.")
    commit = source.get("commit")
    if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
        raise ReleaseAssetError("Build-info source commit is invalid.")
    if not isinstance(source.get("dirty"), bool):
        raise ReleaseAssetError("Build-info source dirty state is invalid.")

    authenticode = artifact.get("authenticode")
    if not isinstance(authenticode, dict) or authenticode.get("status") not in {"verified", "unsigned"}:
        raise ReleaseAssetError("Build-info Authenticode status is invalid.")
    if authenticode["status"] == "verified":
        if not authenticode.get("subject") or authenticode.get("timestamped") is not True:
            raise ReleaseAssetError("Verified Authenticode metadata requires a signer and timestamp.")
    elif authenticode.get("subject") is not None or authenticode.get("timestamped") is not False:
        raise ReleaseAssetError("Unsigned Authenticode metadata is inconsistent.")

    sbom = _read_json(dist_dir / sbom_name)
    _validate_sbom(
        sbom,
        installer_name=installer_name,
        installer_hash=installer_hash,
        version=version,
        require_augmented_packages=True,
    )
    return {
        "assets": len(checksums),
        "authenticode": authenticode["status"],
        "installer": installer_name,
        "sha256": installer_hash,
        "version": version,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finalize and verify LightNovelSelector release assets.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    finalize = subparsers.add_parser("finalize", help="Create SBOM, build info, and checksums.")
    finalize.add_argument("--dist", type=Path, required=True)
    finalize.add_argument("--installer", required=True)
    finalize.add_argument("--sbom-source", type=Path, required=True)
    finalize.add_argument("--version", required=True)
    finalize.add_argument("--signature-status", choices=("verified", "unsigned"), required=True)
    finalize.add_argument("--signer-subject")
    finalize.add_argument("--source-commit", required=True)
    finalize.add_argument("--source-ref", default="unknown")
    finalize.add_argument("--source-dirty", action="store_true")
    finalize.add_argument("--python-version", required=True)
    finalize.add_argument("--inno-version", required=True)

    verify = subparsers.add_parser("verify", help="Verify a completed release directory.")
    verify.add_argument("--dist", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "finalize":
            result = finalize_release_assets(
                dist_dir=args.dist,
                installer_name=args.installer,
                sbom_source=args.sbom_source,
                version=args.version,
                signature_status=args.signature_status,
                signer_subject=args.signer_subject,
                source_commit=args.source_commit,
                source_ref=args.source_ref,
                source_dirty=args.source_dirty,
                python_version=args.python_version,
                inno_version=args.inno_version,
            )
        else:
            result = verify_release_directory(args.dist)
    except (OSError, ReleaseAssetError) as exc:
        print(f"release asset verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
