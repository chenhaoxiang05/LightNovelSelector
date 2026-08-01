import json
import re
import unittest
from pathlib import Path
from xml.etree import ElementTree

from lightnovel_selector.constants import APP_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProjectMetadataTests(unittest.TestCase):
    def test_python_and_native_versions_stay_in_sync(self) -> None:
        numeric_version = APP_VERSION.split("-", 1)[0].split("+", 1)[0]
        assembly_version = f"{numeric_version}.0"

        project = ElementTree.parse(
            PROJECT_ROOT / "native" / "LightNovelSelector.WinUI" / "LightNovelSelector.WinUI.csproj"
        ).getroot()
        self.assertEqual(project.findtext("./PropertyGroup/Version"), APP_VERSION)
        self.assertEqual(project.findtext("./PropertyGroup/AssemblyVersion"), assembly_version)
        self.assertEqual(project.findtext("./PropertyGroup/FileVersion"), assembly_version)
        self.assertEqual(project.findtext("./PropertyGroup/InformationalVersion"), APP_VERSION)

        app_manifest = ElementTree.parse(
            PROJECT_ROOT / "native" / "LightNovelSelector.WinUI" / "app.manifest"
        ).getroot()
        app_identity = app_manifest.find("{urn:schemas-microsoft-com:asm.v1}assemblyIdentity")
        if app_identity is None:
            self.fail("app.manifest 缺少 assemblyIdentity。")
        self.assertEqual(app_identity.get("version"), assembly_version)

        package_manifest = ElementTree.parse(
            PROJECT_ROOT / "native" / "LightNovelSelector.WinUI" / "Package.appxmanifest"
        ).getroot()
        package_identity = package_manifest.find(
            "{http://schemas.microsoft.com/appx/manifest/foundation/windows10}Identity"
        )
        if package_identity is None:
            self.fail("Package.appxmanifest 缺少 Identity。")
        self.assertEqual(package_identity.get("Version"), assembly_version)

    def test_release_supply_chain_tools_are_version_pinned(self) -> None:
        manifest = json.loads((PROJECT_ROOT / ".config" / "dotnet-tools.json").read_text(encoding="utf-8"))
        sbom_tool = manifest["tools"]["microsoft.sbom.dotnettool"]
        self.assertEqual(sbom_tool["version"], "4.1.5")
        self.assertEqual(sbom_tool["commands"], ["sbom-tool"])
        self.assertFalse(sbom_tool["rollForward"])

        workflow = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        action_refs = re.findall(r"^\s*uses:\s*[^@\s]+@([^\s#]+)", workflow, flags=re.MULTILINE)
        self.assertGreaterEqual(len(action_refs), 5)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", reference) for reference in action_refs))
        self.assertEqual(workflow.count("actions/attest@"), 2)
        self.assertIn("runs-on: windows-2022", workflow)
        self.assertIn("artifact-metadata: write", workflow)
        self.assertIn("dotnet-version: |", workflow)
        self.assertIn("8.0.x", workflow)
        self.assertIn("10.0.x", workflow)
        self.assertIn('"-RequireCleanSource"', workflow)
        self.assertIn("git merge-base --is-ancestor $env:GITHUB_SHA origin/main", workflow)
        self.assertIn("runpy.run_path('lightnovel_selector/constants.py')", workflow)
        self.assertNotIn("from lightnovel_selector.constants import APP_VERSION", workflow)
        self.assertIn("id: release-assets", workflow)
        self.assertIn("sbom-path: ${{ steps.release-assets.outputs.sbom_path }}", workflow)
        self.assertNotIn("sbom-path: dist/winui/*", workflow)
        self.assertIn("gh release delete-asset", workflow)
        self.assertIn("Compare-Object", workflow)

    def test_winui_uses_only_required_windows_app_sdk_components(self) -> None:
        project = ElementTree.parse(
            PROJECT_ROOT / "native" / "LightNovelSelector.WinUI" / "LightNovelSelector.WinUI.csproj"
        ).getroot()
        package_references = {
            reference.get("Include")
            for reference in project.findall("./ItemGroup/PackageReference")
            if reference.get("Include")
        }
        required = {
            "Microsoft.WindowsAppSDK.Foundation",
            "Microsoft.WindowsAppSDK.InteractiveExperiences",
            "Microsoft.WindowsAppSDK.WinUI",
        }
        self.assertTrue(required <= package_references)
        self.assertNotIn("Microsoft.WindowsAppSDK", package_references)
        self.assertEqual(
            project.findtext("./PropertyGroup/WindowsAppSDKSelfContained"),
            "true",
        )

        package_lock = json.loads(
            (PROJECT_ROOT / "native" / "LightNovelSelector.WinUI" / "packages.lock.json").read_text(encoding="utf-8")
        )
        locked_packages = {
            package_name for framework in package_lock["dependencies"].values() for package_name in framework
        }
        self.assertTrue(required | {"Microsoft.WindowsAppSDK.Base", "Microsoft.Web.WebView2"} <= locked_packages)
        self.assertTrue(
            locked_packages.isdisjoint(
                {
                    "Microsoft.WindowsAppSDK",
                    "Microsoft.WindowsAppSDK.AI",
                    "Microsoft.WindowsAppSDK.DWrite",
                    "Microsoft.WindowsAppSDK.ML",
                    "Microsoft.WindowsAppSDK.Runtime",
                    "Microsoft.WindowsAppSDK.Widgets",
                    "Microsoft.Windows.AI.MachineLearning",
                    "System.Numerics.Tensors",
                }
            )
        )

        build_script = (PROJECT_ROOT / "scripts" / "windows" / "build_winui.ps1").read_text(encoding="utf-8")
        self.assertIn("$MaxPublishBytes = 210 * 1MB", build_script)
        for forbidden_payload in (
            "DirectML.dll",
            "onnxruntime.dll",
            "Microsoft.Windows.AI.*",
            "Microsoft.Windows.Widgets*",
            "Microsoft.Windows.Workloads*",
        ):
            self.assertIn(forbidden_payload, build_script)
