"""
ReMo Matcher UI
Streamlit интерфейс для семантического сопоставления номенклатуры
"""

import streamlit as st
import streamlit.components.v1 as components
from streamlit.errors import StreamlitSecretNotFoundError
import pandas as pd
import os
from matcher import ReMoMatcher, MISSING_POSITION_TEXT
from pathlib import Path
from datetime import datetime
import sqlite3
import logging
import io
import json
import threading
from typing import Any
from cloudflare_r2_export import upload_file_to_r2
from catalog_search import get_search_catalog_readiness, is_search_catalog_path, refresh_search_catalog
from catalog_coverage_audit import (
    build_catalog_coverage_audit,
    is_catalog_coverage_audit_fresh,
    prepare_catalog_coverage_audit_table,
    prepare_catalog_coverage_family_table,
    prepare_catalog_gap_reason_table,
)
from match_diagnostics import (
    apply_match_diagnostics_summary_to_stats,
    apply_match_diagnostics_to_result_dataframe,
    build_match_diagnostics_payload,
    enrich_match_diagnostics_payload,
    is_match_diagnostics_fresh,
    prepare_match_diagnostics_reason_table,
    prepare_match_diagnostics_root_cause_table,
    prepare_match_diagnostics_stage_table,
    prepare_match_diagnostics_table,
    reconstruct_match_diagnostics,
)
from config import (
    get_catalog_csv_path,
    get_matcher_cache_db_path,
    get_matcher_gemini_chunk_size,
    get_matcher_gemini_max_chunks,
    get_matcher_gemini_shortlist_limit,
    get_matcher_local_recall_pool,
    get_matcher_skip_weak_shortlist,
    get_upload_dir,
)
from catalog_merge import get_catalog_readiness, get_merged_catalog_path, refresh_merged_catalog
from catalog_snapshot import prepare_catalog_duplicate_report
from google_drive_sync import sync_drive_folder_csvs
from etl_pipeline import PriceETL
from main import convert_csv
from processing_runs import (
    build_run_artifacts,
    create_processing_run,
    get_latest_active_processing_run,
    get_preferred_run_for_restore,
    get_processing_run,
    has_processing_run_draft,
    list_processing_runs,
    load_processing_run_coverage_audit,
    load_processing_run_dataframe,
    load_processing_run_match_diagnostics,
    load_processing_run_progress,
    load_processing_run_stats,
    mark_processing_run_completed,
    mark_processing_run_failed,
    mark_processing_run_started,
    mark_stale_running_runs_as_interrupted,
    register_processing_run_thread,
    save_processing_run_draft,
    unregister_processing_run_thread,
    write_processing_run_coverage_audit,
    write_processing_run_match_diagnostics,
    write_processing_run_error,
    write_processing_run_progress,
    write_processing_run_result,
)
from snapshot_export import (
    build_public_export_url,
    build_snapshot_export_basename,
    get_snapshot_xlsx_status,
    start_snapshot_xlsx_build,
)

# ============ ЛОГИРОВАНИЕ ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
ACTIVE_RUN_AUTOREFRESH_MS = 5000

