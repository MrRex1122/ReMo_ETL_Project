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
        self.assertIn("Скачать весь аудит", app_source)
        self.assertIn("Сводка по gap reason", app_source)
        self.assertIn("Вне audit scope", app_source)

    def test_match_diagnostics_ui_is_present(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        processing_runs_source = Path("processing_runs.py").read_text(encoding="utf-8")
        self.assertIn("match_diagnostics.json", processing_runs_source)
        self.assertIn("Диагностика причин ненахода", app_source)
        self.assertIn("Пересчитать диагностику", app_source)
        self.assertIn("Скачать всю диагностику", app_source)
        self.assertIn("Сводка по root cause", app_source)
        self.assertIn("not audited family", app_source)


    def test_search_catalog_export_ui_is_present(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("Выгрузить поисковую БД в Cloudflare R2", app_source)
        self.assertIn("Открыть поисковую БД в Cloudflare R2", app_source)
        self.assertNotIn("Подготовить ссылку на выгрузку поисковой БД", app_source)
        self.assertNotIn("Выгрузить БД в Google Drive (CSV)", app_source)

    def test_duckdb_whole_category_retrieval_ui_is_present(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("DuckDB whole-category retrieval by derived branch", app_source)
        self.assertIn("Advanced matcher controls", app_source)
        self.assertIn("Retrieval mode: `whole category` by derived branch.", app_source)

    def test_processing_run_cancel_ui_is_present(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("Остановить прогон", app_source)


if __name__ == "__main__":
    unittest.main()
