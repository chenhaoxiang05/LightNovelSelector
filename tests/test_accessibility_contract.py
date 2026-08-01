import unittest
from pathlib import Path
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
XAML_NAMESPACE = "http://schemas.microsoft.com/winfx/2006/xaml/presentation"
X_NAMESPACE = "http://schemas.microsoft.com/winfx/2006/xaml"
X_NAME = f"{{{X_NAMESPACE}}}Name"
X_KEY = f"{{{X_NAMESPACE}}}Key"


class AccessibilityContractTests(unittest.TestCase):
    main_page: ElementTree.Element
    interface_roots: list[ElementTree.Element]
    design_tokens: ElementTree.Element

    @classmethod
    def setUpClass(cls) -> None:
        cls.main_page = ElementTree.parse(
            PROJECT_ROOT / "native" / "LightNovelSelector.WinUI" / "Views" / "MainPage.xaml"
        ).getroot()
        component_folder = PROJECT_ROOT / "native" / "LightNovelSelector.WinUI" / "Components"
        cls.interface_roots = [
            cls.main_page,
            *(ElementTree.parse(path).getroot() for path in sorted(component_folder.glob("*.xaml"))),
        ]
        cls.design_tokens = ElementTree.parse(
            PROJECT_ROOT / "native" / "LightNovelSelector.WinUI" / "Styles" / "DesignTokens.xaml"
        ).getroot()

    def _element_named(self, name: str) -> ElementTree.Element:
        for root in self.interface_roots:
            for element in root.iter():
                if element.get(X_NAME) == name:
                    return element
        self.fail(f"界面 XAML 缺少 x:Name={name!r} 的控件。")

    def test_primary_regions_have_landmarks_and_names(self) -> None:
        expected = {
            "ShellNavigation": ("Navigation", "主导航"),
            "WorkspaceView": ("Main", "整理工作台主区域"),
            "ActivityView": ("Main", "活动与报告主区域"),
            "SettingsView": ("Main", "设置主区域"),
            "FilterGrid": ("Search", "分类结果筛选"),
        }

        for element_name, (landmark, accessible_name) in expected.items():
            with self.subTest(element=element_name):
                element = self._element_named(element_name)
                self.assertEqual(
                    landmark,
                    element.get("AutomationProperties.LandmarkType"),
                )
                self.assertEqual(
                    accessible_name,
                    element.get("AutomationProperties.Name"),
                )

    def test_key_controls_have_explicit_accessible_names(self) -> None:
        required_names = {
            "WorkspaceNavigationItem": "整理工作台",
            "ActivityNavigationItem": "活动与报告",
            "ChooseFolderButton": "选择轻小说目录",
            "ScanButton": "扫描并预览",
            "ResultSearchBox": "搜索分类结果",
            "ResultsList": "分类预览结果",
            "CandidateList": "候选系列列表",
            "SeriesEditBox": "手动修正系列名称",
            "SaveCorrectionButton": "保存系列修正",
            "CloseDetailButton": "关闭文件详情",
            "RetryDetailButton": "重新读取文件详情",
            "UsageHelpButton": "查看使用提示",
            "ApplyButton": "确认整理全部分类计划",
            "ReportHistoryList": "分类历史批次",
            "ReportItemsList": "所选分类报告条目",
            "LogsList": "当前会话活动日志",
            "RulesList": "自定义分类规则列表",
            "SaveSettingsButton": "保存设置",
            "NetworkProviderDescriptionText": "当前元数据来源",
        }

        for element_name, accessible_name in required_names.items():
            with self.subTest(element=element_name):
                self.assertEqual(
                    accessible_name,
                    self._element_named(element_name).get("AutomationProperties.Name"),
                )

    def test_large_regions_are_componentized(self) -> None:
        component_tags = {element.tag.rsplit("}", 1)[-1] for element in self.main_page.iter()}

        self.assertIn("FileDetailPane", component_tags)
        self.assertIn("WorkflowRail", component_tags)
        self.assertIsNone(
            next(
                (element for element in self.main_page.iter() if element.get(X_NAME) == "CandidateList"),
                None,
            )
        )

    def test_page_shortcuts_are_wired_to_handlers(self) -> None:
        shortcuts = {
            (
                element.get("Key"),
                element.get("Modifiers", ""),
                element.get("Invoked", ""),
            )
            for element in self.main_page.iter(f"{{{XAML_NAMESPACE}}}KeyboardAccelerator")
            if element.get("Invoked")
        }

        self.assertTrue(
            {
                ("Number1", "Control", "OnSectionShortcutInvoked"),
                ("Number2", "Control", "OnSectionShortcutInvoked"),
                ("Number3", "Control", "OnSectionShortcutInvoked"),
                ("F", "Control", "OnSearchShortcutInvoked"),
                ("F6", "", "OnCycleRegionForwardInvoked"),
                ("F6", "Shift", "OnCycleRegionBackwardInvoked"),
            }.issubset(shortcuts)
        )

    def test_control_shortcuts_are_declared_and_announced(self) -> None:
        expected = {
            "ChooseFolderButton": ("O", "Control", "Control+O"),
            "ScanButton": ("F5", "", "F5"),
            "ApplyButton": ("Enter", "Control", "Control+Enter"),
            "RefreshReportButton": ("F5", "", "F5"),
            "SaveSettingsButton": ("S", "Control", "Control+S"),
        }

        for element_name, (key, modifiers, announcement) in expected.items():
            with self.subTest(element=element_name):
                element = self._element_named(element_name)
                accelerators = list(element.iter(f"{{{XAML_NAMESPACE}}}KeyboardAccelerator"))
                self.assertEqual(1, len(accelerators))
                self.assertEqual(key, accelerators[0].get("Key"))
                self.assertEqual(modifiers, accelerators[0].get("Modifiers", ""))
                self.assertEqual(
                    announcement,
                    element.get("AutomationProperties.AcceleratorKey"),
                )

    def test_heading_styles_expose_document_hierarchy(self) -> None:
        heading_levels: dict[str, str] = {}
        for style in self.design_tokens.iter(f"{{{XAML_NAMESPACE}}}Style"):
            key = style.get(X_KEY)
            if not key:
                continue
            for setter in style.findall(f"{{{XAML_NAMESPACE}}}Setter"):
                if setter.get("Property") == "AutomationProperties.HeadingLevel":
                    heading_levels[key] = setter.get("Value", "")

        self.assertEqual("Level1", heading_levels.get("PageTitleTextStyle"))
        self.assertEqual("Level2", heading_levels.get("SectionTitleTextStyle"))

    def test_filter_scope_warning_is_available_without_a_tooltip(self) -> None:
        self.assertIn(
            "完整分类计划",
            self._element_named("ResultsList").get(
                "AutomationProperties.HelpText",
                "",
            ),
        )
        self.assertIn(
            "完整分类计划",
            self._element_named("ApplyButton").get(
                "AutomationProperties.HelpText",
                "",
            ),
        )

    def test_semantic_text_colors_meet_normal_text_contrast(self) -> None:
        for theme_name in ("Light", "Dark"):
            with self.subTest(theme=theme_name):
                theme = self._theme_dictionary(theme_name)
                colors = {
                    element.get(X_KEY): (element.text or "").strip()
                    for element in theme.findall(f"{{{XAML_NAMESPACE}}}Color")
                }
                transient_surface = next(
                    element
                    for element in theme.findall(f"{{{XAML_NAMESPACE}}}AcrylicBrush")
                    if element.get(X_KEY) == "TransientSurfaceBrush"
                )
                background = self._rgb(transient_surface.get("FallbackColor", ""))

                for key in (
                    "AccentColor",
                    "SuccessColor",
                    "WarningColor",
                    "ErrorColor",
                ):
                    ratio = self._contrast_ratio(self._rgb(colors[key]), background)
                    self.assertGreaterEqual(
                        ratio,
                        4.5,
                        f"{theme_name} 的 {key} 对比度只有 {ratio:.2f}:1。",
                    )

    def test_high_contrast_uses_system_text_and_window_colors(self) -> None:
        theme = self._theme_dictionary("HighContrast")
        colors = {
            element.get(X_KEY): (element.text or "").strip() for element in theme.findall(f"{{{XAML_NAMESPACE}}}Color")
        }
        self.assertIn("SystemColorHighlightColor", colors["AccentColor"])
        for key in ("SuccessColor", "WarningColor", "ErrorColor"):
            self.assertIn("SystemColorWindowTextColor", colors[key])
        for key in (
            "LowCardBackgroundColor",
            "CardBackgroundColor",
            "ElevatedCardBackgroundColor",
        ):
            self.assertIn("SystemColorWindowColor", colors[key])

    def _theme_dictionary(self, theme_name: str) -> ElementTree.Element:
        for element in self.design_tokens.iter(f"{{{XAML_NAMESPACE}}}ResourceDictionary"):
            if element.get(X_KEY) == theme_name:
                return element
        self.fail(f"DesignTokens.xaml 缺少 {theme_name} 主题字典。")

    @staticmethod
    def _rgb(value: str) -> tuple[int, int, int]:
        value = value.removeprefix("#")
        if len(value) == 8:
            value = value[2:]
        if len(value) != 6:
            raise AssertionError(f"无法解析颜色 {value!r}。")
        return (
            int(value[0:2], 16),
            int(value[2:4], 16),
            int(value[4:6], 16),
        )

    @staticmethod
    def _contrast_ratio(
        foreground: tuple[int, int, int],
        background: tuple[int, int, int],
    ) -> float:
        def luminance(color: tuple[int, int, int]) -> float:
            channels = []
            for channel in color:
                normalized = channel / 255
                channels.append(normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4)
            return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

        lighter = max(luminance(foreground), luminance(background))
        darker = min(luminance(foreground), luminance(background))
        return (lighter + 0.05) / (darker + 0.05)


if __name__ == "__main__":
    unittest.main()
