import unittest
from pathlib import Path


class AppUiRegressionTests(unittest.TestCase):
    def test_main_ui_is_reorganized_around_kp_fill_and_debug_admin_tabs(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn('st.tabs(["📄 Заполнение КП", "🧪 Debug / Admin", "📊 История"])', app_source)
        self.assertNotIn('st.tabs(["📤 Загрузка", "📋 Результаты", "📊 История"])', app_source)

    def test_sidebar_is_simplified_and_no_longer_hosts_admin_controls(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("📄 Основной сценарий: вкладка «Заполнение КП».", app_source)
        self.assertIn("🧪 Технические действия: вкладка «Debug / Admin».", app_source)
        self.assertNotIn("⚙️ Настройки", app_source)

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
        self.assertIn("Откройте его на вкладке «Заполнение КП».", app_source)

    def test_catalog_coverage_audit_ui_is_present(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        processing_runs_source = Path("processing_runs.py").read_text(encoding="utf-8")
        self.assertIn("coverage_audit.json", processing_runs_source)
        self.assertIn("Проверить покрытие каталога", app_source)
        self.assertIn("Скачать весь аудит", app_source)
        self.assertIn("Сводка по gap reason", app_source)
        self.assertIn("Вне audit scope", app_source)
        self.assertIn("Аудит строится в фоне", app_source)
        self.assertIn("Осталось примерно", app_source)
        self.assertIn("_begin_catalog_audit_task", app_source)
        self.assertIn("Coverage audit progress", app_source)
        self.assertIn("@st.fragment(run_every=CATALOG_AUDIT_FRAGMENT_REFRESH_INTERVAL)", app_source)
        self.assertNotIn('with st.spinner("Проверяю покрытие каталога по использованной БД...")', app_source)

    def test_match_diagnostics_ui_is_present(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        processing_runs_source = Path("processing_runs.py").read_text(encoding="utf-8")
        self.assertIn("match_diagnostics.json", processing_runs_source)
        self.assertIn("Диагностика причин ненахода", app_source)
        self.assertIn("Пересчитать диагностику", app_source)
        self.assertIn("Скачать всю диагностику", app_source)
        self.assertIn("Сводка по root cause", app_source)
        self.assertIn("Сводка по resolver", app_source)
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

    def test_active_run_status_uses_fragment_refresh_instead_of_page_reload(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("@st.fragment(run_every=ACTIVE_RUN_FRAGMENT_REFRESH_INTERVAL)", app_source)
        self.assertNotIn("location.reload()", app_source)
        self.assertNotIn("streamlit.components.v1", app_source)

    def test_result_download_buttons_use_stable_run_based_filenames(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("download_result_excel_", app_source)
        self.assertIn("download_result_csv_", app_source)
        self.assertNotIn("result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", app_source)
        self.assertNotIn("result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", app_source)


if __name__ == "__main__":
    unittest.main()
