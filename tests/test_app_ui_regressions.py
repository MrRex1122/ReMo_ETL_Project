import unittest
from pathlib import Path


class AppUiRegressionTests(unittest.TestCase):
    def test_no_selected_mode_assignment_left_in_sidebar_ui(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertNotIn("selected_mode", app_source)

    def test_no_explicit_matcher_mode_select_key_to_avoid_duplicate_widget_key(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertNotIn('key="matcher_mode_select"', app_source)

    def test_processing_results_are_not_started_via_removed_sync_function(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertNotIn("process_uploaded_file(", app_source)

    def test_processing_runs_history_ui_is_present(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("История прогонов", app_source)
        self.assertIn("Прогон запущен в фоне", app_source)

    def test_catalog_coverage_audit_ui_is_present(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        processing_runs_source = Path("processing_runs.py").read_text(encoding="utf-8")
        self.assertIn("coverage_audit.json", processing_runs_source)
        self.assertIn("Проверить покрытие каталога", app_source)

    def test_match_diagnostics_ui_is_present(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        processing_runs_source = Path("processing_runs.py").read_text(encoding="utf-8")
        self.assertIn("match_diagnostics.json", processing_runs_source)
        self.assertIn("Диагностика причин ненахода", app_source)
        self.assertIn("Пересчитать диагностику", app_source)


if __name__ == "__main__":
    unittest.main()
