from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.release_assets import (
    CHECKSUM_FILE_NAME,
    ReleaseAssetError,
    finalize_release_assets,
    parse_checksum_manifest,
    verify_release_directory,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source_sbom(installer_name: str, installer_payload: bytes, version: str) -> dict[str, object]:
    package_names = [
        "defusedxml",
        "pyinstaller",
        "Microsoft.Web.WebView2",
        "Microsoft.WindowsAppSDK.Base",
        "Microsoft.WindowsAppSDK.Foundation",
        "Microsoft.WindowsAppSDK.InteractiveExperiences",
        "Microsoft.WindowsAppSDK.WinUI",
        "Microsoft.NETCore.App.Runtime.win-x64",
    ]
    packages: list[dict[str, object]] = [
        {
            "SPDXID": "SPDXRef-RootPackage",
            "name": "LightNovelSelector",
            "versionInfo": version,
        }
    ]
    packages.extend(
        {"SPDXID": f"SPDXRef-{index}", "name": name, "versionInfo": "1"}
        for index, name in enumerate(package_names, start=1)
    )
    return {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {"created": "2026-07-31T00:00:00Z", "creators": ["Tool: test"]},
        "dataLicense": "CC0-1.0",
        "documentNamespace": "https://example.invalid/test",
        "files": [
            {
                "SPDXID": "SPDXRef-Installer",
                "checksums": [{"algorithm": "SHA256", "checksumValue": _sha256(installer_payload)}],
                "fileName": f"./{installer_name}",
            }
        ],
        "packages": packages,
        "relationships": [],
        "spdxVersion": "SPDX-2.2",
    }


def _create_release(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    version = "2.1.0-dev.11"
    installer_name = f"LightNovelSelector-v{version}-win-x64-setup.exe"
    installer_payload = b"installer fixture"
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / installer_name).write_bytes(installer_payload)
    sbom_source = tmp_path / "source.spdx.json"
    sbom_source.write_text(
        json.dumps(_source_sbom(installer_name, installer_payload, version)),
        encoding="utf-8",
    )
    result = finalize_release_assets(
        dist_dir=dist,
        installer_name=installer_name,
        sbom_source=sbom_source,
        version=version,
        signature_status="unsigned",
        signer_subject=None,
        source_commit="1" * 40,
        source_ref="codex/release-trust",
        source_dirty=False,
        python_version="3.12.10",
        inno_version="6.4.3",
    )
    return dist, result


def test_finalize_and_verify_release_assets(tmp_path: Path) -> None:
    dist, result = _create_release(tmp_path)

    assert result["assets"] == 3
    assert result["authenticode"] == "unsigned"
    checksums = parse_checksum_manifest(dist / CHECKSUM_FILE_NAME)
    assert len(checksums) == 3

    sbom_path = next(dist.glob("*-sbom.spdx.json"))
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    package_names = {package["name"] for package in sbom["packages"]}
    assert {"CPython", "Inno Setup"} <= package_names
    build_info_path = next(dist.glob("*-build-info.json"))
    build_info = json.loads(build_info_path.read_text(encoding="utf-8"))
    assert build_info["source"]["dirty"] is False
    assert verify_release_directory(dist) == result


def test_verify_rejects_tampered_installer(tmp_path: Path) -> None:
    dist, _ = _create_release(tmp_path)
    installer = next(dist.glob("*-setup.exe"))
    installer.write_bytes(b"tampered")

    with pytest.raises(ReleaseAssetError, match="SHA-256 mismatch"):
        verify_release_directory(dist)


@pytest.mark.parametrize(
    "line",
    [
        f"{'0' * 64} *../escape.exe\n",
        f"{'0' * 64} *folder/escape.exe\n",
        f"{'0' * 64} *folder\\escape.exe\n",
        f"{'0' * 64} *{CHECKSUM_FILE_NAME}\n",
    ],
)
def test_checksum_manifest_rejects_unsafe_names(tmp_path: Path, line: str) -> None:
    checksum_path = tmp_path / CHECKSUM_FILE_NAME
    checksum_path.write_text(line, encoding="utf-8")

    with pytest.raises(ReleaseAssetError):
        parse_checksum_manifest(checksum_path)


def test_verify_rejects_unlisted_release_asset(tmp_path: Path) -> None:
    dist, _ = _create_release(tmp_path)
    (dist / "debug.pdb").write_bytes(b"debug")

    with pytest.raises(ReleaseAssetError, match="asset set mismatch"):
        verify_release_directory(dist)


def test_finalize_rejects_incomplete_sbom(tmp_path: Path) -> None:
    version = "2.1.0-dev.11"
    installer_name = f"LightNovelSelector-v{version}-win-x64-setup.exe"
    installer_payload = b"installer fixture"
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / installer_name).write_bytes(installer_payload)
    sbom = _source_sbom(installer_name, installer_payload, version)
    packages = sbom["packages"]
    assert isinstance(packages, list)
    sbom["packages"] = [package for package in packages if package["name"] != "Microsoft.NETCore.App.Runtime.win-x64"]
    sbom_source = tmp_path / "source.spdx.json"
    sbom_source.write_text(json.dumps(sbom), encoding="utf-8")

    with pytest.raises(ReleaseAssetError, match=r"\.NET runtime"):
        finalize_release_assets(
            dist_dir=dist,
            installer_name=installer_name,
            sbom_source=sbom_source,
            version=version,
            signature_status="unsigned",
            signer_subject=None,
            source_commit="1" * 40,
            source_ref="test",
            source_dirty=False,
            python_version="3.12.10",
            inno_version="6.4.3",
        )


def test_finalize_rejects_sbom_without_required_winui_component(tmp_path: Path) -> None:
    version = "2.1.0-dev.11"
    installer_name = f"LightNovelSelector-v{version}-win-x64-setup.exe"
    installer_payload = b"installer fixture"
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / installer_name).write_bytes(installer_payload)
    sbom = _source_sbom(installer_name, installer_payload, version)
    packages = sbom["packages"]
    assert isinstance(packages, list)
    sbom["packages"] = [package for package in packages if package["name"] != "Microsoft.WindowsAppSDK.WinUI"]
    sbom_source = tmp_path / "source.spdx.json"
    sbom_source.write_text(json.dumps(sbom), encoding="utf-8")

    with pytest.raises(ReleaseAssetError, match="Microsoft.WindowsAppSDK.WinUI"):
        finalize_release_assets(
            dist_dir=dist,
            installer_name=installer_name,
            sbom_source=sbom_source,
            version=version,
            signature_status="unsigned",
            signer_subject=None,
            source_commit="1" * 40,
            source_ref="test",
            source_dirty=False,
            python_version="3.12.10",
            inno_version="6.4.3",
        )


def test_finalize_rejects_verified_signature_without_signer(tmp_path: Path) -> None:
    version = "2.1.0-dev.11"
    installer_name = f"LightNovelSelector-v{version}-win-x64-setup.exe"
    installer_payload = b"installer fixture"
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / installer_name).write_bytes(installer_payload)
    sbom_source = tmp_path / "source.spdx.json"
    sbom_source.write_text(
        json.dumps(_source_sbom(installer_name, installer_payload, version)),
        encoding="utf-8",
    )

    with pytest.raises(ReleaseAssetError, match="signer subject"):
        finalize_release_assets(
            dist_dir=dist,
            installer_name=installer_name,
            sbom_source=sbom_source,
            version=version,
            signature_status="verified",
            signer_subject=None,
            source_commit="1" * 40,
            source_ref="test",
            source_dirty=False,
            python_version="3.12.10",
            inno_version="6.4.3",
        )
