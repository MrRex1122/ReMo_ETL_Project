from pathlib import Path


def test_no_selected_mode_assignment_left_in_sidebar_ui():
    app_source = Path('app.py').read_text(encoding='utf-8')
    assert 'selected_mode' not in app_source


def test_no_explicit_matcher_mode_select_key_to_avoid_duplicate_widget_key():
    app_source = Path('app.py').read_text(encoding='utf-8')
    assert 'key="matcher_mode_select"' not in app_source


def test_processing_results_are_not_started_via_removed_sync_function():
    app_source = Path('app.py').read_text(encoding='utf-8')
    assert 'process_uploaded_file(' not in app_source


def test_processing_runs_history_ui_is_present():
    app_source = Path('app.py').read_text(encoding='utf-8')
    assert 'История прогонов' in app_source
    assert 'Прогон запущен в фоне' in app_source