# ============ КОНФИГУРАЦИЯ ============
st.set_page_config(
    page_title="ReMo Matcher",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS стили
st.markdown("""
<style>
    .success-box {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 4px;
        padding: 12px;
        margin: 10px 0;
    }
    .error-box {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        border-radius: 4px;
        padding: 12px;
        margin: 10px 0;
    }
    .info-box {
        background-color: #d1ecf1;
        border: 1px solid #bee5eb;
        border-radius: 4px;
        padding: 12px;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

# ============ ИНИЦИАЛИЗАЦИЯ SESSION STATE ============

if 'matcher' not in st.session_state:
    st.session_state.matcher = None
if 'df_processed' not in st.session_state:
    st.session_state.df_processed = None
if 'stats' not in st.session_state:
    st.session_state.stats = None
if 'corrections' not in st.session_state:
    st.session_state.corrections = {}
if 'db_csv_path' not in st.session_state:
    st.session_state.db_csv_path = str(get_merged_catalog_path(get_upload_dir() / "clean"))
if 'matcher_db_csv' not in st.session_state:
    st.session_state.matcher_db_csv = None
if 'matcher_parallel_requests' not in st.session_state:
    st.session_state.matcher_parallel_requests = 1
if 'matcher_mode' not in st.session_state:
    st.session_state.matcher_mode = 'exact'
if 'matcher_gemini_shortlist_limit' not in st.session_state:
    st.session_state.matcher_gemini_shortlist_limit = get_matcher_gemini_shortlist_limit()
if 'matcher_gemini_chunk_size' not in st.session_state:
    st.session_state.matcher_gemini_chunk_size = get_matcher_gemini_chunk_size()
if 'matcher_gemini_max_chunks' not in st.session_state:
    st.session_state.matcher_gemini_max_chunks = get_matcher_gemini_max_chunks()
if 'matcher_local_recall_pool' not in st.session_state:
    st.session_state.matcher_local_recall_pool = get_matcher_local_recall_pool()
if 'matcher_skip_weak_shortlist' not in st.session_state:
    st.session_state.matcher_skip_weak_shortlist = get_matcher_skip_weak_shortlist()
if 'matcher_settings_signature' not in st.session_state:
    st.session_state.matcher_settings_signature = None
if 'show_results' not in st.session_state:
    st.session_state.show_results = False
if 'show_corrections' not in st.session_state:
    st.session_state.show_corrections = False
if 'active_run_id' not in st.session_state:
    st.session_state.active_run_id = None
if 'active_run_status' not in st.session_state:
    st.session_state.active_run_status = None
if 'active_run_loaded_at' not in st.session_state:
    st.session_state.active_run_loaded_at = None
if 'active_run_mode' not in st.session_state:
    st.session_state.active_run_mode = "view"
if 'last_run_restore_attempted' not in st.session_state:
    st.session_state.last_run_restore_attempted = False
if 'processing_thread_started_run_id' not in st.session_state:
    st.session_state.processing_thread_started_run_id = None
if 'active_run_auto_refresh_enabled' not in st.session_state:
    st.session_state.active_run_auto_refresh_enabled = False

if 'catalog_snapshot_bundle' not in st.session_state:
    st.session_state.catalog_snapshot_bundle = None
if 'catalog_snapshot_xlsx_status' not in st.session_state:
    st.session_state.catalog_snapshot_xlsx_status = "idle"
if 'catalog_snapshot_xlsx_path' not in st.session_state:
    st.session_state.catalog_snapshot_xlsx_path = None
if 'catalog_snapshot_xlsx_url' not in st.session_state:
    st.session_state.catalog_snapshot_xlsx_url = None
if 'catalog_snapshot_drive_csv_url' not in st.session_state:
    st.session_state.catalog_snapshot_drive_csv_url = None
if 'catalog_snapshot_drive_csv_name' not in st.session_state:
    st.session_state.catalog_snapshot_drive_csv_name = None
if 'catalog_snapshot_r2_csv_url' not in st.session_state:
    st.session_state.catalog_snapshot_r2_csv_url = None
if 'catalog_snapshot_r2_csv_key' not in st.session_state:
    st.session_state.catalog_snapshot_r2_csv_key = None
if 'search_catalog_export_url' not in st.session_state:
    st.session_state.search_catalog_export_url = None
if 'search_catalog_export_name' not in st.session_state:
    st.session_state.search_catalog_export_name = None




def _catalog_source_path() -> Path:
    """Вернуть актуальный источник каталога для matcher и выгрузки."""
    clean_dir = get_upload_dir() / "clean"
    if clean_dir.exists():
        return get_merged_catalog_path(clean_dir)
    return get_catalog_csv_path(st.session_state.get('db_csv_path'))


def _matcher_catalog_source_path() -> Path:
    """Выбрать источник для matcher: свежий search CSV или fallback на merged."""
    merged_path = _catalog_source_path()
    search_readiness = get_search_catalog_readiness(merged_path)
    if search_readiness.state == "ready":
        logger.info("📄 Matcher using prepared search catalog: %s", search_readiness.search_path)
        return search_readiness.search_path
    logger.info(
        "📄 Matcher falling back to merged catalog: %s reason=%s",
        search_readiness.merged_path,
        search_readiness.reason or "search catalog is not ready",
    )
    return search_readiness.merged_path



def _get_gemini_api_key() -> str | None:
    """Безопасно получить API-ключ из secrets/env без падения при отсутствии secrets.toml."""
    try:
        secret_value = st.secrets.get("GEMINI_API_KEY")
    except StreamlitSecretNotFoundError:
        secret_value = None
    except Exception as e:
        logger.warning(f"⚠️ Не удалось прочитать Streamlit secrets: {e}")
        secret_value = None

    return secret_value or os.getenv("GEMINI_API_KEY")


def _get_drive_sync_config() -> tuple[str | None, str | None]:
    """Получить конфиг Google Drive sync из secrets/env без UI-ввода."""
    folder = None
    service_account_json = None

    try:
        folder = st.secrets.get("GOOGLE_DRIVE_FOLDER_ID") or st.secrets.get("GOOGLE_DRIVE_FOLDER_URL")
        service_account_secret = st.secrets.get("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON")
        if service_account_secret:
            service_account_json = str(service_account_secret)
        elif "GOOGLE_DRIVE_SERVICE_ACCOUNT" in st.secrets:
            service_account_json = json.dumps(dict(st.secrets["GOOGLE_DRIVE_SERVICE_ACCOUNT"]))
    except StreamlitSecretNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"⚠️ Не удалось прочитать Google Drive secrets: {e}")

    folder = folder or os.getenv("GOOGLE_DRIVE_FOLDER_ID") or os.getenv("GOOGLE_DRIVE_FOLDER_URL")
    service_account_json = service_account_json or os.getenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON")

    return folder, service_account_json


def _get_drive_export_config() -> tuple[str | None, str | None]:
    """Получить конфиг Google Drive для выгрузки артефактов БД."""
    folder = None
    service_account_json = None

    try:
        folder = (
            st.secrets.get("GOOGLE_DRIVE_EXPORT_FOLDER_ID")
            or st.secrets.get("GOOGLE_DRIVE_EXPORT_FOLDER_URL")
        )
        service_account_secret = st.secrets.get("GOOGLE_DRIVE_EXPORT_SERVICE_ACCOUNT_JSON")
        if service_account_secret:
            service_account_json = str(service_account_secret)
        elif "GOOGLE_DRIVE_EXPORT_SERVICE_ACCOUNT" in st.secrets:
            service_account_json = json.dumps(dict(st.secrets["GOOGLE_DRIVE_EXPORT_SERVICE_ACCOUNT"]))
    except StreamlitSecretNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"⚠️ Не удалось прочитать Google Drive export secrets: {e}")

    if not service_account_json:
        try:
            shared_service_account_secret = st.secrets.get("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON")
            if shared_service_account_secret:
                service_account_json = str(shared_service_account_secret)
            elif "GOOGLE_DRIVE_SERVICE_ACCOUNT" in st.secrets:
                service_account_json = json.dumps(dict(st.secrets["GOOGLE_DRIVE_SERVICE_ACCOUNT"]))
        except StreamlitSecretNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"⚠️ Не удалось прочитать общий Google Drive service account: {e}")

    folder = folder or os.getenv("GOOGLE_DRIVE_EXPORT_FOLDER_ID") or os.getenv("GOOGLE_DRIVE_EXPORT_FOLDER_URL")
    service_account_json = (
        service_account_json
        or os.getenv("GOOGLE_DRIVE_EXPORT_SERVICE_ACCOUNT_JSON")
        or os.getenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON")
    )

    return folder, service_account_json


def _get_cloudflare_r2_export_config() -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Получить конфиг Cloudflare R2 для выгрузки больших артефактов."""
    account_id = None
    bucket = None
    access_key_id = None
    secret_access_key = None
    public_base_url = None

    try:
        account_id = st.secrets.get("CLOUDFLARE_R2_ACCOUNT_ID")
        bucket = st.secrets.get("CLOUDFLARE_R2_BUCKET")
        access_key_id = st.secrets.get("CLOUDFLARE_R2_ACCESS_KEY_ID")
        secret_access_key = st.secrets.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY")
        public_base_url = st.secrets.get("CLOUDFLARE_R2_PUBLIC_BASE_URL")
    except StreamlitSecretNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"⚠️ Не удалось прочитать Cloudflare R2 secrets: {e}")

    account_id = account_id or os.getenv("CLOUDFLARE_R2_ACCOUNT_ID")
    bucket = bucket or os.getenv("CLOUDFLARE_R2_BUCKET")
    access_key_id = access_key_id or os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID")
    secret_access_key = secret_access_key or os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY")
    public_base_url = public_base_url or os.getenv("CLOUDFLARE_R2_PUBLIC_BASE_URL")

    return account_id, bucket, access_key_id, secret_access_key, public_base_url

def _validate_runtime_readiness(db_csv: str) -> list[str]:
    """Проверить готовность приложения к обработке перед запуском matcher."""
    issues = []

    api_key = _get_gemini_api_key()
    if not api_key:
        issues.append("Не задан GEMINI_API_KEY")

    readiness = get_catalog_readiness(db_csv)
    if readiness.state != "ready":
        issues.append(readiness.reason or f"БД не готова: {readiness.state}")

    return issues


def _safe_matcher_mode_select(current_mode: str, mode_options: list[str]) -> str:
    """Безопасно получить режим matcher из selectbox без падения UI."""
    fallback_mode = current_mode if current_mode in mode_options else "exact"
    try:
        return st.selectbox(
            "Режим сопоставления",
            options=mode_options,
            index=mode_options.index(fallback_mode),
            format_func=lambda value: "Точный матч" if value == "exact" else "Аналог/замена",
            help=(
                "exact: только строгие совпадения по типу товара. "
                "analog: допускает близкие аналоги, но не подменяет тип товара "
                "(например, патч-корд не заменяется витой парой в бухте)."
            ),
        )
    except Exception as e:
        logger.error("❌ Ошибка рендера выбора режима matcher, применён fallback '%s': %s", fallback_mode, e)
        st.warning("⚠️ Не удалось отрисовать selector режима matcher, применён fallback.")
        return fallback_mode

def _current_matcher_runtime_settings() -> dict[str, Any]:
    return {
        "parallel_requests": int(st.session_state.get('matcher_parallel_requests', 1)),
        "match_mode": str(st.session_state.get('matcher_mode', 'exact')),
        "gemini_shortlist_limit": int(
            st.session_state.get('matcher_gemini_shortlist_limit', get_matcher_gemini_shortlist_limit())
        ),
        "gemini_chunk_size": int(
            st.session_state.get('matcher_gemini_chunk_size', get_matcher_gemini_chunk_size())
        ),
        "gemini_max_chunks": int(
            st.session_state.get('matcher_gemini_max_chunks', get_matcher_gemini_max_chunks())
        ),
        "local_recall_pool": int(
            st.session_state.get('matcher_local_recall_pool', get_matcher_local_recall_pool())
        ),
        "skip_weak_shortlist": bool(
            st.session_state.get('matcher_skip_weak_shortlist', get_matcher_skip_weak_shortlist())
        ),
    }


def _create_matcher_instance(db_csv: str, settings: dict[str, Any]) -> ReMoMatcher:
    api_key = _get_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY не установлен")
    if not Path(db_csv).exists():
        raise FileNotFoundError(f"Файл не найден: {db_csv}")
    return ReMoMatcher(
        api_key,
        db_csv,
        parallel_requests=int(settings.get("parallel_requests", 1)),
        match_mode=str(settings.get("match_mode", "exact")),
        gemini_shortlist_limit=int(settings.get("gemini_shortlist_limit", get_matcher_gemini_shortlist_limit())),
        gemini_chunk_size=int(settings.get("gemini_chunk_size", get_matcher_gemini_chunk_size())),
        gemini_max_chunks=int(settings.get("gemini_max_chunks", get_matcher_gemini_max_chunks())),
        local_recall_pool=int(settings.get("local_recall_pool", get_matcher_local_recall_pool())),
        skip_weak_shortlist=bool(settings.get("skip_weak_shortlist", get_matcher_skip_weak_shortlist())),
    )


def _resolve_catalog_source_for_run() -> tuple[Path, str]:
    catalog_path = _matcher_catalog_source_path()
    source_kind = "search" if is_search_catalog_path(catalog_path) else "merged"
    return catalog_path, source_kind


def get_matcher() -> ReMoMatcher:
    """Получить или инициализировать экземпляр matcher"""
    db_csv = str(_matcher_catalog_source_path())
    runtime_settings = _current_matcher_runtime_settings()
    settings_signature = (
        runtime_settings["parallel_requests"],
        runtime_settings["match_mode"],
        runtime_settings["gemini_shortlist_limit"],
        runtime_settings["gemini_chunk_size"],
        runtime_settings["gemini_max_chunks"],
        runtime_settings["local_recall_pool"],
        runtime_settings["skip_weak_shortlist"],
    )
    needs_reinit = (
        st.session_state.matcher is None
        or st.session_state.matcher_db_csv != db_csv
        or st.session_state.matcher_settings_signature != settings_signature
    )

    if needs_reinit:
        logger.info("🔄 Инициализация ReMoMatcher...")
        with st.spinner("⏳ Инициализация ReMo Matcher..."):
            try:
                st.session_state.matcher = _create_matcher_instance(db_csv, runtime_settings)
                st.session_state.matcher_db_csv = db_csv
                st.session_state.matcher_settings_signature = settings_signature
                logger.info("✓ ReMoMatcher успешно инициализирован")
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации: {e}", exc_info=True)
                st.error(f"❌ Ошибка инициализации: {str(e)}")
                st.stop()
    
    return st.session_state.matcher


def _run_processing_job(run_id: str, matcher_settings: dict[str, Any]) -> None:
    try:
        run = get_processing_run(run_id)
        if run is None:
            raise RuntimeError(f"Run not found: {run_id}")

        mark_processing_run_started(run_id)
        write_processing_run_progress(
            run_id,
            stage="matcher_init",
            percent=0.02,
            message="Инициализация matcher и загрузка каталога",
        )
        logger.info("🚀 Processing run started in background: %s", run_id)

        matcher = _create_matcher_instance(str(run.catalog_source_path), matcher_settings)
        artifacts = build_run_artifacts(run_id)
        write_processing_run_progress(
            run_id,
            stage="processing",
            percent=0.08,
            message="Matcher готов, начинается обработка файла",
        )
        logger.info("⏳ Background run %s: processing %s", run_id, run.input_file_path)

        def _progress_callback(
            *,
            stage: str,
            current: int | None = None,
            total: int | None = None,
            message: str | None = None,
        ) -> None:
            percent = None
            if stage == "matching" and total:
                percent = 0.08 + (0.87 * (max(0, min(int(current or 0), int(total))) / max(1, int(total))))
            elif stage == "reading_excel":
                percent = 0.08
            elif stage == "saving_results":
                percent = 0.97
            write_processing_run_progress(
                run_id,
                stage=stage,
                current=current,
                total=total,
                message=message,
                percent=percent,
            )

        df_result, stats = matcher.process_excel(
            str(run.input_file_path),
            output_path=str(artifacts.result_xlsx_path),
            progress_callback=_progress_callback,
        )

        diagnostics_rows = getattr(matcher, "last_match_diagnostics_rows", None)
        write_processing_run_progress(
            run_id,
            stage="saving_results",
            current=int(stats.get("total", len(df_result))),
            total=int(stats.get("total", len(df_result))),
            percent=0.98,
            message="Сохранение результатов и runtime-диагностики",
        )
        diagnostics_payload = None
        try:
            if isinstance(diagnostics_rows, list):
                diagnostics_payload = build_match_diagnostics_payload(
                    diagnostics_rows,
                    run_id=run_id,
                )
            else:
                diagnostics_payload = reconstruct_match_diagnostics(
                    df_result,
                    run_id=run_id,
                )
            write_processing_run_match_diagnostics(run_id, diagnostics_payload)
            apply_match_diagnostics_to_result_dataframe(df_result, diagnostics_payload)
            stats = apply_match_diagnostics_summary_to_stats(stats, diagnostics_payload)
        except Exception:
            logger.exception("Failed to build or apply diagnostics for run %s", run_id)

        write_processing_run_result(run_id, df_result, stats)
        rows_total = int(stats.get("total", len(df_result)))
        found_count = int(stats.get("found", 0))
        missing_count = int(stats.get("not_found", 0))
        requires_review_count = int(
            (df_result.get("Требует проверки", pd.Series(dtype=object)).fillna("").astype(str).str.lower() == "да").sum()
        )
        mark_processing_run_completed(
            run_id,
            result_csv_path=artifacts.result_csv_path,
            stats_json_path=artifacts.stats_json_path,
            rows_total=rows_total,
            found_count=found_count,
            missing_count=missing_count,
            requires_review_count=requires_review_count,
        )
        write_processing_run_progress(
            run_id,
            stage="completed",
            current=rows_total,
            total=rows_total,
            percent=1.0,
            message="Обработка завершена",
        )
        logger.info("✅ Processing run completed: %s", run_id)
        logger.info(
            "ℹ️ Coverage audit is not built synchronously during background run %s; use the manual audit action in Results.",
            run_id,
        )
    except Exception as exc:
        logger.error("❌ Processing run failed: %s", run_id, exc_info=True)
        error_text = str(exc)
        try:
            write_processing_run_error(run_id, error_text)
            write_processing_run_progress(
                run_id,
                stage="failed",
                message=error_text,
            )
        except Exception:
            logger.exception("Failed to write run error file: %s", run_id)
        mark_processing_run_failed(run_id, error_text)
    finally:
        unregister_processing_run_thread(run_id)


def _start_processing_run(uploaded_file) -> str:
    logger.info("📄 Обработка файла: %s", uploaded_file.name)
    catalog_source_path, source_kind = _resolve_catalog_source_for_run()
    run = create_processing_run(
        input_filename=uploaded_file.name,
        catalog_source_path=catalog_source_path,
        catalog_source_kind=source_kind,
    )
    artifacts = build_run_artifacts(run.run_id)
    with open(artifacts.input_path, 'wb') as fh:
        fh.write(uploaded_file.getbuffer())
    write_processing_run_progress(
        run.run_id,
        stage="queued",
        percent=0.0,
        message="Прогон создан и ожидает запуска фонового потока",
    )

    matcher_settings = _current_matcher_runtime_settings()
    worker = threading.Thread(
        target=_run_processing_job,
        args=(run.run_id, matcher_settings),
        daemon=True,
        name=f"processing-run-{run.run_id}",
    )
    register_processing_run_thread(run.run_id, worker)
    worker.start()
    st.session_state.active_run_id = run.run_id
    st.session_state.active_run_status = "queued"
    st.session_state.active_run_loaded_at = None
    st.session_state.active_run_mode = "view"
    st.session_state.processing_thread_started_run_id = run.run_id
    st.session_state.df_processed = None
    st.session_state.stats = None
    logger.info("🧵 Background processing thread started: run_id=%s source=%s", run.run_id, source_kind)
    return run.run_id


def save_uploaded_catalog(uploaded_catalog, run_etl: bool = False) -> Path:
    """Сохранить загруженный CSV каталога в рабочую папку данных."""
    storage_dir = get_upload_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)

    source_name = Path(uploaded_catalog.name).name
    source_stem = Path(source_name).stem

    raw_dir = storage_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / source_name

    with open(raw_path, 'wb') as fh:
        fh.write(uploaded_catalog.getbuffer())

    if not run_etl:
        target_path = storage_dir / source_name
        raw_path.replace(target_path)
        logger.info(f"📚 Каталог сохранен без ETL: {target_path}")
        return target_path

    converted_dir = storage_dir / "converted"
    clean_dir = storage_dir / "clean"
    converted_dir.mkdir(parents=True, exist_ok=True)
    clean_dir.mkdir(parents=True, exist_ok=True)

    converted_path = converted_dir / f"{source_stem}_converted.csv"
    clean_path = clean_dir / f"{source_stem}_clean.csv"

    convert_csv(raw_path, converted_path)
    PriceETL(str(converted_path), str(clean_path)).run()

    logger.info(f"📚 Каталог сохранен после ETL: {clean_path}")
    return clean_path




