import json
import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from lightnovel_selector.constants import APP_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")
_HTML_LINK_PATTERN = re.compile(
    r"<(?:a|img|source)\b[^>]*(href|src|srcset)=['\"]([^'\"]+)['\"]",
    flags=re.IGNORECASE,
)


def _document_link_targets(text: str) -> list[str]:
    targets = list(_MARKDOWN_LINK_PATTERN.findall(text))
    for attribute, value in _HTML_LINK_PATTERN.findall(text):
        if attribute.casefold() != "srcset":
            targets.append(value)
            continue
        targets.extend(candidate.strip().split(maxsplit=1)[0] for candidate in value.split(",") if candidate.strip())
    return targets


class ProjectMetadataTests(unittest.TestCase):
    def test_local_markdown_links_resolve_inside_repository(self) -> None:
        markdown_files = list(PROJECT_ROOT.glob("*.md"))
        for directory_name in (".github", "docs", "scripts"):
            markdown_files.extend((PROJECT_ROOT / directory_name).rglob("*.md"))

        for markdown_path in sorted(set(markdown_files)):
            text = markdown_path.read_text(encoding="utf-8")
            for target in _document_link_targets(text):
                parsed = urlsplit(target.split(maxsplit=1)[0])
                if parsed.scheme or target.startswith(("#", "//")) or not parsed.path:
                    continue
                resolved = (markdown_path.parent / unquote(parsed.path)).resolve()
                with self.subTest(
                    document=str(markdown_path.relative_to(PROJECT_ROOT)),
                    target=target,
                ):
                    self.assertTrue(
                        resolved.is_relative_to(PROJECT_ROOT),
                        "本地文档链接不能越出仓库。",
                    )
                    self.assertTrue(resolved.exists(), "本地文档链接指向不存在的文件。")

    def test_html_srcset_checks_every_density_candidate(self) -> None:
        targets = _document_link_targets(
            '<picture><source srcset="normal.png 1x, retina.png 2x"><img src="fallback.png"></picture>'
        )

        self.assertEqual(targets, ["normal.png", "retina.png", "fallback.png"])

    def test_latest_release_notes_are_archived_without_drift(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        version_match = re.search(r"最新稳定版.+?`(v\d+\.\d+\.\d+)`", readme)
        if version_match is None:
            self.fail("README 缺少可解析的最新稳定版本。")
        latest_tag = version_match.group(1)
        archived_notes = PROJECT_ROOT / "docs" / "releases" / f"{latest_tag}.md"
        current_notes = PROJECT_ROOT / "UPDATE_NOTES.md"

        self.assertTrue(archived_notes.is_file(), "最新稳定版缺少仓库内发布说明归档。")
        notes = current_notes.read_text(encoding="utf-8")
        self.assertEqual(
            notes,
            archived_notes.read_text(encoding="utf-8"),
            "UPDATE_NOTES.md 必须与最新稳定版归档保持一致。",
        )
        self.assertTrue(
            notes.startswith(f"# LightNovelSelector {latest_tag} 更新说明\n"),
            "发布说明标题必须与 README 最新稳定版本一致。",
        )

        installer_name = f"LightNovelSelector-{latest_tag}-win-x64-setup.exe"
        self.assertIn(installer_name, readme)
        self.assertIn(installer_name, notes)
        self.assertIn(
            f"## {latest_tag} - ",
            (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
            "更新记录缺少最新稳定版本章节。",
        )

        if "-" not in APP_VERSION and "+" not in APP_VERSION:
            self.assertEqual(
                latest_tag,
                f"v{APP_VERSION}",
                "正式应用版本必须与 README 最新稳定版本一致。",
            )

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
        self.assertIn("根目录 UPDATE_NOTES.md", workflow)
        self.assertIn("[IO.File]::ReadAllText($currentNotes)", workflow)
        self.assertNotIn("from lightnovel_selector.constants import APP_VERSION", workflow)
        self.assertIn("id: release-assets", workflow)
        self.assertIn("sbom-path: ${{ steps.release-assets.outputs.sbom_path }}", workflow)
        self.assertNotIn("sbom-path: dist/winui/*", workflow)
        self.assertIn("gh release delete-asset", workflow)
        self.assertIn("Compare-Object", workflow)

        ci_workflow = (PROJECT_ROOT / ".github" / "workflows" / "windows-ci.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: windows-2022", ci_workflow)

        build_script = (PROJECT_ROOT / "scripts" / "windows" / "build_winui.ps1").read_text(encoding="utf-8")
        self.assertIn("$env:LN_SELECTOR_PYTHON = $python", build_script)
        self.assertIn("$previousSidecarPython = $env:LN_SELECTOR_PYTHON", build_script)
        self.assertIn("Remove-Item Env:LN_SELECTOR_PYTHON", build_script)

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

    def test_windows_build_covers_compact_detail_smoke(self) -> None:
        build_script = (PROJECT_ROOT / "scripts" / "windows" / "build_winui.ps1").read_text(encoding="utf-8")

        self.assertIn('Invoke-AppSmokeTest -AppPath $appExe -Mode "appearance-compact"', build_script)
        self.assertIn('$env:LN_SELECTOR_WINUI_TEST_WINDOW_SIZE = "1024x700"', build_script)
        self.assertIn('$env:LN_SELECTOR_WINUI_TEST_OPEN_DETAIL = "1"', build_script)
        appearance_source = (
            PROJECT_ROOT / "native" / "LightNovelSelector.WinUI" / "Views" / "MainPage.Appearance.cs"
        ).read_text(encoding="utf-8")
        self.assertIn("Math.Min(requestedHold, 15_000)", appearance_source)
        self.assertIn("WaitForExit(30000)", build_script)
        self.assertGreaterEqual(
            build_script.count("Remove-Item Env:LN_SELECTOR_WINUI_TEST_WINDOW_SIZE"),
            1,
        )
        self.assertGreaterEqual(
            build_script.count("Remove-Item Env:LN_SELECTOR_WINUI_TEST_OPEN_DETAIL"),
            1,
        )
