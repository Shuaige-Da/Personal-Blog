from pathlib import Path
import unittest


TEMPLATE = Path(__file__).resolve().parents[1] / "frontend" / "templates" / "admin" / "admin.html"


class AdminSettingsTemplateTests(unittest.TestCase):
    def test_settings_page_keeps_two_column_equal_height_layout(self):
        template = TEMPLATE.read_text(encoding="utf-8")

        self.assertIn(".settings-layout", template)
        self.assertIn(
            "grid-template-columns: minmax(320px, 0.35fr) minmax(0, 1fr);",
            template,
        )
        self.assertIn(".settings-nav-card", template)
        self.assertIn("height: 720px;", template)
        self.assertIn(".settings-detail-column .settings-panel", template)

    def test_single_background_panel_uses_compact_workspace(self):
        template = TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("single-bg-workspace", template)
        self.assertIn("single-bg-library", template)
        self.assertIn("single-bg-form", template)
        self.assertIn("server-bg-grid", template)
        self.assertNotIn('id="background-server-panel" class="single-bg-library" hidden', template)
        self.assertNotIn("使用选中的服务器背景", template)
        self.assertNotIn("background_library_submit", template)

    def test_homepage_font_and_color_controls_use_stable_grid(self):
        template = TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("homepage-settings-form", template)
        self.assertIn("homepage-style-grid", template)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(150px, 0.34fr);", template)
        self.assertIn(".homepage-font-field .rw-select-shell", template)
        self.assertIn(".settings-detail-column #section-homepage:not([hidden])", template)
        self.assertIn("height: auto;", template)


if __name__ == "__main__":
    unittest.main()