def sync_catalogs_from_google_drive(folder_url_or_id: str, service_account_json: str, run_etl: bool = False) -> list[Path]:
    """Синхронизировать CSV-каталоги из папки Google Drive в локальное хранилище."""
    storage_dir = get_upload_dir()
    raw_dir = storage_dir / "raw"

    logger.info("☁️ Старт синхронизации каталогов из Google Drive")
    service_account_info = json.loads(service_account_json)
    downloaded_raw_paths = sync_drive_folder_csvs(
        folder_url_or_id=folder_url_or_id,
        service_account_info=service_account_info,
        destination_dir=raw_dir,
    )

    if not downloaded_raw_paths:
        return []

    if not run_etl:
        logger.info("📦 Этап 1 завершен: файлы сохранены в raw без ETL. Файлов: %s", len(downloaded_raw_paths))
        return downloaded_raw_paths

    saved_paths: list[Path] = []
    total_files = len(downloaded_raw_paths)
    converted_dir = storage_dir / "converted"
    clean_dir = storage_dir / "clean"
    converted_dir.mkdir(parents=True, exist_ok=True)
    clean_dir.mkdir(parents=True, exist_ok=True)
    for idx, raw_path in enumerate(downloaded_raw_paths, start=1):
        source_name = Path(raw_path.name).name
        source_stem = Path(source_name).stem
        logger.info("🧩 Постобработка файла %s/%s: %s", idx, total_files, source_name)

        converted_path = converted_dir / f"{source_stem}_converted.csv"
        clean_path = clean_dir / f"{source_stem}_clean.csv"

        logger.info("🔄 ETL старт: %s", source_name)
        convert_csv(raw_path, converted_path)
        PriceETL(str(converted_path), str(clean_path)).run()
        saved_paths.append(clean_path)
        logger.info("✅ ETL завершен: %s", clean_path)

    _rebuild_merged_catalog_from_clean(clean_dir)
    logger.info("✅ Синхронизация и постобработка завершены. Файлов: %s", len(saved_paths))
    return saved_paths


def _run_etl_for_raw_file(raw_path: Path, converted_path: Path, clean_path: Path) -> Path | None:
    """Запустить ETL для raw файла с memory-safe режимом для крупных CSV."""
    threshold_mb = int(os.getenv("REMO_CHUNKED_ETL_THRESHOLD_MB", "512"))
    chunksize = int(os.getenv("REMO_CHUNKED_ETL_CHUNKSIZE", "100000"))
    file_mb = raw_path.stat().st_size / (1024 * 1024)

    if file_mb >= threshold_mb:
        logger.info(
            "🧠 Большой CSV (%.2f MB) — запускаем chunked ETL (threshold=%s MB, chunksize=%s)",
            file_mb,
            threshold_mb,
            chunksize,
        )
        PriceETL(str(raw_path), str(clean_path)).run_chunked(chunksize=chunksize)
        return None

    convert_csv(raw_path, converted_path)
    PriceETL(str(converted_path), str(clean_path)).run()
    return converted_path


def _prune_orphan_files(directory: Path, pattern: str, keep_paths: set[Path]) -> list[Path]:
    """Удалить файлы, которые больше не относятся к актуальному набору источников."""
    if not directory.exists():
        return []

    removed: list[Path] = []
    normalized_keep = {path.resolve() for path in keep_paths}
    for candidate in directory.glob(pattern):
        try:
            if candidate.resolve() in normalized_keep:
                continue
        except FileNotFoundError:
            continue
        if candidate.is_file():
            candidate.unlink()
            removed.append(candidate)
    return removed


def _reset_catalog_runtime_state() -> None:
    st.session_state.matcher = None
    st.session_state.matcher_db_csv = None
    st.session_state.matcher_settings_signature = None
    st.session_state.catalog_snapshot_bundle = None
    st.session_state.catalog_snapshot_xlsx_status = "idle"
    st.session_state.catalog_snapshot_xlsx_path = None
    st.session_state.catalog_snapshot_xlsx_url = None
    st.session_state.catalog_snapshot_drive_csv_url = None
    st.session_state.catalog_snapshot_drive_csv_name = None
    st.session_state.catalog_snapshot_r2_csv_url = None
    st.session_state.catalog_snapshot_r2_csv_key = None
    st.session_state.search_catalog_export_url = None
    st.session_state.search_catalog_export_name = None


def _reset_matcher_runtime_state() -> None:
    st.session_state.matcher = None
    st.session_state.matcher_db_csv = None
    st.session_state.matcher_settings_signature = None


def _rebuild_merged_catalog_from_clean(clean_dir: Path) -> Path:
    clean_dir = Path(clean_dir)
    merged_path = refresh_merged_catalog(clean_dir)
    logger.info("📦 Prepared merged DB after ETL/update: %s", merged_path)
    return merged_path


def _clear_loaded_run_cache() -> None:
    st.session_state.df_processed = None
    st.session_state.stats = None
    st.session_state.active_run_loaded_at = None


def _restore_active_run_state() -> None:
    interrupted_count = mark_stale_running_runs_as_interrupted()
    if interrupted_count:
        logger.info("🧹 Interrupted stale processing runs after startup: %s", interrupted_count)

    active_run_id = st.session_state.get("active_run_id")
    active_run = get_processing_run(active_run_id) if active_run_id else None
    if active_run is None:
        preferred_run = get_preferred_run_for_restore()
        st.session_state.last_run_restore_attempted = True
        if preferred_run is not None:
            st.session_state.active_run_id = preferred_run.run_id
            st.session_state.active_run_status = preferred_run.status
        else:
            st.session_state.active_run_id = None
            st.session_state.active_run_status = None
            _clear_loaded_run_cache()
        return

    st.session_state.active_run_status = active_run.status


def _get_active_or_preferred_run() -> Any:
    active_run_id = st.session_state.get("active_run_id")
    if active_run_id:
        return get_processing_run(active_run_id)
    return get_preferred_run_for_restore()


def _load_run_progress_safe(run_id: str) -> dict[str, Any] | None:
    try:
        return load_processing_run_progress(run_id)
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("⚠️ Failed to load run progress for %s: %s", run_id, exc)
        return None


def _schedule_active_run_autorefresh(run_id: str | None, *, interval_ms: int = ACTIVE_RUN_AUTOREFRESH_MS) -> None:
    if run_id:
        script = f"""
        <script>
        const root = window.parent;
        const key = "run:{run_id}";
        if (!root.__remoAutoRefreshTimers) {{
          root.__remoAutoRefreshTimers = {{}};
        }}
        Object.keys(root.__remoAutoRefreshTimers).forEach((existingKey) => {{
          if (existingKey !== key) {{
            clearTimeout(root.__remoAutoRefreshTimers[existingKey]);
            delete root.__remoAutoRefreshTimers[existingKey];
          }}
        }});
        if (root.__remoAutoRefreshTimers[key]) {{
          clearTimeout(root.__remoAutoRefreshTimers[key]);
        }}
        root.__remoAutoRefreshTimers[key] = setTimeout(() => {{
          delete root.__remoAutoRefreshTimers[key];
          root.location.reload();
        }}, {int(interval_ms)});
        </script>
        """
    else:
        script = """
        <script>
        const root = window.parent;
        if (root.__remoAutoRefreshTimers) {
          Object.keys(root.__remoAutoRefreshTimers).forEach((existingKey) => {
            clearTimeout(root.__remoAutoRefreshTimers[existingKey]);
            delete root.__remoAutoRefreshTimers[existingKey];
          });
        }
        </script>
        """
    components.html(script, height=0, width=0)


def _load_run_results_into_session(run) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = load_processing_run_dataframe(run, prefer_draft=True)
    stats = load_processing_run_stats(run)
    st.session_state.df_processed = df
    st.session_state.stats = stats
    st.session_state.active_run_id = run.run_id
    st.session_state.active_run_status = run.status
    st.session_state.active_run_loaded_at = run.updated_at
    return df, stats


