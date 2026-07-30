from pathlib import Path
import unittest
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
