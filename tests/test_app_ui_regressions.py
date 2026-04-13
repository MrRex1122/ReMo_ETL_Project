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
        self.assertIn("запущен в фоне.", app_source)
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

    def test_main_kp_tab_uses_trimmed_result_view(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        processing_worker_source = Path("processing_worker.py").read_text(encoding="utf-8")
        self.assertIn("_build_main_kp_result_df", app_source)
        self.assertIn("Полная таблица доступна во вкладке «Debug / Admin».", app_source)
        self.assertIn("main_result_df = _build_main_kp_result_df(df)", app_source)
        self.assertIn("show_corrections_table(df, visible_columns=list(main_result_df.columns))", app_source)
        self.assertIn('if "Найденная номенклатура" in visible_columns:', processing_worker_source)

    def test_main_kp_view_renders_static_full_width_result_without_pagination_controls(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("def _render_static_result_table", app_source)
        self.assertIn("_render_static_result_table(main_result_df)", app_source)
        self.assertNotIn('page_size = st.slider("Строк на странице"', app_source)
        self.assertNotIn('page = st.slider("Страница"', app_source)
        self.assertNotIn('show_filter = st.selectbox(', app_source)
        self.assertNotIn('sort_by = st.selectbox("Сортировать по"', app_source)

    def test_debug_tab_exposes_full_result_downloads(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("Полная таблица результата", app_source)
        self.assertIn("download_full_result_excel_", app_source)
        self.assertIn("download_full_result_csv_", app_source)

    def test_main_run_uses_lite_diagnostics_and_debug_mentions_reconstruction(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        processing_worker_source = Path("processing_worker.py").read_text(encoding="utf-8")
        self.assertIn('stats["diagnostics_mode"] = "lite"', processing_worker_source)
        self.assertIn('stats["runtime_diagnostics_saved"] = False', processing_worker_source)
        self.assertIn("build_runtime_diagnostics=False", processing_worker_source)
        self.assertIn("runtime-диагностика не сохранялась автоматически", app_source)

    def test_taxonomy_snapshot_ui_ensures_fresh_snapshot_and_versioned_download_names(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("ensure_search_taxonomy_snapshot(clean_dir)", app_source)
        self.assertIn("_taxonomy_snapshot_download_filename(tree_path)", app_source)
        self.assertIn("_taxonomy_snapshot_download_filename(branch_summary_path)", app_source)
        self.assertNotIn("file_name=tree_path.name", app_source)
        self.assertNotIn("file_name=branch_summary_path.name", app_source)

    def test_taxonomy_snapshot_ui_shows_top_20_suspicious_branches_and_exports_full_audit(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("_build_branch_cleanup_audit_df", app_source)
        self.assertIn("Подозрительные ветки для cleanup", app_source)
        self.assertIn("top-20 веток", app_source)
        self.assertIn("Выгрузка ниже содержит весь список подозрительных веток", app_source)
        self.assertIn("suspicious_df.head(20)", app_source)
        self.assertIn("Скачать все подозрительные ветки", app_source)
        self.assertIn("download_taxonomy_branch_cleanup_audit_csv", app_source)

    def test_taxonomy_preview_ui_supports_dry_run_without_search_rebuild(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("build_search_taxonomy_preview", app_source)
        self.assertIn("_render_search_taxonomy_preview_section", app_source)
        self.assertIn("Taxonomy preview без rebuild", app_source)
        self.assertIn("Построить taxonomy preview без rebuild", app_source)
        self.assertIn("taxonomy_preview_branch_cleanup_audit.csv", app_source)
        self.assertIn("preview_audit_df.head(20)", app_source)

    def test_taxonomy_preview_ui_supports_branch_probe_for_selected_branches(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("build_search_taxonomy_branch_probe", app_source)
        self.assertIn("Branch probe по выбранным веткам", app_source)
        self.assertIn("Построить branch probe по выбранным веткам", app_source)
        self.assertIn("taxonomy_probe_branch_cleanup_audit.csv", app_source)
        self.assertIn("probe_audit_df.head(20)", app_source)
        self.assertIn("preview_summary_df", app_source)
        self.assertIn("Или добавьте ветки вручную", app_source)
        self.assertIn("taxonomy_branch_probe_manual_branches", app_source)


        self.assertIn("get_search_taxonomy_probe_report_path", app_source)
        self.assertIn("download_taxonomy_probe_report_json", app_source)
        self.assertIn("probe_report.get(\"summary_lines\")", app_source)
        self.assertIn("probe_report_path", app_source)

    def test_taxonomy_preview_ui_supports_gemini_bootstrap_draft(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("build_search_taxonomy_bootstrap_draft", app_source)
        self.assertIn("Gemini draft", app_source)
        self.assertIn("Gemini draft по branch probe", app_source)
        self.assertIn("taxonomy_bootstrap_draft.csv", app_source)
        self.assertIn("draft_df.head(20)", app_source)

if __name__ == "__main__":
    unittest.main()