def _dataframes_equal_for_persistence(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    if list(left.columns) != list(right.columns) or len(left.index) != len(right.index):
        return False
    left_norm = left.fillna("").astype(str)
    right_norm = right.fillna("").astype(str)
    return left_norm.equals(right_norm)


def process_raw_catalogs_with_etl() -> list[Path]:
    """Обработать уже скачанные raw CSV в отдельный этап ETL."""
    storage_dir = get_upload_dir()
    raw_dir = storage_dir / "raw"
    raw_files = sorted(raw_dir.glob("*.csv"), key=lambda p: p.name.lower())
    if not raw_files:
        logger.warning("⚠️ В папке raw нет CSV для ETL: %s", raw_dir)
        return []

    converted_dir = storage_dir / "converted"
    clean_dir = storage_dir / "clean"
    converted_dir.mkdir(parents=True, exist_ok=True)
    clean_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    active_converted_paths: set[Path] = set()
    active_clean_paths: set[Path] = set()
    total_files = len(raw_files)
    logger.info("🚀 Этап 2: старт ETL для raw CSV. Файлов: %s", total_files)
    for idx, raw_path in enumerate(raw_files, start=1):
        source_name = raw_path.name
        source_stem = raw_path.stem
        converted_path = converted_dir / f"{source_stem}_converted.csv"
        clean_path = clean_dir / f"{source_stem}_clean.csv"

        logger.info("🧩 ETL файл %s/%s: %s", idx, total_files, source_name)
        used_converted_path = _run_etl_for_raw_file(raw_path, converted_path, clean_path)
        saved_paths.append(clean_path)
        active_clean_paths.add(clean_path)
        if used_converted_path is not None:
            active_converted_paths.add(used_converted_path)
        logger.info("✅ ETL готов: %s (%s/%s)", clean_path.name, idx, total_files)

    removed_converted = _prune_orphan_files(converted_dir, "*_converted.csv", active_converted_paths)
    removed_clean = _prune_orphan_files(clean_dir, "*_clean.csv", active_clean_paths)
    if removed_converted:
        logger.info("🧹 Удалены устаревшие converted-файлы: %s", len(removed_converted))
    if removed_clean:
        logger.info("🧹 Удалены устаревшие clean-файлы: %s", len(removed_clean))

    _rebuild_merged_catalog_from_clean(clean_dir)

    logger.info("✅ Этап 2 завершен: ETL обработан для %s файлов", len(saved_paths))
    return saved_paths
def show_statistics(stats):
    """Отобразить статистику"""
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("📌 Всего элементов", stats['total'])
    
    with col2:
        st.metric("✅ Найдено", stats['found'], 
                 delta=f"{stats['found']/stats['total']*100:.1f}%" if stats['total'] > 0 else None)
    
    with col3:
        st.metric("❌ Не найдено", stats['not_found'])
    
    with col4:
        st.metric("💾 Из кэша", stats['from_cache'])
    
    with col5:
        st.metric("⚠️ Ошибок", stats['errors'])

    quality_rows = []
    if "gemini_rows_total" in stats:
        quality_rows.append(
            "Gemini: "
            f"{stats.get('gemini_rows_total', 0)} | "
            f"compatible={stats.get('gemini_rows_confirmed_compatible', 0)} | "
            f"weak={stats.get('gemini_rows_weakly_compatible', 0)} | "
            f"rejected={stats.get('gemini_rows_rejected_incompatible', 0)}"
        )
    if "unresolved_no_compatible_candidates" in stats:
        quality_rows.append(
            "Совместимость: "
            f"unresolved={stats.get('unresolved_no_compatible_candidates', 0)} | "
            f"local_fallback={stats.get('compatible_local_fallback_count', 0)} | "
            f"weak_fallback={stats.get('weak_compatible_fallback_count', 0)} | "
            f"strict_unresolved={stats.get('strict_class_unresolved_count', 0)}"
        )
    if "diagnostic_reason_class_counts" in stats:
        reason_classes = stats.get("diagnostic_reason_class_counts", {}) or {}
        quality_rows.append(
            "Диагностика: "
            f"catalog_gap={reason_classes.get('catalog_gap', 0)} | "
            f"retrieval={reason_classes.get('matcher_retrieval_or_ranking', 0)} | "
            f"gemini/policy={reason_classes.get('gemini_or_decision_policy', 0)}"
        )
    if "matcher_init_ms" in stats:
        quality_rows.append(
            "Performance: "
            f"matcher_init={float(stats.get('matcher_init_ms', 0.0)):.0f}ms | "
            f"duckdb_query_total={float(stats.get('duckdb_category_query_ms_total', 0.0)):.0f}ms | "
            f"scoring_total={float(stats.get('python_scoring_ms_total', 0.0)):.0f}ms | "
            f"gemini_total={float(stats.get('gemini_total_ms_total', 0.0)):.0f}ms"
        )
    for row in quality_rows:
        st.caption(row)




def _load_fresh_catalog_coverage_audit(run) -> dict[str, Any] | None:
    try:
        stored_payload = load_processing_run_coverage_audit(run.run_id)
    except Exception:
        return None
    if is_catalog_coverage_audit_fresh(
        stored_payload,
        run_id=run.run_id,
        catalog_source_path=run.catalog_source_path,
        catalog_source_kind=run.catalog_source_kind,
    ):
        return stored_payload
    return None


def _render_match_diagnostics(run, df: pd.DataFrame) -> None:
    st.subheader("🧭 Диагностика причин ненахода")
    st.caption(
        "Показывает, на каком этапе цепочки остановилась строка: query -> recall -> compatibility -> Gemini -> fallback."
    )

    coverage_audit_payload = _load_fresh_catalog_coverage_audit(run)
    diagnostics_payload = None
    reconstructed = False
    diagnostics_error = None
    try:
        stored_payload = load_processing_run_match_diagnostics(run.run_id)
        if is_match_diagnostics_fresh(stored_payload, run_id=run.run_id):
            diagnostics_payload = enrich_match_diagnostics_payload(
                stored_payload,
                coverage_audit_payload=coverage_audit_payload,
            )
    except Exception as exc:
        diagnostics_error = exc
        logger.warning("Не удалось загрузить сохраненную диагностику прогона %s: %s", run.run_id, exc)

    button_col, status_col = st.columns([1, 2])
    with button_col:
        rebuild_diagnostics = st.button("🧭 Пересчитать диагностику", key=f"match_diagnostics_{run.run_id}")
    with status_col:
        if diagnostics_payload is not None:
            generated_at = str(diagnostics_payload.get("generated_at") or "").strip()
            if diagnostics_payload.get("reconstructed"):
                st.caption(
                    f"Используется сохраненная reconstructed-диагностика: {generated_at}" if generated_at
                    else "Используется сохраненная reconstructed-диагностика."
                )
            elif generated_at:
                st.caption(f"Используется сохраненная runtime-диагностика: {generated_at}")
        elif diagnostics_error is not None:
            st.caption("Сохраненную диагностику не удалось прочитать, можно пересчитать.")
        else:
            st.caption("Диагностика еще не пересчитывалась вручную для этого прогона.")

    if rebuild_diagnostics:
        try:
            with st.spinner("Пересчитываю диагностику причин ненахода..."):
                if diagnostics_payload is None:
                    diagnostics_payload = reconstruct_match_diagnostics(
                        df,
                        run_id=run.run_id,
                        coverage_audit_payload=coverage_audit_payload,
                    )
                else:
                    diagnostics_payload = enrich_match_diagnostics_payload(
                        diagnostics_payload,
                        coverage_audit_payload=coverage_audit_payload,
                    )
                write_processing_run_match_diagnostics(run.run_id, diagnostics_payload)
            reconstructed = bool(diagnostics_payload.get("reconstructed"))
            st.success("✓ Диагностика сохранена.")
        except Exception as exc:
            st.error(f"Не удалось пересчитать диагностику: {exc}")
            logger.exception("Не удалось пересчитать диагностику прогона %s", run.run_id)

    if diagnostics_payload is None:
        reconstructed = True
        diagnostics_payload = reconstruct_match_diagnostics(
            df,
            run_id=run.run_id,
            coverage_audit_payload=coverage_audit_payload,
        )

    if reconstructed:
        st.info("Для этого прогона показана post-hoc reconstruction диагностики: runtime trace не был сохранен во время обработки.")
    else:
        generated_at = str(diagnostics_payload.get("generated_at") or "").strip()
        if generated_at:
            st.caption(f"Используется сохраненная runtime-диагностика: {generated_at}")

    summary = diagnostics_payload.get("summary", {}) if isinstance(diagnostics_payload, dict) else {}
    root_cause_class_counts = summary.get("root_cause_class_counts", {}) if isinstance(summary, dict) else {}
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("catalog gap", int(root_cause_class_counts.get("catalog_gap", 0)))
    with col2:
        st.metric("retrieval/ranking", int(root_cause_class_counts.get("matcher_retrieval_or_ranking", 0)))
    with col3:
        st.metric("Gemini/policy", int(root_cause_class_counts.get("gemini_or_decision_policy", 0)))
    with col4:
        st.metric("input/query shape", int(root_cause_class_counts.get("input_or_query_shape", 0)))

    stage_table = prepare_match_diagnostics_stage_table(diagnostics_payload)
    root_cause_table = prepare_match_diagnostics_root_cause_table(diagnostics_payload)
    reason_table = prepare_match_diagnostics_reason_table(diagnostics_payload)
    detail_table = prepare_match_diagnostics_table(diagnostics_payload)

    diagnostics_summary_table = _summary_mapping_to_df(
        {
            "rows_total": summary.get("rows_total", 0),
            "rows_resolved": summary.get("rows_resolved", 0),
            "rows_unresolved": summary.get("rows_unresolved", 0),
            "catalog_gap": root_cause_class_counts.get("catalog_gap", 0),
            "retrieval_ranking": root_cause_class_counts.get("matcher_retrieval_or_ranking", 0),
            "gemini_policy": root_cause_class_counts.get("gemini_or_decision_policy", 0),
            "input_query_shape": root_cause_class_counts.get("input_or_query_shape", 0),
            "not_audited_family": root_cause_class_counts.get("not_audited_family", 0),
            "reconstructed": "yes" if reconstructed else "no",
            "generated_at": str(diagnostics_payload.get("generated_at") or "").strip(),
        },
        labels={
            "rows_total": "Строк всего",
            "rows_resolved": "Resolved",
            "rows_unresolved": "Unresolved",
            "catalog_gap": "catalog gap",
            "retrieval_ranking": "retrieval/ranking",
            "gemini_policy": "Gemini/policy",
            "input_query_shape": "input/query shape",
            "not_audited_family": "not audited family",
            "reconstructed": "Post-hoc reconstruction",
            "generated_at": "Сгенерировано",
        },
    )
    diagnostics_export = _build_excel_workbook_bytes(
        [
            ("summary", diagnostics_summary_table),
            ("root_cause_summary", root_cause_table),
            ("pipeline_summary", stage_table),
            ("root_cause_codes", reason_table),
            ("details", detail_table),
        ]
    )
    st.download_button(
        "📥 Скачать всю диагностику",
        diagnostics_export,
        file_name=f"match_diagnostics_{run.run_id}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"download_match_diagnostics_{run.run_id}",
    )

    if not root_cause_table.empty:
        st.markdown("**Сводка по root cause**")
        st.dataframe(_prepare_df_for_display(root_cause_table), width="stretch")

    if not stage_table.empty:
        st.markdown("**Сводка по pipeline stage**")
        st.dataframe(_prepare_df_for_display(stage_table), width="stretch")

    if not reason_table.empty:
        st.markdown("**Сводка по root cause code**")
        st.dataframe(_prepare_df_for_display(reason_table), width="stretch")

    if not detail_table.empty:
        st.markdown("**Детали по строкам**")
        st.dataframe(_prepare_df_for_display(detail_table), width="stretch")


def _render_catalog_coverage_audit(run, df: pd.DataFrame) -> None:
    st.subheader("🔎 Аудит покрытия каталога")
    st.caption(
        "Проверка помогает понять, это честный unresolved из-за каталога или в БД уже есть "
        "совместимые кандидаты и сначала нужно тюнить matcher."
    )

    audit_payload = None
    audit_error = None
    try:
        stored_payload = load_processing_run_coverage_audit(run.run_id)
        if is_catalog_coverage_audit_fresh(
            stored_payload,
            run_id=run.run_id,
            catalog_source_path=run.catalog_source_path,
            catalog_source_kind=run.catalog_source_kind,
        ):
            audit_payload = stored_payload
    except Exception as exc:
        audit_error = exc

    button_col, status_col = st.columns([1, 2])
    with button_col:
        run_audit = st.button("🔎 Проверить покрытие каталога", key=f"catalog_coverage_audit_{run.run_id}")
    with status_col:
        if audit_payload is not None:
            generated_at = str(audit_payload.get("generated_at") or "").strip()
            if generated_at:
                st.caption(f"Используется сохраненный аудит: {generated_at}")
        elif audit_error is not None:
            st.caption("Сохраненный аудит не удалось прочитать, можно пересчитать.")
        else:
            st.caption("Аудит еще не рассчитывался для этого прогона.")

    if run_audit:
        try:
            with st.spinner("Проверяю покрытие каталога по использованной БД..."):
                audit_payload = build_catalog_coverage_audit(
                    df,
                    run_id=run.run_id,
                    catalog_source_path=run.catalog_source_path,
                    catalog_source_kind=run.catalog_source_kind,
                )
                write_processing_run_coverage_audit(run.run_id, audit_payload)
            st.success("✓ Аудит покрытия каталога сохранен.")
        except Exception as exc:
            logger.error("❌ Не удалось построить аудит покрытия каталога для %s: %s", run.run_id, exc, exc_info=True)
            st.error(f"❌ Не удалось построить аудит покрытия каталога: {exc}")
            audit_payload = None

    if audit_error is not None and audit_payload is None:
        st.warning(f"⚠️ Не удалось загрузить сохраненный аудит покрытия каталога: {audit_error}")

    if audit_payload is None:
        st.info(
            "Нажмите «Проверить покрытие каталога», чтобы получить диагноз по проблемным телеком-строкам "
            "и понять, это пробел БД или точка роста для matcher."
        )
        return

    summary = audit_payload.get("summary", {}) if isinstance(audit_payload, dict) else {}
    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    with metric_col1:
        st.metric("Строк в аудите", int(summary.get("rows_analyzed", 0)))
    with metric_col2:
        st.metric("Пробел каталога", int(summary.get("catalog_missing_family", 0)))
    with metric_col3:
        st.metric("Есть family, нет specs", int(summary.get("catalog_has_family_but_no_compatible_specs", 0)))
    with metric_col4:
        st.metric("Есть совместимые кандидаты", int(summary.get("catalog_has_compatible_candidates", 0)))

    st.caption(
        "Есть совместимые кандидаты = сначала тюним matcher. "
        "Пробел каталога = это скорее проблема входной БД, а не матчинга."
    )

    family_table = prepare_catalog_coverage_family_table(audit_payload)
    gap_reason_table = prepare_catalog_gap_reason_table(audit_payload)
    detail_table = prepare_catalog_coverage_audit_table(audit_payload)
    audit_export = _build_excel_workbook_bytes(
        [
            (
                "summary",
                _summary_mapping_to_df(
                    {
                        "rows_analyzed": summary.get("rows_analyzed", 0),
                        "catalog_missing_family": summary.get("catalog_missing_family", 0),
                        "catalog_has_family_but_no_compatible_specs": summary.get("catalog_has_family_but_no_compatible_specs", 0),
                        "catalog_has_compatible_candidates": summary.get("catalog_has_compatible_candidates", 0),
                        "families_total": summary.get("families_total", 0),
                        "generated_at": str(audit_payload.get("generated_at") or "").strip(),
                    },
                    labels={
                        "rows_analyzed": "Строк в аудите",
                        "catalog_missing_family": "Пробел каталога",
                        "catalog_has_family_but_no_compatible_specs": "Есть family, нет specs",
                        "catalog_has_compatible_candidates": "Есть совместимые кандидаты",
                        "families_total": "Семейств в аудите",
                        "generated_at": "Сгенерировано",
                    },
                ),
            ),
            ("families", family_table),
            ("gap_reasons", gap_reason_table),
            ("details", detail_table),
        ]
    )
    st.download_button(
        "📥 Скачать весь аудит",
        audit_export,
        file_name=f"catalog_coverage_audit_{run.run_id}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"download_catalog_audit_{run.run_id}",
    )

    if not family_table.empty:
        st.markdown("**Сводка по семействам**")
        st.dataframe(_prepare_df_for_display(family_table), width="stretch")

    if not gap_reason_table.empty:
        st.markdown("**Сводка по gap reason**")
        st.dataframe(_prepare_df_for_display(gap_reason_table), width="stretch")

    if not detail_table.empty:
        st.markdown("**Детали по строкам**")
        st.dataframe(_prepare_df_for_display(detail_table), width="stretch")


def _ensure_history_table_exists(conn: sqlite3.Connection) -> None:
    """Создать таблицу истории, если БД открыта до инициализации matcher."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_query TEXT,
            found_name TEXT,
            price REAL,
            article TEXT,
            user_approved BOOLEAN,
            correction_note TEXT,
            created_at TIMESTAMP
        )
    """)
    conn.commit()

def _prepare_df_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Сделать DataFrame безопасным для отображения в Streamlit/Arrow."""
    display_df = df.copy()
    for col in display_df.columns:
        if display_df[col].dtype == object:
            display_df[col] = display_df[col].astype(str)
    return display_df


def _summary_mapping_to_df(summary: dict[str, Any], *, labels: dict[str, str] | None = None) -> pd.DataFrame:
    prepared_rows = []
    for key, value in summary.items():
        prepared_rows.append(
            {
                "Метрика": (labels or {}).get(str(key), str(key)),
                "Значение": value,
            }
        )
    return pd.DataFrame(prepared_rows)


def _build_excel_workbook_bytes(sheets: list[tuple[str, pd.DataFrame]]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in sheets:
            export_df = df.copy()
            if export_df.empty:
                export_df = pd.DataFrame({"Статус": ["Нет данных"]})
            export_df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    buffer.seek(0)
    return buffer.getvalue()


def show_corrections_table(df):
    """Таблица для ручной коррекции результатов"""
    st.subheader("✏️ Коррекция результатов")
    
    # Фильтр: показать только не найденные
    show_only_missing = st.checkbox("Показать только не найденные позиции", value=False)
    
    if show_only_missing:
        missing_mask = (
            df['Найденная номенклатура'].isna()
            | (df['Найденная номенклатура'].astype(str).str.strip() == '')
            | (df['Найденная номенклатура'].astype(str).str.strip() == MISSING_POSITION_TEXT)
        )
        df_view = df[missing_mask].copy()
        st.info(f"📌 Найдено {len(df_view)} позиций без сопоставления")
    else:
        df_view = df.copy()
    original_index = df_view.index.copy()
    
    # Редактируемая таблица
    st.write("**Отредактируйте результаты в таблице ниже:**")
    
    edited_df = st.data_editor(
        df_view,
        width="stretch",
        disabled=['Наименование оборудования, материалов и кабелей'],  # Закрыть от редактирования
        num_rows="fixed"
    )

    updated_df = df.copy()
    edited_df.index = original_index
    updated_df.loc[original_index] = edited_df
    return updated_df


# ============ MAIN UI ============

def main():
    st.title("🔍 ReMo Matcher")
    st.markdown("*Семантическое сопоставление номенклатуры с товарной БД*")
    build_sha = os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("RAILWAY_GIT_COMMIT")
    if build_sha:
        st.caption(f"Build: `{build_sha[:8]}`")
        logger.info("🚢 Build commit: %s", build_sha)

    _restore_active_run_state()
    # Боковая панель
    with st.sidebar:
        st.header("⚙️ Настройки")
        
        st.subheader("1️⃣ Товарная база данных")

        catalog_upload = st.file_uploader(
            "Загрузить CSV каталог(и) поставщика",
            type=['csv'],
            accept_multiple_files=True,
            help="Файлы будут сохранены в рабочую папку данных (например, /data в Railway Volume)."
        )

        run_etl_before_save = st.checkbox(
            "Прогнать ETL перед сохранением каталога",
            value=True,
            help=(
                "Рекомендуется для "
                "сырого CSV из 1С/Excel: сначала конвертация кодировки/разделителя, "
                "потом очистка и нормализация."
            )
        )

        if catalog_upload and st.button("💾 Сохранить каталоги", key="save_catalogs_btn"):
            saved_clean_paths: list[Path] = []
            for uploaded_catalog in catalog_upload:
                try:
                    saved_path = save_uploaded_catalog(uploaded_catalog, run_etl=run_etl_before_save)
                    if run_etl_before_save and saved_path.parent.name == "clean":
                        saved_clean_paths.append(saved_path)
                    st.success(f"✓ Сохранен каталог: {saved_path.name}")
                except Exception as e:
                    logger.error(f"❌ Ошибка сохранения каталога: {e}", exc_info=True)
                    st.error(f"❌ Не удалось сохранить {uploaded_catalog.name}: {e}")

            if run_etl_before_save and saved_clean_paths:
                try:
                    merged_path = _rebuild_merged_catalog_from_clean(get_upload_dir() / "clean")
                    _reset_catalog_runtime_state()
                    st.success(f"✓ Итоговая БД обновлена: {merged_path.name}")
                except Exception as e:
                    logger.error("❌ Каталоги сохранены, но итоговая БД не обновлена: %s", e, exc_info=True)
                    st.error(f"❌ Каталоги сохранены, но итоговая БД не обновлена: {e}")
            else:
                _reset_catalog_runtime_state()

        st.caption("Синхронизация Google Drive в 2 этапа: скачать → отдельно ETL")
        if st.button("☁️ Выгрузить файлы из Google Drive", key="sync_drive_catalogs_btn"):
            folder_url_or_id, service_account_json = _get_drive_sync_config()
            if not folder_url_or_id or not service_account_json:
                st.error(
                    "❌ Не настроен доступ к Google Drive. "
                    "Задайте GOOGLE_DRIVE_FOLDER_ID/GOOGLE_DRIVE_FOLDER_URL и "
                    "GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON в secrets или env."
                )
            else:
                try:
                    saved_paths = sync_catalogs_from_google_drive(
                        folder_url_or_id=folder_url_or_id,
                        service_account_json=service_account_json,
                        run_etl=False,
                    )
                    if not saved_paths:
                        st.warning("⚠️ В папке Google Drive не найдено CSV-файлов")
                    else:
                        st.success(f"✓ Синхронизировано файлов: {len(saved_paths)}")
                        for path in saved_paths[:20]:
                            st.write(f"- {path.name}")
                        if len(saved_paths) > 20:
                            st.write(f"... и еще {len(saved_paths) - 20}")

                        _reset_catalog_runtime_state()
                except Exception as e:
                    logger.error(f"❌ Ошибка синхронизации из Google Drive: {e}", exc_info=True)
                    st.error(f"❌ Не удалось синхронизировать каталоги из Google Drive: {e}")


        if st.button("🧪 Прогнать ETL для raw CSV", key="run_raw_etl_btn"):
            try:
                clean_paths = process_raw_catalogs_with_etl()
                if not clean_paths:
                    st.warning("⚠️ В raw нет CSV для ETL")
                else:
                    st.success(f"✓ ETL обработал файлов: {len(clean_paths)}")
                    for path in clean_paths[:20]:
                        st.write(f"- {path.name}")
                    if len(clean_paths) > 20:
                        st.write(f"... и еще {len(clean_paths) - 20}")
                    _reset_catalog_runtime_state()
            except Exception as e:
                logger.error(f"❌ Ошибка этапа ETL для raw CSV: {e}", exc_info=True)
                st.error(f"❌ Не удалось выполнить ETL для raw CSV: {e}")

        catalog_path = _catalog_source_path()
        catalog_readiness = get_catalog_readiness(catalog_path)
        search_readiness = get_search_catalog_readiness(catalog_path)
        if catalog_readiness.state != "ready" and st.session_state.catalog_snapshot_bundle is not None:
            st.session_state.catalog_snapshot_bundle = None
            st.session_state.catalog_snapshot_xlsx_status = "idle"
            st.session_state.catalog_snapshot_xlsx_path = None
            st.session_state.catalog_snapshot_xlsx_url = None
            st.session_state.catalog_snapshot_drive_csv_url = None
            st.session_state.catalog_snapshot_drive_csv_name = None
            st.session_state.catalog_snapshot_r2_csv_url = None
            st.session_state.catalog_snapshot_r2_csv_key = None
        elif catalog_readiness.state != "ready" and st.session_state.catalog_snapshot_drive_csv_url is not None:
            st.session_state.catalog_snapshot_drive_csv_url = None
            st.session_state.catalog_snapshot_drive_csv_name = None
        elif catalog_readiness.state != "ready" and st.session_state.catalog_snapshot_r2_csv_url is not None:
            st.session_state.catalog_snapshot_r2_csv_url = None
            st.session_state.catalog_snapshot_r2_csv_key = None
        if search_readiness.state != "ready":
            st.session_state.search_catalog_export_url = None
            st.session_state.search_catalog_export_name = None
        readiness_labels = {
            "ready": "Готова",
            "missing": "Не собрана",
            "stale": "Устарела",
            "invalid": "Некорректна",
        }
        st.caption("Используется заранее подготовленная merged БД")
        st.info(
            "Основной источник для matcher и выгрузки: `clean/price_clean_merged.csv`. "
            "Пересборка выполняется после ETL или вручную через `🔄 Обновить БД`."
        )
        st.code(str(catalog_readiness.merged_path))
        st.write(
            f"Состояние БД: **{readiness_labels.get(catalog_readiness.state, catalog_readiness.state)}** "
            f"(clean-файлов: {catalog_readiness.clean_sources_count})"
        )
        if catalog_readiness.reason:
            st.caption(catalog_readiness.reason)
        if catalog_readiness.merged_path.exists():
            merged_updated_at = datetime.fromtimestamp(
                catalog_readiness.merged_path.stat().st_mtime
            ).isoformat(timespec="seconds")
            st.caption(f"Последнее обновление merged БД: {merged_updated_at}")

        st.caption("Поисковая БД для matcher")
        st.info(
            "Поисковая БД используется matcher для быстрого сопоставления. "
            "Если она не собрана или устарела, matcher будет работать на полной merged БД."
        )
        st.code(str(search_readiness.search_path))
        st.caption(f"Format: `{getattr(search_readiness, 'search_format', 'csv')}`")
        if str(getattr(search_readiness, "search_format", "")).strip().lower() == "duckdb":
            st.caption("Retrieval mode: `whole category` by derived branch.")
        st.write(
            f"Состояние поисковой БД: **{readiness_labels.get(search_readiness.state, search_readiness.state)}**"
        )
        if search_readiness.reason:
            st.caption(search_readiness.reason)
        if search_readiness.search_path.exists():
            search_updated_at = datetime.fromtimestamp(
                search_readiness.search_path.stat().st_mtime
            ).isoformat(timespec="seconds")
            st.caption(f"Последнее обновление поисковой БД: {search_updated_at}")

        if st.button("🔄 Обновить БД"):
            if catalog_readiness.clean_dir is None or catalog_readiness.clean_sources_count == 0:
                st.error(catalog_readiness.reason or "❌ Нет clean-файлов для пересборки БД")
            else:
                try:
                    merged_path = _rebuild_merged_catalog_from_clean(catalog_readiness.clean_dir)
                    _reset_catalog_runtime_state()
                    st.success(f"✓ БД обновлена: {merged_path.name}")
                except Exception as e:
                    logger.error(f"❌ Ошибка обновления итоговой БД: {e}", exc_info=True)
                    st.error(f"❌ Не удалось обновить итоговую БД: {e}")

        if st.button("🪶 Обновить поисковую БД"):
            if catalog_readiness.state != "ready" or catalog_readiness.clean_dir is None:
                st.error("❌ Сначала соберите итоговую БД через `🔄 Обновить БД`")
            else:
                try:
                    logger.info("🪶 Search catalog rebuild requested: clean_dir=%s", catalog_readiness.clean_dir)
                    search_path = refresh_search_catalog(catalog_readiness.clean_dir)
                    _reset_matcher_runtime_state()
                    st.session_state.search_catalog_export_url = None
                    st.session_state.search_catalog_export_name = None
                    st.success(f"✓ Поисковая БД обновлена: {search_path.name}")
                except Exception as e:
                    logger.error("❌ Search catalog rebuild failed: %s", e, exc_info=True)
                    st.error(f"❌ Не удалось обновить поисковую БД: {e}")

        if st.button("♻️ Сбросить состояние БД"):
            _reset_catalog_runtime_state()
            st.success("✓ Состояние БД сброшено")

        st.caption("Выгрузка поисковой БД")
        if st.button("☁️ Выгрузить поисковую БД в Cloudflare R2"):
            if search_readiness.state != "ready":
                st.error(
                    f"❌ {search_readiness.reason or 'Поисковая БД не готова'}. "
                    "Нажмите `🪶 Обновить поисковую БД`."
                )
            else:
                account_id, bucket, access_key_id, secret_access_key, public_base_url = _get_cloudflare_r2_export_config()
                if not account_id or not bucket or not access_key_id or not secret_access_key:
                    st.error(
                        "❌ Не настроен Cloudflare R2 export. "
                        "Задайте CLOUDFLARE_R2_ACCOUNT_ID, CLOUDFLARE_R2_BUCKET, "
                        "CLOUDFLARE_R2_ACCESS_KEY_ID и CLOUDFLARE_R2_SECRET_ACCESS_KEY."
                    )
                else:
                    try:
                        source_path = search_readiness.search_path
                        export_name = f"{build_snapshot_export_basename(source_path)}{source_path.suffix or '.duckdb'}"
                        object_key = f"catalog-exports/{export_name}"
                        logger.info(
                            "🖱️ Search catalog Cloudflare R2 export button pressed: source=%s bucket=%s key=%s",
                            source_path,
                            bucket,
                            object_key,
                        )
                        upload_result = upload_file_to_r2(
                            source_path=source_path,
                            account_id=account_id,
                            bucket=bucket,
                            access_key_id=access_key_id,
                            secret_access_key=secret_access_key,
                            object_key=object_key,
                            public_base_url=public_base_url,
                        )
                        st.session_state.search_catalog_export_url = upload_result.download_url
                        st.session_state.search_catalog_export_name = upload_result.object_key
                        st.success(f"✓ Поисковая БД выгружена в Cloudflare R2: {upload_result.object_key}")
                    except Exception as e:
                        logger.error("❌ Search catalog Cloudflare R2 export failed: %s", e, exc_info=True)
                        st.error(f"❌ Не удалось выгрузить поисковую БД в Cloudflare R2: {e}")

        if st.session_state.search_catalog_export_url:
            if st.session_state.search_catalog_export_name:
                st.caption(f"Объект в Cloudflare R2: {st.session_state.search_catalog_export_name}")
            st.link_button(
                "☁️ Открыть поисковую БД в Cloudflare R2",
                st.session_state.search_catalog_export_url,
                use_container_width=True,
            )

        st.caption("Выгрузка готовой входной БД")
        if st.button("☁️ Выгрузить БД в Cloudflare R2 (CSV)"):
            if catalog_readiness.state != "ready":
                st.error(
                    f"❌ {catalog_readiness.reason or 'Итоговая БД не готова'}. "
                    "Нажмите `🔄 Обновить БД`."
                )
            else:
                account_id, bucket, access_key_id, secret_access_key, public_base_url = _get_cloudflare_r2_export_config()
                if not account_id or not bucket or not access_key_id or not secret_access_key:
                    st.error(
                        "❌ Не настроен Cloudflare R2 export. "
                        "Задайте CLOUDFLARE_R2_ACCOUNT_ID, CLOUDFLARE_R2_BUCKET, "
                        "CLOUDFLARE_R2_ACCESS_KEY_ID и CLOUDFLARE_R2_SECRET_ACCESS_KEY."
                    )
                else:
                    try:
                        source_path = _catalog_source_path()
                        export_name = f"{build_snapshot_export_basename(source_path)}{source_path.suffix or '.csv'}"
                        object_key = f"catalog-exports/{export_name}"
                        logger.info(
                            "🖱️ Cloudflare R2 export button pressed: source=%s bucket=%s key=%s",
                            source_path,
                            bucket,
                            object_key,
                        )
                        upload_result = upload_file_to_r2(
                            source_path=source_path,
                            account_id=account_id,
                            bucket=bucket,
                            access_key_id=access_key_id,
                            secret_access_key=secret_access_key,
                            object_key=object_key,
                            public_base_url=public_base_url,
                        )
                        st.session_state.catalog_snapshot_r2_csv_url = upload_result.download_url
                        st.session_state.catalog_snapshot_r2_csv_key = upload_result.object_key
                        logger.info(
                            "✅ Cloudflare R2 export link prepared in UI: bucket=%s key=%s",
                            upload_result.bucket,
                            upload_result.object_key,
                        )
                        st.success(f"✓ Файл выгружен в Cloudflare R2: {upload_result.object_key}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка выгрузки БД в Cloudflare R2: {e}", exc_info=True)
                        st.error(f"❌ Не удалось выгрузить БД в Cloudflare R2: {e}")

        if st.session_state.catalog_snapshot_r2_csv_url:
            if st.session_state.catalog_snapshot_r2_csv_key:
                st.caption(f"Объект в Cloudflare R2: {st.session_state.catalog_snapshot_r2_csv_key}")
            st.link_button(
                "☁️ Открыть входную БД в Cloudflare R2",
                st.session_state.catalog_snapshot_r2_csv_url,
                use_container_width=True,
            )

        st.session_state.catalog_snapshot_bundle = None

        if st.session_state.catalog_snapshot_bundle is not None:
            bundle = st.session_state.catalog_snapshot_bundle
            xlsx_status, xlsx_started_at = get_snapshot_xlsx_status(
                bundle.resolved_csv_path,
                bundle.xlsx_path,
            )
            bundle.xlsx_status = xlsx_status
            bundle.xlsx_started_at = xlsx_started_at
            bundle.public_xlsx_url = (
                build_public_export_url(bundle.xlsx_path)
                if bundle.xlsx_path is not None and xlsx_status == "ready"
                else None
            )
            st.session_state.catalog_snapshot_xlsx_status = xlsx_status
            st.session_state.catalog_snapshot_xlsx_path = (
                str(bundle.xlsx_path) if bundle.xlsx_path is not None else None
            )
            st.session_state.catalog_snapshot_xlsx_url = bundle.public_xlsx_url

            size_mb = bundle.resolved_csv_size_bytes / (1024 * 1024)
            st.write(f"Активный источник: `{bundle.resolved_csv_path}`")
            st.write(f"Размер CSV: **{size_mb:.2f} MB**")
            if bundle.resolved_csv_path.exists():
                source_updated_at = datetime.fromtimestamp(
                    bundle.resolved_csv_path.stat().st_mtime
                ).isoformat(timespec="seconds")
                st.caption(f"Файл обновлен: {source_updated_at}")

            st.link_button(
                "⬇️ Скачать входную БД (CSV)",
                bundle.public_csv_url,
                use_container_width=True,
            )

            if st.button("🧮 Проверить дубли БД"):
                try:
                    logger.info("🖱️ Duplicate report button pressed: source=%s", bundle.resolved_csv_path)
                    bundle = prepare_catalog_duplicate_report(bundle)
                    st.session_state.catalog_snapshot_bundle = bundle
                    st.success("✓ Проверка дублей завершена")
                except Exception as e:
                    logger.error(f"❌ Ошибка проверки дублей БД: {e}", exc_info=True)
                    st.error(f"❌ Не удалось проверить дубли БД: {e}")

            stats = bundle.duplicate_stats or {}
            if stats:
                st.write(f"Строк всего: **{stats.get('rows_total', 0)}**")
                st.write(
                    f"Дублей: **{stats.get('duplicates_total', 0)}** "
                    f"(артикул: {stats.get('duplicates_by_article', 0)}, "
                    f"наименование: {stats.get('duplicates_by_name', 0)})"
                )
                if bundle.public_duplicate_csv_url:
                    st.link_button(
                        "⬇️ Скачать только дубли (CSV)",
                        bundle.public_duplicate_csv_url,
                        use_container_width=True,
                    )

            if st.button("📗 Подготовить Excel-файл"):
                try:
                    logger.info(
                        "🖱️ Snapshot XLSX button pressed: source=%s target=%s current_status=%s",
                        bundle.resolved_csv_path,
                        bundle.xlsx_path,
                        bundle.xlsx_status,
                    )
                    xlsx_status, xlsx_started_at = start_snapshot_xlsx_build(
                        bundle.resolved_csv_path,
                        bundle.xlsx_path,
                    )
                    bundle.xlsx_status = xlsx_status
                    bundle.xlsx_started_at = xlsx_started_at
                    bundle.public_xlsx_url = (
                        build_public_export_url(bundle.xlsx_path)
                        if bundle.xlsx_path is not None and xlsx_status == "ready"
                        else None
                    )
                    st.session_state.catalog_snapshot_xlsx_status = xlsx_status
                    st.session_state.catalog_snapshot_xlsx_path = (
                        str(bundle.xlsx_path) if bundle.xlsx_path is not None else None
                    )
                    st.session_state.catalog_snapshot_xlsx_url = bundle.public_xlsx_url
                    logger.info(
                        "✅ Snapshot XLSX request handled: source=%s target=%s new_status=%s started_at=%s",
                        bundle.resolved_csv_path,
                        bundle.xlsx_path,
                        xlsx_status,
                        xlsx_started_at,
                    )
                    if xlsx_status == "ready":
                        st.success("✓ Excel-файл уже готов")
                    else:
                        st.info("⏳ Подготовка Excel-файла запущена")
                except Exception as e:
                    logger.error(f"❌ Ошибка подготовки Excel-файла: {e}", exc_info=True)
                    st.error(f"❌ Не удалось подготовить Excel-файл: {e}")

            xlsx_status_labels = {
                "idle": "Не подготовлен",
                "building": "Подготовка Excel-файла...",
                "ready": "Excel-файл готов",
                "failed_stale": "Подготовка зависла, перезапустите сборку",
            }
            st.write(f"Excel-выгрузка: **{xlsx_status_labels.get(bundle.xlsx_status, bundle.xlsx_status)}**")
            if bundle.xlsx_started_at:
                st.caption(f"Статус обновлен: {bundle.xlsx_started_at}")
            if bundle.public_xlsx_url:
                st.link_button(
                    "⬇️ Скачать входную БД (Excel)",
                    bundle.public_xlsx_url,
                    use_container_width=True,
                )

        st.subheader("2️⃣ Тонкая настройка matcher")
        st.info(
            "Параллелизм установлен на максимум: одновременно отправляется число запросов, "
            "равное числу позиций в файле."
        )
        st.success("Активный режим retrieval: `DuckDB whole-category retrieval by derived branch`.")
        st.caption(
            "При подготовленной search DuckDB matcher сначала берет всю категорию запроса по derived branch, "
            "а лимиты ниже используются как legacy/advanced fallback и для разбиения Gemini-контекста."
        )
        with st.expander("Advanced matcher controls", expanded=False):
            st.caption(
                "Эти параметры больше не являются основным retrieval-механизмом в DuckDB-режиме, "
                "но остаются полезными для fallback и Gemini chunking."
            )
            st.slider(
                "Кандидатов для Gemini",
                min_value=24,
                max_value=200,
                step=12,
                key="matcher_gemini_shortlist_limit",
                help="Сколько лучших кандидатов максимум может увидеть Gemini для одной позиции.",
            )
            st.slider(
                "Кандидатов в 1 запрос Gemini",
                min_value=6,
                max_value=20,
                step=2,
                key="matcher_gemini_chunk_size",
                help="Сколько кандидатов включать в один вызов модели.",
            )
            st.slider(
                "Максимум запросов Gemini на позицию",
                min_value=1,
                max_value=12,
                step=1,
                key="matcher_gemini_max_chunks",
                help="Ограничение по числу последовательных Gemini-вызовов для одной строки.",
            )
            st.slider(
                "Глубина локального поиска",
                min_value=100,
                max_value=1000,
                step=50,
                key="matcher_local_recall_pool",
                help="Legacy/fallback лимит локального отбора, если whole-category retrieval недоступен.",
            )
            st.checkbox(
                "Пропускать Gemini для слабого shortlist",
                key="matcher_skip_weak_shortlist",
                help="Если включено, слишком слабый локальный shortlist не отправляется в Gemini. По умолчанию выключено.",
            )

        shortlist_limit = int(st.session_state.get("matcher_gemini_shortlist_limit", get_matcher_gemini_shortlist_limit()))
        chunk_size = int(st.session_state.get("matcher_gemini_chunk_size", get_matcher_gemini_chunk_size()))
        max_chunks = int(st.session_state.get("matcher_gemini_max_chunks", get_matcher_gemini_max_chunks()))
        st.caption(
            f"Gemini chunking: до {shortlist_limit} кандидатов, "
            f"до {max_chunks} запросов на строку, по {chunk_size} кандидатов за запрос."
        )
        st.warning("Рост этих advanced-лимитов увеличивает время обработки и стоимость Gemini, но не заменяет category retrieval.")

        mode_options = ["exact", "analog"]
        current_mode = str(st.session_state.get("matcher_mode", "exact"))
        st.session_state.matcher_mode = _safe_matcher_mode_select(current_mode, mode_options)

        if st.button("✅ Применить параметры matcher"):
            st.session_state.matcher = None
            st.session_state.matcher_db_csv = None
            st.session_state.matcher_settings_signature = None
            st.success("✓ Параметры применены. Matcher будет переинициализирован при следующем запуске.")
        
        st.divider()
        
        st.subheader("📚 О приложении")
        st.markdown("""
        **ReMo Matcher v1.0**
        
        Функции:
        - 🔍 Автоматическое сопоставление номенклатуры
        - 🤖 Использует Gemini API для точности
        - 💾 Кэширование результатов
        - ✏️ Ручная коррекция
        - 📊 Статистика обработки
        
        **Столбцы результата:**
        - G: Цена (из БД)
        - H: Найденная номенклатура
        - I: Артикул
        """)
        
        st.divider()
        
        if st.button("🗑️ Очистить кэш"):
            cache_file = get_matcher_cache_db_path()
            if cache_file.exists():
                os.unlink(cache_file)
                st.session_state.matcher = None
                st.success("✓ Кэш очищен")
            else:
                st.info("Кэш уже пуст")
    
    # Основная область
    tab1, tab2, tab3 = st.tabs(["📤 Загрузка", "📋 Результаты", "📊 История"])
    
    with tab1:
        st.header("Загрузка файла КП")

        run_for_display = _get_active_or_preferred_run()
        if run_for_display is not None:
            status_labels = {
                "queued": "В очереди",
                "running": "Выполняется",
                "completed": "Завершен",
                "failed": "Ошибка",
                "interrupted": "Прерван",
            }
            auto_refresh_allowed = run_for_display.status in ("queued", "running")
            if not auto_refresh_allowed:
                st.session_state.active_run_auto_refresh_enabled = False
            if auto_refresh_allowed and st.session_state.get("active_run_auto_refresh_enabled"):
                _schedule_active_run_autorefresh(run_for_display.run_id)
            else:
                _schedule_active_run_autorefresh(None)
            st.subheader("Текущий прогон")
            st.write(f"**ID:** `{run_for_display.run_id}`")
            st.write(f"**Файл:** {run_for_display.input_filename}")
            st.write(f"**Статус:** {status_labels.get(run_for_display.status, run_for_display.status)}")
            st.write(f"**Источник каталога:** {run_for_display.catalog_source_kind}")
            st.write(f"**Создан:** {run_for_display.created_at}")
            if run_for_display.started_at:
                st.write(f"**Старт:** {run_for_display.started_at}")
            st.write(f"**Обновлен:** {run_for_display.updated_at}")
            progress_state = _load_run_progress_safe(run_for_display.run_id)
            if progress_state:
                stage_labels = {
                    "queued": "Ожидание запуска",
                    "matcher_init": "Инициализация matcher",
                    "reading_excel": "Чтение Excel",
                    "processing": "Подготовка к обработке",
                    "matching": "Сопоставление позиций",
                    "saving_results": "Сохранение результатов",
                    "completed": "Завершено",
                    "failed": "Ошибка",
                }
                progress_stage = str(progress_state.get("stage") or "").strip()
                progress_message = str(progress_state.get("message") or "").strip()
                current = progress_state.get("current")
                total = progress_state.get("total")
                percent = progress_state.get("percent")
                try:
                    normalized_progress = float(percent) if percent is not None else 0.0
                except (TypeError, ValueError):
                    normalized_progress = 0.0
                normalized_progress = max(0.0, min(1.0, normalized_progress))
                st.write(
                    f"**Этап:** {stage_labels.get(progress_stage, progress_stage or 'Неизвестно')}"
                )
                st.progress(normalized_progress)
                if current is not None and total is not None and int(total) > 0:
                    st.caption(f"Прогресс: {int(current)} / {int(total)}")
                if progress_message:
                    st.caption(progress_message)
                if auto_refresh_allowed:
                    if st.session_state.get("active_run_auto_refresh_enabled"):
                        st.caption("Автообновление включено: страница обновляется каждые 5 секунд.")
                    else:
                        st.caption("Автообновление выключено. Включите его ниже или обновляйте статус вручную.")
            if run_for_display.status == "completed":
                st.caption(
                    "Статистика: "
                    f"всего={run_for_display.rows_total or 0}, "
                    f"найдено={run_for_display.found_count or 0}, "
                    f"не найдено={run_for_display.missing_count or 0}, "
                    f"требуют проверки={run_for_display.requires_review_count or 0}"
                )
            elif run_for_display.error_text:
                st.warning(run_for_display.error_text)

            status_col1, status_col2, status_col3 = st.columns(3)
            with status_col1:
                if st.button("🔄 Обновить статус", key="refresh_active_run_status"):
                    st.rerun()
            with status_col2:
                if auto_refresh_allowed:
                    st.checkbox(
                        "Автообновление 5с",
                        value=bool(st.session_state.get("active_run_auto_refresh_enabled")),
                        key="active_run_auto_refresh_enabled",
                        help="Включает автоматическое обновление страницы во время выполнения прогона.",
                    )
                elif st.button("📌 Открыть этот прогон в результатах", key="open_active_run_results"):
                    st.session_state.active_run_id = run_for_display.run_id
                    st.session_state.active_run_status = run_for_display.status
                    st.info("Перейдите на вкладку «Результаты», чтобы открыть этот прогон.")
            with status_col3:
                if st.button("🧹 Сбросить выбор", key="clear_active_run_selection"):
                    st.session_state.active_run_id = None
                    st.session_state.active_run_status = None
                    st.session_state.active_run_auto_refresh_enabled = False
                    _clear_loaded_run_cache()
                    st.success("Выбор активного прогона очищен")
        else:
            st.session_state.active_run_auto_refresh_enabled = False
            _schedule_active_run_autorefresh(None)
        
        uploaded_file = st.file_uploader(
            "Выберите Excel файл коммерческого предложения",
            type=['xlsx', 'xls'],
            help="Файл должен содержать столбец 'Наименование оборудования, материалов и кабелей'"
        )
        
        if uploaded_file:
            logger.info(f"📤 Файл загружен пользователем: {uploaded_file.name} ({uploaded_file.size} байт)")
            st.info(f"📄 Файл выбран: {uploaded_file.name}")

            db_csv = str(_catalog_source_path())
            issues = _validate_runtime_readiness(db_csv)
            if issues:
                st.warning("⚠️ Перед обработкой исправьте настройки:")
                for issue in issues:
                    st.write(f"- {issue}")

            with st.form("process_form", clear_on_submit=False):
                process_button = st.form_submit_button(
                    "🚀 Начать обработку",
                    disabled=bool(issues),
                    width="stretch",
                )

            if process_button:
                logger.info("🔘 Пользователь нажал кнопку 'Начать обработку'")
                active_run = get_latest_active_processing_run()
                if active_run is not None:
                    st.error("❌ Уже выполняется обработка. Дождитесь завершения текущего прогона.")
                else:
                    try:
                        run_id = _start_processing_run(uploaded_file)
                        st.markdown(
                            '<div class="success-box">✅ Прогон запущен в фоне. '
                            'Страница может быть обновлена без потери результата.</div>',
                            unsafe_allow_html=True,
                        )
                        st.info(f"ID нового прогона: `{run_id}`")
                        logger.info("✅ Processing run created from UI: %s", run_id)
                    except Exception as e:
                        logger.error(f"❌ Ошибка при запуске фоновой обработки: {e}", exc_info=True)
                        st.markdown(
                            f'<div class="error-box">❌ Ошибка запуска обработки: {str(e)}</div>',
                            unsafe_allow_html=True,
                        )
                        st.error(str(e))
    
    with tab2:
        st.header("📋 Результаты обработки")
        run = _get_active_or_preferred_run()
        if run is None:
            st.info("📤 Загрузите файл и запустите обработку. Последних прогонов пока нет.")
        elif run.status in ("queued", "running"):
            st.info(
                f"⏳ Прогон `{run.run_id}` еще выполняется "
                f"({run.status}). Обновите страницу позже или нажмите «Обновить статус» на вкладке «Загрузка»."
            )
            progress_state = _load_run_progress_safe(run.run_id)
            if progress_state:
                progress_message = str(progress_state.get("message") or "").strip()
                percent = progress_state.get("percent")
                try:
                    normalized_progress = float(percent) if percent is not None else 0.0
                except (TypeError, ValueError):
                    normalized_progress = 0.0
                normalized_progress = max(0.0, min(1.0, normalized_progress))
                st.progress(normalized_progress)
                current = progress_state.get("current")
                total = progress_state.get("total")
                if current is not None and total is not None and int(total) > 0:
                    st.caption(f"Прогресс: {int(current)} / {int(total)}")
                if progress_message:
                    st.caption(progress_message)
        elif run.status in ("failed", "interrupted"):
            st.error(
                f"❌ Прогон `{run.run_id}` не завершен: "
                f"{run.error_text or 'подробности отсутствуют'}"
            )
        else:
            try:
                if (
                    st.session_state.df_processed is None
                    or st.session_state.get("active_run_id") != run.run_id
                    or st.session_state.get("active_run_loaded_at") != run.updated_at
                ):
                    df, stats = _load_run_results_into_session(run)
                else:
                    df = st.session_state.df_processed
                    stats = st.session_state.stats
            except Exception as e:
                logger.error("❌ Не удалось загрузить результаты прогона %s: %s", run.run_id, e, exc_info=True)
                st.error(f"❌ Не удалось загрузить результаты прогона `{run.run_id}`: {e}")
                df = None
                stats = None

            if df is not None and stats is not None:
                st.caption(f"Открыт прогон: `{run.run_id}`")
                if has_processing_run_draft(run):
                    st.info("📝 Для этого прогона есть автосохраненный черновик правок.")
                show_statistics(stats)
                st.divider()
                _render_catalog_coverage_audit(run, df)

                st.divider()
                _render_match_diagnostics(run, df)

                st.divider()

                default_mode = "Коррекция" if st.session_state.get("active_run_mode") == "correction" else "Просмотр"
                mode = st.radio(
                    "Режим",
                    ["Просмотр", "Коррекция"],
                    index=1 if default_mode == "Коррекция" else 0,
                    horizontal=True,
                )
                st.session_state.active_run_mode = "correction" if mode == "Коррекция" else "view"

                if mode == "Коррекция":
                    edited_df = show_corrections_table(df)
                    if not _dataframes_equal_for_persistence(edited_df, df):
                        save_processing_run_draft(run.run_id, edited_df)
                        st.session_state.df_processed = edited_df.copy()
                        df = edited_df
                        run = get_processing_run(run.run_id) or run
                        st.session_state.active_run_loaded_at = run.updated_at
                        st.caption(f"Черновик правок автосохранен: {run.updated_at}")
                    if st.button("💾 Сохранить правки", key="save_corrections"):
                        save_processing_run_draft(run.run_id, df)
                        run = get_processing_run(run.run_id) or run
                        st.session_state.active_run_loaded_at = run.updated_at
                        st.success("✓ Правки сохранены")

                col1, col2, col3 = st.columns(3)

                with col1:
                    show_filter = st.selectbox(
                        "Фильтр",
                        ["Все", "Найдены", "Не найдены", "С ошибками"]
                    )

                with col2:
                    sort_by = st.selectbox("Сортировать по", ["По порядку", "Названию", "Цене"])

                with col3:
                    page_size = st.slider("Строк на странице", 5, 50, 20)

                missing_mask = (
                    df['Найденная номенклатура'].isna()
                    | (df['Найденная номенклатура'].astype(str).str.strip() == '')
                    | (df['Найденная номенклатура'].astype(str).str.strip() == MISSING_POSITION_TEXT)
                )
                error_mask = (
                    df['Ошибка сопоставления'].notna()
                    & (df['Ошибка сопоставления'].astype(str).str.strip() != '')
                ) if 'Ошибка сопоставления' in df.columns else pd.Series(False, index=df.index)

                if show_filter == "Найдены":
                    df_view = df[~missing_mask]
                elif show_filter == "Не найдены":
                    df_view = df[missing_mask]
                elif show_filter == "С ошибками":
                    df_view = df[error_mask]
                else:
                    df_view = df

                if sort_by == "Названию":
                    df_view = df_view.sort_values(by=df.columns[1], na_position='last')
                elif sort_by == "Цене":
                    df_view = df_view.sort_values(by='Цена', ascending=False, na_position='last')

                st.info(f"📌 Отображено {len(df_view)} из {len(df)} записей")

                total_pages = (len(df_view) + page_size - 1) // page_size
                max_pages = max(1, total_pages)
                if max_pages > 1:
                    page = st.slider("Страница", 1, max_pages, 1)
                else:
                    page = 1
                    st.caption("Страница 1 из 1")

                start_idx = (page - 1) * page_size
                end_idx = start_idx + page_size

                st.dataframe(_prepare_df_for_display(df_view.iloc[start_idx:end_idx]), width="stretch")

                if max_pages > 1:
                    st.markdown(f"Страница {page} из {max_pages}")

                st.divider()

                output_format = st.radio("Формат для скачивания", ["Excel", "CSV"])

                download_col1, download_col2 = st.columns(2)

                with download_col1:
                    if output_format == "Excel":
                        try:
                            excel_buffer = io.BytesIO()
                            df.to_excel(excel_buffer, index=False, engine='openpyxl')
                            excel_buffer.seek(0)
                            st.download_button(
                                "📥 Скачать Excel",
                                excel_buffer.getvalue(),
                                f"result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                                "application/vnd.ms-excel"
                            )
                            logger.info("✓ Excel успешно сгенерирован для скачивания")
                        except Exception as e:
                            st.error(f"❌ Ошибка при сохранении Excel: {str(e)}")
                            logger.error(f"Ошибка Excel: {e}", exc_info=True)

                with download_col2:
                    csv_data = df.to_csv(index=False, sep=';', encoding='utf-8')
                    st.download_button(
                        "📥 Скачать CSV",
                        csv_data,
                        f"result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        "text/csv"
                    )
    
    with tab3:
        st.header("📊 История обработок")
        st.subheader("История прогонов")
        try:
            runs = list_processing_runs(limit=20)
            if runs:
                runs_df = pd.DataFrame(
                    [
                        {
                            "run_id": run.run_id,
                            "created_at": run.created_at,
                            "input_filename": run.input_filename,
                            "status": run.status,
                            "catalog_source_kind": run.catalog_source_kind,
                            "rows_total": run.rows_total,
                            "found_count": run.found_count,
                            "missing_count": run.missing_count,
                            "requires_review_count": run.requires_review_count,
                        }
                        for run in runs
                    ]
                )
                st.dataframe(_prepare_df_for_display(runs_df), width="stretch")

                run_options = {f"{run.created_at} | {run.status} | {run.input_filename}": run.run_id for run in runs}
                selected_run_label = st.selectbox(
                    "Выберите прогон",
                    list(run_options.keys()),
                    key="history_run_selector",
                )
                if st.button("📌 Открыть выбранный прогон", key="open_history_run"):
                    selected_run_id = run_options[selected_run_label]
                    selected_run = get_processing_run(selected_run_id)
                    if selected_run is None:
                        st.error("❌ Выбранный прогон больше недоступен")
                    else:
                        st.session_state.active_run_id = selected_run.run_id
                        st.session_state.active_run_status = selected_run.status
                        _clear_loaded_run_cache()
                        st.success(f"✓ Выбран прогон `{selected_run.run_id}`. Перейдите на вкладку «Результаты».")
            else:
                st.info("📭 История прогонов пока пуста")
        except Exception as e:
            st.warning(f"⚠️ Не удалось загрузить историю прогонов: {e}")

        st.divider()
        st.subheader("История подтверждений")

        try:
            conn = sqlite3.connect(str(get_matcher_cache_db_path()))
            _ensure_history_table_exists(conn)

            df_history = pd.read_sql_query(
                "SELECT * FROM match_history ORDER BY created_at DESC LIMIT 100",
                conn
            )

            if not df_history.empty:
                col1, col2, col3 = st.columns(3)

                with col1:
                    approved_count = df_history['user_approved'].sum()
                    st.metric("✅ Одобрено", approved_count)

                with col2:
                    rejected_count = len(df_history) - approved_count
                    st.metric("❌ Отклонено", rejected_count)

                with col3:
                    success_rate = (approved_count / len(df_history) * 100) if len(df_history) > 0 else 0
                    st.metric("📊 Одобрено %", f"{success_rate:.1f}%")

                st.divider()
                st.dataframe(_prepare_df_for_display(df_history), width="stretch")
            else:
                st.info("📭 История подтверждений пуста")

            conn.close()
        except Exception as e:
            st.warning(f"⚠️ Не удалось загрузить историю подтверждений: {e}")


if __name__ == "__main__":
    main()
