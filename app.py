"""
ReMo Matcher UI
Streamlit интерфейс для семантического сопоставления номенклатуры
"""

import streamlit as st
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
import re
import subprocess
import sys
import threading
import time
import uuid
from typing import Any
from cloudflare_r2_export import upload_file_to_r2
from catalog_search import (
    build_search_taxonomy_bootstrap_draft,
    build_search_taxonomy_branch_probe,
    build_search_taxonomy_preview,
    ensure_search_taxonomy_snapshot,
    get_search_catalog_readiness,
    get_search_taxonomy_probe_report_path,
    is_search_catalog_path,
    refresh_search_catalog,
)
from catalog_coverage_audit import (
    build_catalog_coverage_audit,
    is_catalog_coverage_audit_fresh,
    prepare_catalog_coverage_audit_table,
    prepare_catalog_coverage_family_table,
    prepare_catalog_gap_reason_table,
)
from match_diagnostics import (
    enrich_match_diagnostics_payload,
    is_match_diagnostics_fresh,
    prepare_match_diagnostics_reason_table,
    prepare_match_diagnostics_resolver_table,
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
    get_matcher_parallel_requests,
    get_matcher_skip_weak_shortlist,
    get_upload_dir,
)
from catalog_merge import get_catalog_readiness, get_merged_catalog_path, refresh_merged_catalog
from catalog_schema import normalize_header
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
    is_processing_run_cancel_requested,
    list_processing_runs,
    load_processing_run_coverage_audit,
    load_processing_run_dataframe,
    load_processing_run_match_diagnostics,
    load_processing_run_progress,
    load_processing_run_stats,
    mark_stale_running_runs_as_interrupted,
    request_processing_run_cancel,
    save_processing_run_draft,
    write_processing_run_coverage_audit,
    write_processing_run_match_diagnostics,
    write_processing_run_progress,
)
from processing_worker import (
    build_main_kp_result_df as _build_main_kp_result_df,
    compute_business_run_summary as _compute_business_run_summary,
    request_cancel as _request_worker_cancel,
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
ACTIVE_RUN_AUTOREFRESH_MS = 1000
ACTIVE_RUN_FRAGMENT_REFRESH_INTERVAL = f"{max(1, ACTIVE_RUN_AUTOREFRESH_MS // 1000)}s"
CATALOG_AUDIT_FRAGMENT_REFRESH_INTERVAL = "2s"
CATALOG_AUDIT_PROGRESS_LOG_INTERVAL_SEC = 5.0
_CATALOG_AUDIT_TASKS: dict[str, dict[str, Any]] = {}
_CATALOG_AUDIT_TASKS_LOCK = threading.Lock()

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
_ss = st.session_state
if 'matcher'                         not in _ss: _ss.matcher                         = None
if 'df_processed'                    not in _ss: _ss.df_processed                    = None
if 'stats'                           not in _ss: _ss.stats                           = None
if 'corrections'                     not in _ss: _ss.corrections                     = {}
if 'db_csv_path'                     not in _ss: _ss.db_csv_path                     = str(get_merged_catalog_path(get_upload_dir() / "clean"))
if 'matcher_db_csv'                  not in _ss: _ss.matcher_db_csv                  = None
if 'matcher_parallel_requests'       not in _ss: _ss.matcher_parallel_requests       = get_matcher_parallel_requests()
if 'matcher_mode'                    not in _ss: _ss.matcher_mode                    = 'exact'
if 'matcher_gemini_shortlist_limit'  not in _ss: _ss.matcher_gemini_shortlist_limit  = get_matcher_gemini_shortlist_limit()
if 'matcher_gemini_chunk_size'       not in _ss: _ss.matcher_gemini_chunk_size       = get_matcher_gemini_chunk_size()
if 'matcher_gemini_max_chunks'       not in _ss: _ss.matcher_gemini_max_chunks       = get_matcher_gemini_max_chunks()
if 'matcher_local_recall_pool'       not in _ss: _ss.matcher_local_recall_pool       = get_matcher_local_recall_pool()
if 'matcher_skip_weak_shortlist'     not in _ss: _ss.matcher_skip_weak_shortlist     = get_matcher_skip_weak_shortlist()
if 'matcher_settings_signature'      not in _ss: _ss.matcher_settings_signature      = None
if 'show_results'                    not in _ss: _ss.show_results                    = False
if 'show_corrections'                not in _ss: _ss.show_corrections                = False
if 'active_run_id'                   not in _ss: _ss.active_run_id                   = None
if 'active_run_status'               not in _ss: _ss.active_run_status               = None
if 'active_run_loaded_at'            not in _ss: _ss.active_run_loaded_at            = None
if 'active_run_mode'                 not in _ss: _ss.active_run_mode                 = "view"
if 'last_run_restore_attempted'      not in _ss: _ss.last_run_restore_attempted      = False
if 'processing_thread_started_run_id' not in _ss: _ss.processing_thread_started_run_id = None
if 'catalog_snapshot_bundle'         not in _ss: _ss.catalog_snapshot_bundle         = None
if 'catalog_snapshot_xlsx_status'    not in _ss: _ss.catalog_snapshot_xlsx_status    = "idle"
if 'catalog_snapshot_xlsx_path'      not in _ss: _ss.catalog_snapshot_xlsx_path      = None
if 'catalog_snapshot_xlsx_url'       not in _ss: _ss.catalog_snapshot_xlsx_url       = None
if 'catalog_snapshot_drive_csv_url'  not in _ss: _ss.catalog_snapshot_drive_csv_url  = None
if 'catalog_snapshot_drive_csv_name' not in _ss: _ss.catalog_snapshot_drive_csv_name = None
if 'catalog_snapshot_r2_csv_url'     not in _ss: _ss.catalog_snapshot_r2_csv_url     = None
if 'catalog_snapshot_r2_csv_key'     not in _ss: _ss.catalog_snapshot_r2_csv_key     = None
if 'search_catalog_export_url'       not in _ss: _ss.search_catalog_export_url       = None
if 'search_catalog_export_name'      not in _ss: _ss.search_catalog_export_name      = None


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
    mode_labels = {
        "exact": "Точный матч",
        "analog": "Аналог/замена",
        "assembly": "Сборка/заготовка",
    }
    try:
        return st.selectbox(
            "Режим сопоставления",
            options=mode_options,
            index=mode_options.index(fallback_mode),
            format_func=lambda value: mode_labels.get(value, value),
            help=(
                "exact: только строгие совпадения по типу товара. "
                "analog: допускает близкие аналоги, но не подменяет тип товара "
                "(например, патч-корд не заменяется витой парой в бухте). "
                "assembly: для patch_cord может вернуть patch-like кабель или заготовку как материал под сборку, "
                "но не выдает это за точное совпадение."
            ),
        )
    except Exception as e:
        logger.error("❌ Ошибка рендера выбора режима matcher, применён fallback '%s': %s", fallback_mode, e)
        st.warning("⚠️ Не удалось отрисовать selector режима matcher, применён fallback.")
        return fallback_mode

def _current_matcher_runtime_settings() -> dict[str, Any]:
    return {
        "parallel_requests": int(st.session_state.get('matcher_parallel_requests', get_matcher_parallel_requests())),
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
        parallel_requests=int(settings.get("parallel_requests", get_matcher_parallel_requests())),
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
        message="Прогон создан и ожидает запуска фонового процесса",
    )

    matcher_settings = _current_matcher_runtime_settings()
    settings_path = artifacts.run_dir / "settings.json"
    settings_path.write_text(json.dumps(matcher_settings, ensure_ascii=False), encoding="utf-8")
    worker_script = str(Path(__file__).resolve().parent / "processing_worker.py")
    proc = subprocess.Popen(
        [sys.executable, worker_script, run.run_id, str(settings_path)],
        cwd=str(Path(__file__).resolve().parent),
    )
    logger.info("🚀 Worker subprocess started: pid=%s run_id=%s source=%s", proc.pid, run.run_id, source_kind)
    st.session_state.active_run_id = run.run_id
    st.session_state.active_run_status = "queued"
    st.session_state.active_run_loaded_at = None
    st.session_state.active_run_mode = "view"
    st.session_state.processing_thread_started_run_id = run.run_id
    st.session_state.df_processed = None
    st.session_state.stats = None
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


def _parse_run_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _format_elapsed_duration(seconds_total: int) -> str:
    seconds_total = max(0, int(seconds_total))
    hours, remainder = divmod(seconds_total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}ч {minutes:02d}м {seconds:02d}с"
    if minutes:
        return f"{minutes}м {seconds:02d}с"
    return f"{seconds}с"


def _get_run_elapsed_label(run: Any) -> str | None:
    started_at = _parse_run_timestamp(getattr(run, "started_at", None))
    if started_at is None:
        return None
    if started_at.tzinfo is None:
        finished_at = _parse_run_timestamp(getattr(run, "updated_at", None)) or datetime.now()
    else:
        finished_at = _parse_run_timestamp(getattr(run, "updated_at", None)) or datetime.now(started_at.tzinfo)
    if getattr(run, "status", None) in ("queued", "running"):
        finished_at = datetime.now(started_at.tzinfo) if started_at.tzinfo is not None else datetime.now()
    return _format_elapsed_duration(int((finished_at - started_at).total_seconds()))


def _refresh_active_run_for_display() -> Any:
    run_for_display = _get_active_or_preferred_run()
    if run_for_display is None:
        return None
    st.session_state.active_run_status = run_for_display.status
    return run_for_display


def _render_active_run_panel_contents(run_for_display: Any) -> None:
    status_labels = {
        "queued": "В очереди",
        "running": "Выполняется",
        "completed": "Завершен",
        "failed": "Ошибка",
        "interrupted": "Прерван",
    }
    auto_refresh_allowed = run_for_display.status in ("queued", "running")

    st.subheader("Текущий прогон")
    st.write(f"**ID:** `{run_for_display.run_id}`")
    st.write(f"**Файл:** {run_for_display.input_filename}")
    st.write(f"**Статус:** {status_labels.get(run_for_display.status, run_for_display.status)}")
    st.write(f"**Источник каталога:** {run_for_display.catalog_source_kind}")
    st.write(f"**Создан:** {run_for_display.created_at}")
    if run_for_display.started_at:
        st.write(f"**Старт:** {run_for_display.started_at}")
    st.write(f"**Обновлен:** {run_for_display.updated_at}")
    elapsed_label = _get_run_elapsed_label(run_for_display)
    if elapsed_label:
        st.write(f"**Длительность:** {elapsed_label}")

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
            "interrupted": "Остановлено",
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
        st.write(f"**Этап:** {stage_labels.get(progress_stage, progress_stage or 'Неизвестно')}")
        st.progress(normalized_progress)
        if current is not None and total is not None and int(total) > 0:
            st.caption(f"Прогресс: {int(current)} / {int(total)}")
        if progress_message:
            st.caption(progress_message)
        if auto_refresh_allowed:
            st.caption("Статус обновляется автоматически каждую секунду.")
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

    action_col, clear_col = st.columns([3, 1])
    with action_col:
        if auto_refresh_allowed:
            cancel_already_requested = is_processing_run_cancel_requested(run_for_display.run_id)
            if cancel_already_requested:
                st.caption("Остановка уже запрошена")
            if st.button(
                "⏹ Остановить прогон",
                key="cancel_active_run",
                disabled=cancel_already_requested,
            ):
                current_progress = _load_run_progress_safe(run_for_display.run_id) or {}
                _request_worker_cancel(run_for_display.run_id)
                request_processing_run_cancel(run_for_display.run_id)
                write_processing_run_progress(
                    run_for_display.run_id,
                    stage=str(current_progress.get("stage") or "processing"),
                    current=current_progress.get("current"),
                    total=current_progress.get("total"),
                    percent=current_progress.get("percent"),
                    message="Запрошена остановка прогона. Ожидаем безопасного завершения текущих задач.",
                )
                st.warning("Остановка запрошена. Прогон завершится на ближайшей безопасной точке.")
        else:
            if st.button("📌 Открыть результат ниже", key="open_active_run_results"):
                st.session_state.active_run_id = run_for_display.run_id
                st.session_state.active_run_status = run_for_display.status
                st.info("Прокрутите ниже до блока результата на вкладке «Заполнение КП».")
    with clear_col:
        if st.button("🧹 Сбросить выбор", key="clear_active_run_selection"):
            st.session_state.active_run_id = None
            st.session_state.active_run_status = None
            _clear_loaded_run_cache()
            st.success("Выбор активного прогона очищен")


@st.fragment(run_every=ACTIVE_RUN_FRAGMENT_REFRESH_INTERVAL)
def _render_active_run_panel_live() -> None:
    run_for_display = _refresh_active_run_for_display()
    if run_for_display is None:
        return
    _render_active_run_panel_contents(run_for_display)
    if run_for_display.status not in ("queued", "running"):
        # Делаем полный rerun только один раз при переходе в финальный статус,
        # чтобы обновить основную страницу (загрузить результаты).
        last_completed = st.session_state.get("_completion_rerun_run_id")
        if last_completed != run_for_display.run_id:
            st.session_state["_completion_rerun_run_id"] = run_for_display.run_id
            st.rerun()


def _render_active_run_panel_static() -> None:
    run_for_display = _refresh_active_run_for_display()
    if run_for_display is None:
        return
    _render_active_run_panel_contents(run_for_display)


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
def show_statistics(stats, *, include_debug_details: bool = True):
    """Отобразить статистику."""
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

    if not include_debug_details:
        return

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


def _render_main_kp_statistics(stats: dict[str, Any], df: pd.DataFrame) -> None:
    """Операционная сводка для основного сценария заполнения КП."""
    business_summary = dict(stats.get("business_summary", {}) or _compute_business_run_summary(df, stats))
    total = int(business_summary.get("total", 0))
    filled = int(business_summary.get("found", 0))
    not_found = int(business_summary.get("not_found", 0))
    review_count = int(business_summary.get("requires_review", 0))
    errors = int(business_summary.get("errors", 0))

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("📌 Всего строк", total)
    with col2:
        st.metric("✅ Заполнено", filled)
    with col3:
        st.metric("❌ Не найдено", not_found)
    with col4:
        st.metric("📝 Требует проверки", review_count)
    with col5:
        st.metric("⚠️ Ошибок", errors)




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


def _catalog_audit_now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get_catalog_audit_task(run_id: str) -> dict[str, Any] | None:
    with _CATALOG_AUDIT_TASKS_LOCK:
        task = _CATALOG_AUDIT_TASKS.get(str(run_id))
        return dict(task) if isinstance(task, dict) else None


def _new_catalog_audit_task_token() -> str:
    return uuid.uuid4().hex


def _begin_catalog_audit_task(run_id: str) -> dict[str, Any] | None:
    normalized_run_id = str(run_id)
    with _CATALOG_AUDIT_TASKS_LOCK:
        existing = dict(_CATALOG_AUDIT_TASKS.get(normalized_run_id) or {})
        if str(existing.get("status") or "").strip().lower() in {"queued", "running"}:
            return None
        timestamp = _catalog_audit_now_iso()
        task = {
            "run_id": normalized_run_id,
            "task_token": _new_catalog_audit_task_token(),
            "status": "queued",
            "stage": "queued",
            "started_at": timestamp,
            "updated_at": timestamp,
            "finished_at": "",
            "message": "Аудит поставлен в очередь фоновой обработки.",
            "rows_considered": 0,
            "rows_in_scope": 0,
            "catalog_rows_scanned": 0,
            "total_catalog_rows": 0,
            "rows_analyzed": 0,
            "error": "",
        }
        _CATALOG_AUDIT_TASKS[normalized_run_id] = task
        return dict(task)


def _set_catalog_audit_task(run_id: str, **updates: Any) -> dict[str, Any]:
    with _CATALOG_AUDIT_TASKS_LOCK:
        task = dict(_CATALOG_AUDIT_TASKS.get(str(run_id)) or {})
        task.update(updates)
        task["run_id"] = str(run_id)
        task["updated_at"] = _catalog_audit_now_iso()
        _CATALOG_AUDIT_TASKS[str(run_id)] = task
        return dict(task)


def _set_catalog_audit_task_if_current(run_id: str, task_token: str, **updates: Any) -> dict[str, Any] | None:
    with _CATALOG_AUDIT_TASKS_LOCK:
        task = dict(_CATALOG_AUDIT_TASKS.get(str(run_id)) or {})
        if not task or str(task.get("task_token") or "") != str(task_token):
            return None
        task.update(updates)
        task["run_id"] = str(run_id)
        task["updated_at"] = _catalog_audit_now_iso()
        _CATALOG_AUDIT_TASKS[str(run_id)] = task
        return dict(task)


def _clear_catalog_audit_task(run_id: str) -> None:
    with _CATALOG_AUDIT_TASKS_LOCK:
        _CATALOG_AUDIT_TASKS.pop(str(run_id), None)


def _catalog_audit_stage_label(stage: str, *, status: str = "") -> str:
    normalized_stage = str(stage or "").strip().lower()
    normalized_status = str(status or "").strip().lower()
    labels = {
        "queued": "В очереди",
        "preparing": "Подготовка",
        "scanning_catalog": "Сканирование каталога",
        "finalizing": "Формирование сводки",
        "completed": "Готово",
        "failed": "Ошибка",
    }
    if normalized_stage in labels:
        return labels[normalized_stage]
    if normalized_status in labels:
        return labels[normalized_status]
    return normalized_stage or normalized_status or "Подготовка"


def _catalog_audit_elapsed_seconds(task_state: dict[str, Any]) -> int | None:
    started_at = _parse_run_timestamp(str(task_state.get("started_at") or ""))
    if started_at is None:
        return None
    updated_at = _parse_run_timestamp(str(task_state.get("updated_at") or ""))
    finished_at = _parse_run_timestamp(str(task_state.get("finished_at") or ""))
    if finished_at is not None:
        current = finished_at
    elif updated_at is not None:
        current = updated_at
    elif started_at.tzinfo is None:
        current = datetime.now()
    else:
        current = datetime.now(started_at.tzinfo)
    return max(0, int((current - started_at).total_seconds()))


def _catalog_audit_eta_seconds(task_state: dict[str, Any]) -> int | None:
    elapsed_seconds = _catalog_audit_elapsed_seconds(task_state)
    total_catalog_rows = int(task_state.get("total_catalog_rows") or 0)
    catalog_rows_scanned = int(task_state.get("catalog_rows_scanned") or 0)
    status = str(task_state.get("status") or "").strip().lower()
    if status != "running" or elapsed_seconds is None or elapsed_seconds <= 0:
        return None
    if total_catalog_rows <= 0 or catalog_rows_scanned <= 0 or catalog_rows_scanned >= total_catalog_rows:
        return None
    rate = float(catalog_rows_scanned) / float(elapsed_seconds)
    if rate <= 0:
        return None
    remaining_rows = max(0, total_catalog_rows - catalog_rows_scanned)
    return int(round(remaining_rows / rate))


def _catalog_audit_progress_value(task_state: dict[str, Any]) -> float:
    status = str(task_state.get("status") or "").strip().lower()
    stage = str(task_state.get("stage") or "").strip().lower()
    if status == "completed":
        return 1.0
    if status == "failed":
        return 0.0
    if status == "queued":
        return 0.05
    if stage == "preparing":
        return 0.15
    if stage == "scanning_catalog":
        total_catalog_rows = int(task_state.get("total_catalog_rows") or 0)
        catalog_rows_scanned = int(task_state.get("catalog_rows_scanned") or 0)
        if total_catalog_rows > 0:
            scan_ratio = min(1.0, max(0.0, float(catalog_rows_scanned) / float(total_catalog_rows)))
            return 0.15 + 0.75 * scan_ratio
        return 0.55
    if stage == "finalizing":
        return 0.9
    return 0.25


def _render_catalog_audit_task_status_contents(task_state: dict[str, Any]) -> None:
    status = str(task_state.get("status") or "").strip().lower()
    message = str(task_state.get("message") or "").strip()
    stage = str(task_state.get("stage") or "").strip()
    rows_in_scope = int(task_state.get("rows_in_scope") or 0)
    rows_considered = int(task_state.get("rows_considered") or 0)
    catalog_rows_scanned = int(task_state.get("catalog_rows_scanned") or 0)
    total_catalog_rows = int(task_state.get("total_catalog_rows") or 0)
    rows_analyzed = int(task_state.get("rows_analyzed") or 0)
    started_at = str(task_state.get("started_at") or "").strip()
    stage_label = _catalog_audit_stage_label(stage, status=status)
    elapsed_seconds = _catalog_audit_elapsed_seconds(task_state)
    eta_seconds = _catalog_audit_eta_seconds(task_state)

    if status in {"queued", "running"}:
        st.info(message or "Аудит строится в фоне.")
    elif status == "completed":
        st.success(message or "Аудит построен.")
    elif status == "failed":
        st.error(message or "Не удалось построить аудит.")

    st.progress(_catalog_audit_progress_value(task_state))
    primary_parts: list[str] = [f"Этап: {stage_label}"]
    if elapsed_seconds is not None:
        primary_parts.append(f"Длительность: {_format_elapsed_duration(elapsed_seconds)}")
    if eta_seconds is not None:
        primary_parts.append(f"Осталось примерно: {_format_elapsed_duration(eta_seconds)}")
    if total_catalog_rows > 0:
        percent = min(100.0, max(0.0, (float(catalog_rows_scanned) / float(total_catalog_rows)) * 100.0))
        primary_parts.append(
            f"Сканирование: {catalog_rows_scanned:,} / {total_catalog_rows:,} ({percent:.1f}%)"
        )
    elif catalog_rows_scanned > 0:
        primary_parts.append(f"Просканировано релевантных строк каталога: {catalog_rows_scanned:,}")
    st.caption(" | ".join(primary_parts))
    meta_parts: list[str] = []
    if started_at:
        meta_parts.append(f"Старт: {started_at}")
    if rows_considered > 0:
        meta_parts.append(f"Строк к проверке: {rows_considered}")
    if rows_in_scope > 0:
        meta_parts.append(f"В scope: {rows_in_scope}")
    if rows_analyzed > 0:
        meta_parts.append(f"Проанализировано: {rows_analyzed}")
    if meta_parts:
        st.caption(" | ".join(meta_parts))


@st.fragment(run_every=CATALOG_AUDIT_FRAGMENT_REFRESH_INTERVAL)
def _render_catalog_audit_task_live(run_id: str) -> None:
    task_state = _get_catalog_audit_task(run_id)
    if task_state is None:
        st.rerun()
        return
    _render_catalog_audit_task_status_contents(task_state)
    if str(task_state.get("status") or "").strip().lower() not in {"queued", "running"}:
        st.rerun()


def _run_catalog_coverage_audit_background(
    *,
    run_id: str,
    task_token: str,
    df: pd.DataFrame,
    catalog_source_path: Path,
    catalog_source_kind: str,
    diagnostics_payload: dict[str, Any] | None,
) -> None:
    _set_catalog_audit_task_if_current(
        run_id,
        task_token,
        status="running",
        stage="preparing",
        message="Подготовка фонового аудита покрытия каталога.",
        rows_considered=0,
        rows_in_scope=0,
        catalog_rows_scanned=0,
        total_catalog_rows=0,
        rows_analyzed=0,
        error="",
        finished_at="",
    )

    last_progress_log_at = 0.0
    last_logged_stage = ""

    def _progress_callback(progress: dict[str, Any]) -> None:
        nonlocal last_progress_log_at, last_logged_stage
        task_state = _set_catalog_audit_task_if_current(run_id, task_token, status="running", **dict(progress or {}))
        if task_state is None:
            return
        now_mono = time.monotonic()
        stage_name = str(task_state.get("stage") or "").strip().lower()
        if stage_name != last_logged_stage or (now_mono - last_progress_log_at) >= CATALOG_AUDIT_PROGRESS_LOG_INTERVAL_SEC:
            scanned = int(task_state.get("catalog_rows_scanned") or 0)
            total = int(task_state.get("total_catalog_rows") or 0)
            rows_in_scope = int(task_state.get("rows_in_scope") or 0)
            rows_analyzed = int(task_state.get("rows_analyzed") or 0)
            if total > 0:
                logger.info(
                    "📊 Coverage audit progress: run=%s stage=%s scanned=%s/%s scope=%s analyzed=%s",
                    run_id,
                    stage_name or "unknown",
                    scanned,
                    total,
                    rows_in_scope,
                    rows_analyzed,
                )
            else:
                logger.info(
                    "📊 Coverage audit progress: run=%s stage=%s scanned=%s scope=%s analyzed=%s",
                    run_id,
                    stage_name or "unknown",
                    scanned,
                    rows_in_scope,
                    rows_analyzed,
                )
            last_logged_stage = stage_name
            last_progress_log_at = now_mono

    try:
        payload = build_catalog_coverage_audit(
            df,
            run_id=run_id,
            catalog_source_path=catalog_source_path,
            catalog_source_kind=catalog_source_kind,
            diagnostics_payload=diagnostics_payload,
            progress_callback=_progress_callback,
        )
        write_processing_run_coverage_audit(run_id, payload)
        summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
        task_state = _get_catalog_audit_task(run_id)
        _set_catalog_audit_task_if_current(
            run_id,
            task_token,
            status="completed",
            stage="completed",
            message=(
                "Аудит покрытия каталога сохранен. "
                f"Строк в scope: {int(summary.get('rows_analyzed', 0) or 0)}"
            ),
            rows_analyzed=int(summary.get("rows_analyzed", 0) or 0),
            catalog_rows_scanned=int(task_state.get("catalog_rows_scanned") or 0) if task_state else 0,
            total_catalog_rows=int(task_state.get("total_catalog_rows") or 0) if task_state else 0,
            finished_at=_catalog_audit_now_iso(),
        )
        logger.info("✅ Background coverage audit completed: %s", run_id)
    except Exception as exc:
        logger.error("❌ Background coverage audit failed for %s: %s", run_id, exc, exc_info=True)
        _set_catalog_audit_task_if_current(
            run_id,
            task_token,
            status="failed",
            stage="failed",
            message=f"Не удалось построить аудит покрытия каталога: {exc}",
            error=str(exc),
            finished_at=_catalog_audit_now_iso(),
        )


def _start_catalog_coverage_audit_background(
    *,
    run_id: str,
    df: pd.DataFrame,
    catalog_source_path: Path,
    catalog_source_kind: str,
    diagnostics_payload: dict[str, Any] | None,
) -> bool:
    started_task = _begin_catalog_audit_task(run_id)
    if started_task is None:
        return False

    worker = threading.Thread(
        target=_run_catalog_coverage_audit_background,
        kwargs={
            "run_id": run_id,
            "task_token": str(started_task.get("task_token") or ""),
            "df": df.copy(),
            "catalog_source_path": Path(catalog_source_path),
            "catalog_source_kind": str(catalog_source_kind),
            "diagnostics_payload": dict(diagnostics_payload) if isinstance(diagnostics_payload, dict) else None,
        },
        name=f"coverage_audit_{run_id}",
        daemon=True,
    )
    worker.start()
    logger.info("🧵 Background coverage audit thread started: run_id=%s", run_id)
    return True


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
    catalog_gap_count = int(root_cause_class_counts.get("catalog_gap", 0))
    retrieval_ranking_count = int(root_cause_class_counts.get("matcher_retrieval_or_ranking", 0))
    gemini_policy_count = int(root_cause_class_counts.get("gemini_or_decision_policy", 0))
    input_query_shape_count = int(root_cause_class_counts.get("input_or_query_shape", 0))
    not_audited_family_count = int(root_cause_class_counts.get("not_audited_family", 0))

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("catalog gap", catalog_gap_count)
    with col2:
        st.metric("retrieval/ranking", retrieval_ranking_count)
    with col3:
        st.metric("Gemini/policy", gemini_policy_count)
    with col4:
        st.metric("input/query shape", input_query_shape_count)
    with col5:
        st.metric("not audited family", not_audited_family_count)

    if not_audited_family_count > 0:
        if catalog_gap_count == 0 and retrieval_ranking_count == 0 and gemini_policy_count == 0 and input_query_shape_count == 0:
            st.warning(
                "Диагностика построена, но все проблемные строки для этого прогона сейчас вне текущего audit scope. "
                "Они помечены как `not_audited_family`, поэтому rich telecom-root-cause детализация тут не появится."
            )
        else:
            st.info(
                f"Часть строк вне текущего audit scope: `not_audited_family = {not_audited_family_count}`. "
                "Это нормально для cable/electrical файлов: диагностика сохранена, но детализация по ним пока ограничена."
            )

    stage_table = prepare_match_diagnostics_stage_table(diagnostics_payload)
    root_cause_table = prepare_match_diagnostics_root_cause_table(diagnostics_payload)
    reason_table = prepare_match_diagnostics_reason_table(diagnostics_payload)
    resolver_table = prepare_match_diagnostics_resolver_table(diagnostics_payload)
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
            ("resolver_summary", resolver_table),
            ("details", detail_table),
        ]
    )
    st.download_button(
        "📥 Скачать всю диагностику",
        diagnostics_export,
        file_name=f"match_diagnostics_{run.run_id}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"download_match_diagnostics_{run.run_id}",
        on_click="ignore",
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

    if not resolver_table.empty:
        st.markdown("**Сводка по resolver**")
        st.dataframe(_prepare_df_for_display(resolver_table), width="stretch")

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
    diagnostics_payload = None
    task_state = _get_catalog_audit_task(run.run_id)
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

    try:
        stored_diagnostics_payload = load_processing_run_match_diagnostics(run.run_id)
        if is_match_diagnostics_fresh(stored_diagnostics_payload, run_id=run.run_id):
            diagnostics_payload = stored_diagnostics_payload
    except Exception as exc:
        logger.warning("Не удалось загрузить runtime-диагностику для аудита прогона %s: %s", run.run_id, exc)

    if task_state and str(task_state.get("status") or "").strip().lower() == "completed":
        st.success(str(task_state.get("message") or "Аудит покрытия каталога сохранен."))
    elif task_state and str(task_state.get("status") or "").strip().lower() == "failed":
        st.error(str(task_state.get("message") or "Не удалось построить аудит покрытия каталога."))

    task_active = bool(task_state) and str(task_state.get("status") or "").strip().lower() in {"queued", "running"}
    task_finished = bool(task_state) and str(task_state.get("status") or "").strip().lower() in {"completed", "failed"}
    button_col, status_col = st.columns([1, 2])
    with button_col:
        run_audit = st.button(
            "🔎 Проверить покрытие каталога",
            key=f"catalog_coverage_audit_{run.run_id}",
            disabled=task_active,
        )
    with status_col:
        if task_active:
            st.caption("Аудит строится в фоне. Статус ниже обновляется автоматически.")
        elif audit_payload is not None:
            generated_at = str(audit_payload.get("generated_at") or "").strip()
            if generated_at:
                st.caption(f"Используется сохраненный аудит: {generated_at}")
        elif audit_error is not None:
            st.caption("Сохраненный аудит не удалось прочитать, можно пересчитать.")
        else:
            st.caption("Аудит еще не рассчитывался для этого прогона.")

    if run_audit:
        started = _start_catalog_coverage_audit_background(
            run_id=run.run_id,
            df=df,
            catalog_source_path=run.catalog_source_path,
            catalog_source_kind=run.catalog_source_kind,
            diagnostics_payload=diagnostics_payload,
        )
        if started:
            st.success("✓ Аудит запущен в фоне. Статус ниже обновляется автоматически.")
            st.rerun()
        else:
            st.info("Аудит уже строится. Подождите завершения текущей фоновой задачи.")

    if audit_error is not None and audit_payload is None:
        st.warning(f"⚠️ Не удалось загрузить сохраненный аудит покрытия каталога: {audit_error}")

    if task_active:
        _render_catalog_audit_task_live(run.run_id)
    elif task_finished:
        _render_catalog_audit_task_status_contents(task_state)

    if audit_payload is None:
        if task_active:
            st.info("Аудит сейчас строится в фоне. Дождитесь завершения, таблицы подгрузятся автоматически.")
        else:
            st.info(
                "Нажмите «Проверить покрытие каталога», чтобы получить диагноз по проблемным телеком-строкам "
                "и понять, это пробел БД или точка роста для matcher. Для cable/electrical файлов current scope пока ограничен."
            )
        return

    summary = audit_payload.get("summary", {}) if isinstance(audit_payload, dict) else {}
    audit_rows = audit_payload.get("rows", []) if isinstance(audit_payload, dict) else []
    rows_total = len(audit_rows) if isinstance(audit_rows, list) else 0
    rows_analyzed = int(summary.get("rows_analyzed", 0))
    rows_outside_scope = max(0, rows_total - rows_analyzed)

    metric_col1, metric_col2, metric_col3, metric_col4, metric_col5 = st.columns(5)
    with metric_col1:
        st.metric("Строк в аудите", rows_analyzed)
    with metric_col2:
        st.metric("Пробел каталога", int(summary.get("catalog_missing_family", 0)))
    with metric_col3:
        st.metric("Есть family, нет specs", int(summary.get("catalog_has_family_but_no_compatible_specs", 0)))
    with metric_col4:
        st.metric("Есть совместимые кандидаты", int(summary.get("catalog_has_compatible_candidates", 0)))
    with metric_col5:
        st.metric("Вне audit scope", rows_outside_scope)

    if rows_analyzed == 0 and rows_outside_scope > 0:
        st.warning(
            "Аудит построен, но в текущий telecom-focused scope не попало ни одной строки. "
            f"Вне scope осталось `{rows_outside_scope}` строк, поэтому таблицы ниже пустые."
        )
    elif rows_outside_scope > 0:
        st.info(
            f"Аудит построен частично: вне текущего scope осталось `{rows_outside_scope}` строк. "
            "Для них подробная family/specs-диагностика пока не строится."
        )

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
        on_click="ignore",
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


def _render_static_result_table(
    df: pd.DataFrame,
    *,
    table_class: str = "remo-static-result-table",
    table_layout: str = "fixed",
    font_size: str = "0.92rem",
) -> None:
    """Показать таблицу без встроенного скролла и пагинации."""
    display_df = _prepare_df_for_display(df).where(pd.notna(df), "")
    if display_df.empty:
        st.info("📭 Нет строк для отображения.")
        return

    st.markdown(
        f"""
        <style>
        table.{table_class} {{
            width: 100%;
            border-collapse: collapse;
            table-layout: {table_layout};
            font-size: {font_size};
        }}
        table.{table_class} thead th {{
            background: #f3f5f7;
            border-bottom: 1px solid #d7dce3;
            font-weight: 600;
            padding: 0.55rem 0.7rem;
            text-align: left;
            vertical-align: top;
            white-space: normal;
            word-break: break-word;
        }}
        table.{table_class} tbody td {{
            border-bottom: 1px solid #eceff3;
            padding: 0.5rem 0.7rem;
            vertical-align: top;
            white-space: normal;
            word-break: break-word;
        }}
        table.{table_class} tbody tr:nth-child(even) {{
            background: #fafbfc;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        display_df.to_html(index=False, escape=True, border=0, classes=table_class),
        unsafe_allow_html=True,
    )


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


def _result_download_filename(run, extension: str) -> str:
    suffix = extension if extension.startswith(".") else f".{extension}"
    run_id = str(getattr(run, "run_id", "") or "session")
    return f"result_{run_id}{suffix}"


def _full_result_download_filename(run, extension: str) -> str:
    suffix = extension if extension.startswith(".") else f".{extension}"
    run_id = str(getattr(run, "run_id", "") or "session")
    return f"result_full_{run_id}{suffix}"


def show_corrections_table(df, *, visible_columns: list[str] | None = None):
    if visible_columns is not None:
        visible_columns = [column for column in visible_columns if column in df.columns]
        base_df = df.loc[:, visible_columns].copy()
    else:
        base_df = df.copy()
    # Таблица для ручной коррекции пользовательской версии результата.
    st.subheader("✏️ Коррекция результатов")
    
    # Фильтр: показать только не найденные
    show_only_missing = st.checkbox("Показать только не найденные позиции", value=False)
    
    if show_only_missing:
        missing_mask = (
            base_df['Найденная номенклатура'].isna()
            | (base_df['Найденная номенклатура'].astype(str).str.strip() == '')
            | (base_df['Найденная номенклатура'].astype(str).str.strip() == MISSING_POSITION_TEXT)
        )
        df_view = base_df[missing_mask].copy()
        st.info(f"📌 Найдено {len(df_view)} позиций без сопоставления")
    else:
        df_view = base_df.copy()
    original_index = df_view.index.copy()
    disabled_columns = [column for column in df_view.columns if _is_source_query_column(column)]
    
    # Редактируемая таблица
    st.write("**Отредактируйте результаты в таблице ниже:**")
    
    edited_df = st.data_editor(
        df_view,
        width="stretch",
        disabled=disabled_columns,
        num_rows="fixed"
    )

    updated_df = df.copy()
    edited_df.index = original_index
    updated_df.loc[original_index, list(edited_df.columns)] = edited_df
    return updated_df


def _load_run_results_for_ui(run) -> tuple[pd.DataFrame | None, dict[str, Any] | None, Exception | None]:
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
        return df, stats, None
    except Exception as exc:
        logger.error("❌ Не удалось загрузить результаты прогона %s: %s", run.run_id, exc, exc_info=True)
        return None, None, exc


def _render_debug_run_section(run) -> None:
    st.subheader("Debug по выбранному прогону")
    if run is None:
        st.info("📭 Нет выбранного прогона. Запустите обработку на вкладке «Заполнение КП» или выберите прогон из истории.")
        return
    if run.status in ("queued", "running"):
        st.info(
            f"⏳ Прогон `{run.run_id}` еще выполняется. "
            "После завершения здесь станут доступны диагностика и coverage audit."
        )
        return
    if run.status in ("failed", "interrupted"):
        st.error(
            f"❌ Прогон `{run.run_id}` не завершен: "
            f"{run.error_text or 'подробности отсутствуют'}"
        )
        return

    df, stats, load_error = _load_run_results_for_ui(run)
    if load_error is not None:
        st.error(f"❌ Не удалось загрузить результаты прогона `{run.run_id}`: {load_error}")
        return
    if df is None or stats is None:
        st.error(f"❌ Результаты прогона `{run.run_id}` недоступны")
        return

    st.caption(f"Открыт прогон: `{run.run_id}`")
    show_statistics(stats, include_debug_details=True)
    if str(stats.get("diagnostics_mode") or "").strip().lower() == "lite":
        st.caption("Для ускорения обычного КП-прогона runtime-диагностика не сохранялась автоматически. Во вкладке Debug она достраивается по запросу.")
    with st.expander("Полная таблица результата", expanded=False):
        st.caption("Здесь доступен полный результат прогона со всеми техническими полями. На главной вкладке показывается облегченная КП-версия.")
        full_download_col1, full_download_col2 = st.columns(2)
        with full_download_col1:
            full_excel_buffer = io.BytesIO()
            df.to_excel(full_excel_buffer, index=False, engine="openpyxl")
            full_excel_buffer.seek(0)
            st.download_button(
                "📥 Скачать полный Excel",
                full_excel_buffer.getvalue(),
                _full_result_download_filename(run, ".xlsx"),
                "application/vnd.ms-excel",
                key=f"download_full_result_excel_{run.run_id}",
                on_click="ignore",
            )
        with full_download_col2:
            full_csv_data = df.to_csv(index=False, sep=";", encoding="utf-8").encode("utf-8")
            st.download_button(
                "📥 Скачать полный CSV",
                full_csv_data,
                _full_result_download_filename(run, ".csv"),
                "text/csv",
                key=f"download_full_result_csv_{run.run_id}",
                on_click="ignore",
            )
        _render_static_result_table(
            df,
            table_class="remo-static-full-result-table",
            table_layout="auto",
            font_size="0.82rem",
        )
    st.divider()
    _render_catalog_coverage_audit(run, df)
    st.divider()
    _render_match_diagnostics(run, df)


def _taxonomy_snapshot_download_filename(path: Path) -> str:
    try:
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d_%H%M%S")
    except OSError:
        return path.name
    return f"{path.stem}_{stamp}{path.suffix}"


def _build_branch_cleanup_audit_df(branch_df: pd.DataFrame) -> pd.DataFrame:
    audit_columns = [
        "search_branch_path",
        "branch_total_rows",
        "family_count",
        "top_family",
        "top_family_rows",
        "top_family_share",
        "second_family",
        "second_family_rows",
        "second_family_share",
        "other_rows",
        "other_share",
        "suspicious_score",
        "top_families",
    ]
    if branch_df.empty:
        return pd.DataFrame(columns=audit_columns)

    prepared = branch_df.copy()
    prepared["branch_total_rows"] = pd.to_numeric(prepared["branch_total_rows"], errors="coerce").fillna(0).astype(int)
    prepared["rows_count"] = pd.to_numeric(prepared["rows_count"], errors="coerce").fillna(0).astype(int)
    prepared["family_share_within_branch"] = pd.to_numeric(
        prepared["family_share_within_branch"], errors="coerce"
    ).fillna(0.0)

    audit_rows: list[dict[str, Any]] = []
    for branch_path, group in prepared.groupby("search_branch_path", dropna=False):
        group = group.sort_values(["rows_count", "effective_family"], ascending=[False, True], kind="stable")
        if group.empty:
            continue

        branch_total_rows = int(group["branch_total_rows"].iloc[0])
        if branch_total_rows <= 0:
            continue

        family_items = [
            {
                "family": str(row["effective_family"]),
                "rows_count": int(row["rows_count"]),
                "share": float(row["family_share_within_branch"]),
            }
            for _, row in group.iterrows()
        ]
        family_count = len(family_items)
        top = family_items[0]
        second = family_items[1] if family_count > 1 else {"family": "", "rows_count": 0, "share": 0.0}
        other_item = next((item for item in family_items if item["family"] == "other"), {"rows_count": 0, "share": 0.0})

        suspicious = (
            branch_total_rows >= 100
            and (
                top["family"] == "other"
                or top["share"] < 0.85
                or second["share"] >= 0.10
                or family_count >= 5
                or other_item["share"] >= 0.10
            )
        )
        if not suspicious:
            continue

        suspicious_score = round(
            (1.0 - top["share"]) * branch_total_rows
            + second["share"] * branch_total_rows
            + max(0, family_count - 2) * 25
            + other_item["share"] * branch_total_rows,
            3,
        )
        audit_rows.append(
            {
                "search_branch_path": branch_path,
                "branch_total_rows": branch_total_rows,
                "family_count": family_count,
                "top_family": top["family"],
                "top_family_rows": top["rows_count"],
                "top_family_share": round(top["share"], 6),
                "second_family": second["family"],
                "second_family_rows": second["rows_count"],
                "second_family_share": round(float(second["share"]), 6),
                "other_rows": int(other_item["rows_count"]),
                "other_share": round(float(other_item["share"]), 6),
                "suspicious_score": suspicious_score,
                "top_families": " | ".join(
                    f"{item['family']} ({item['rows_count']})" for item in family_items[:5]
                ),
            }
        )

    audit_df = pd.DataFrame(audit_rows, columns=audit_columns)
    if audit_df.empty:
        return pd.DataFrame(columns=audit_columns)
    return audit_df.sort_values(
        ["suspicious_score", "branch_total_rows", "search_branch_path"],
        ascending=[False, False, True],
        kind="stable",
    ).reset_index(drop=True)


def _render_search_taxonomy_snapshot_section(clean_dir: Path | None) -> None:
    st.subheader("🧭 Структура taxonomy")
    st.caption(
        "Snapshot дерева и branch-to-family mapping, собранные во время последней пересборки поисковой БД."
    )
    if clean_dir is None:
        st.info("📭 Папка clean еще не определена.")
        return

    try:
        tree_path, branch_summary_path = ensure_search_taxonomy_snapshot(clean_dir)
        snapshot = json.loads(tree_path.read_text(encoding="utf-8"))
    except Exception as exc:
        st.error(f"❌ Не удалось прочитать taxonomy snapshot: {exc}")
        return

    catalog_stats = dict(snapshot.get("catalog_stats", {}) or {})
    family_counts = list(catalog_stats.get("family_counts", []) or [])
    top_branches = list(catalog_stats.get("top_branches", []) or [])
    families = dict(snapshot.get("families", {}) or {})
    branches = dict(snapshot.get("branches", {}) or {})

    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("Family", int(snapshot.get("family_count", len(families))))
    metric_col2.metric("Registry branches", int(snapshot.get("branch_count", len(branches))))
    metric_col3.metric("Rows in search DB", int(catalog_stats.get("rows_total", 0)))
    st.caption(f"Snapshot: `{tree_path}`")

    download_col1, download_col2 = st.columns(2)
    with download_col1:
        st.download_button(
            "📥 Скачать taxonomy_tree.json",
            tree_path.read_bytes(),
            file_name=_taxonomy_snapshot_download_filename(tree_path),
            mime="application/json",
            key="download_taxonomy_tree_json",
            on_click="ignore",
        )
    with download_col2:
        if branch_summary_path.exists():
            st.download_button(
                "📥 Скачать taxonomy_branch_family_summary.csv",
                branch_summary_path.read_bytes(),
                file_name=_taxonomy_snapshot_download_filename(branch_summary_path),
                mime="text/csv",
                key="download_taxonomy_branch_summary_csv",
                on_click="ignore",
            )

    if family_counts:
        family_df = pd.DataFrame(family_counts)
        st.markdown("**Family counts в поисковой БД**")
        st.dataframe(_prepare_df_for_display(family_df.head(30)), width="stretch")

    family_rows = []
    for family_name, spec in sorted(families.items()):
        default_branches = list(spec.get("default_branches", []) or [])
        family_rows.append(
            {
                "family": family_name,
                "entity_types": ", ".join(spec.get("entity_types", []) or []),
                "default_branches_count": len(default_branches),
                "default_branches": " | ".join(default_branches),
                "retrieval_mode": spec.get("retrieval_mode", ""),
                "strictness": spec.get("strictness", ""),
                "audited": bool(spec.get("audited")),
                "audit_group": spec.get("audit_group_label", "") or spec.get("audit_group", ""),
            }
        )
    if family_rows:
        with st.expander("Registry tree", expanded=False):
            st.dataframe(_prepare_df_for_display(pd.DataFrame(family_rows)), width="stretch")

    if top_branches:
        top_branch_rows = []
        for row in top_branches:
            top_family_pairs = row.get("top_families", []) or []
            top_branch_rows.append(
                {
                    "search_branch_path": row.get("search_branch_path", ""),
                    "rows_total": row.get("rows_total", 0),
                    "top_families": " | ".join(
                        f"{item.get('family', '')} ({item.get('rows_count', 0)})"
                        for item in top_family_pairs
                    ),
                }
            )
        st.markdown("**Top branches по наполнению**")
        st.dataframe(_prepare_df_for_display(pd.DataFrame(top_branch_rows)), width="stretch")

    if branch_summary_path.exists():
        with st.expander("Branch-to-family summary", expanded=False):
            try:
                branch_df = pd.read_csv(branch_summary_path, sep=";", encoding="utf-8")
                branch_df = branch_df.sort_values(
                    by=["branch_total_rows", "rows_count"],
                    ascending=[False, False],
                    kind="stable",
                )
                st.dataframe(_prepare_df_for_display(branch_df.head(100)), width="stretch")
            except Exception as exc:
                st.error(f"❌ Не удалось прочитать branch summary: {exc}")

        try:
            branch_df = pd.read_csv(branch_summary_path, sep=";", encoding="utf-8")
            suspicious_df = _build_branch_cleanup_audit_df(branch_df)
        except Exception as exc:
            st.error(f"❌ Не удалось построить branch cleanup audit: {exc}")
        else:
            st.markdown("**Подозрительные ветки для cleanup**")
            st.caption(
                "На экране показывается top-20 веток с самым большим branch-family шумом. "
                "Выгрузка ниже содержит весь список подозрительных веток."
            )
            if suspicious_df.empty:
                st.success("✅ Явно подозрительных веток по текущим правилам не найдено.")
            else:
                metric_col1, metric_col2 = st.columns(2)
                metric_col1.metric("Подозрительных веток", len(suspicious_df))
                metric_col2.metric("Самая шумная ветка", suspicious_df.iloc[0]["search_branch_path"])
                st.dataframe(_prepare_df_for_display(suspicious_df.head(20)), width="stretch")
                suspicious_csv = suspicious_df.to_csv(index=False, sep=";", encoding="utf-8").encode("utf-8")
                st.download_button(
                    "📥 Скачать все подозрительные ветки",
                    suspicious_csv,
                    file_name=f"taxonomy_branch_cleanup_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    key="download_taxonomy_branch_cleanup_audit_csv",
                    on_click="ignore",
                )


def _render_search_taxonomy_preview_section(clean_dir: Path | None) -> None:
    st.subheader("⚡ Taxonomy preview без rebuild")
    st.caption(
        "Dry-run preview считает дерево и подозрительные ветки прямо из merged CSV, "
        "не пересобирая поисковую БД. Это удобнее для быстрых taxonomy-итераций."
    )
    if clean_dir is None:
        st.info("📭 Папка clean еще не определена.")
        return

    preview_tree_path = clean_dir / "taxonomy_preview_tree.json"
    preview_summary_path = clean_dir / "taxonomy_preview_branch_family_summary.csv"
    preview_audit_path = clean_dir / "taxonomy_preview_branch_cleanup_audit.csv"

    if st.button("⚡ Построить taxonomy preview без rebuild", key="build_taxonomy_preview_btn"):
        try:
            preview_tree_path, preview_summary_path, preview_audit_path = build_search_taxonomy_preview(clean_dir)
            st.success(f"✓ Taxonomy preview обновлен: {preview_tree_path.name}")
        except Exception as exc:
            logger.error("❌ Taxonomy preview build failed: %s", exc, exc_info=True)
            st.error(f"❌ Не удалось построить taxonomy preview: {exc}")

    preview_paths = [preview_tree_path, preview_summary_path, preview_audit_path]
    if not all(path.exists() for path in preview_paths):
        st.info("📭 Preview еще не построен. Нажмите `⚡ Построить taxonomy preview без rebuild`.")
        return

    preview_updated_at = datetime.fromtimestamp(
        min(path.stat().st_mtime for path in preview_paths)
    ).isoformat(timespec="seconds")
    st.caption(f"Последнее обновление preview: {preview_updated_at}")

    download_col1, download_col2, download_col3 = st.columns(3)
    with download_col1:
        st.download_button(
            "📥 Скачать preview tree",
            preview_tree_path.read_bytes(),
            file_name=_taxonomy_snapshot_download_filename(preview_tree_path),
            mime="application/json",
            key="download_taxonomy_preview_tree_json",
            on_click="ignore",
        )
    with download_col2:
        st.download_button(
            "📥 Скачать preview summary",
            preview_summary_path.read_bytes(),
            file_name=_taxonomy_snapshot_download_filename(preview_summary_path),
            mime="text/csv",
            key="download_taxonomy_preview_summary_csv",
            on_click="ignore",
        )
    with download_col3:
        st.download_button(
            "📥 Скачать все подозрительные ветки preview",
            preview_audit_path.read_bytes(),
            file_name=_taxonomy_snapshot_download_filename(preview_audit_path),
            mime="text/csv",
            key="download_taxonomy_preview_audit_csv",
            on_click="ignore",
        )

    try:
        preview_snapshot = json.loads(preview_tree_path.read_text(encoding="utf-8"))
        preview_summary_df = pd.read_csv(preview_summary_path, sep=";", encoding="utf-8")
        preview_audit_df = pd.read_csv(preview_audit_path, sep=";", encoding="utf-8")
    except Exception as exc:
        st.error(f"❌ Не удалось прочитать taxonomy preview: {exc}")
        return

    preview_stats = dict(preview_snapshot.get("catalog_stats", {}) or {})
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("Family в preview", int(preview_snapshot.get("family_count", 0)))
    metric_col2.metric("Rows в preview", int(preview_stats.get("rows_total", 0)))
    metric_col3.metric("Подозрительных веток", len(preview_audit_df))

    if preview_audit_df.empty:
        st.success("✅ В preview нет явно подозрительных веток по текущим правилам.")
    else:
        st.caption(
            "На экране показывается top-20 веток из preview. "
            "Полный список остается в выгрузке `taxonomy_preview_branch_cleanup_audit.csv`."
        )
        st.dataframe(_prepare_df_for_display(preview_audit_df.head(20)), width="stretch")

    st.divider()
    st.markdown("**⚡ Branch probe по выбранным веткам**")
    st.caption(
        "Для быстрых итераций можно пересчитать только выбранные проблемные ветки из текущей search DB, "
        "не гоняя весь preview по всему каталогу."
    )

    branch_options: list[str] = []
    seen_branch_options: set[str] = set()

    def _append_branch_option(value: object) -> None:
        branch_path = str(value or "").strip()
        if not branch_path or branch_path in seen_branch_options:
            return
        seen_branch_options.add(branch_path)
        branch_options.append(branch_path)

    if not preview_audit_df.empty and "search_branch_path" in preview_audit_df.columns:
        for value in preview_audit_df["search_branch_path"].astype(str).tolist():
            _append_branch_option(value)
    if not preview_summary_df.empty and "search_branch_path" in preview_summary_df.columns:
        for value in preview_summary_df["search_branch_path"].astype(str).drop_duplicates().tolist():
            _append_branch_option(value)

    default_branches = branch_options[:3]
    selected_branches = st.multiselect(
        "Выберите ветки для branch probe",
        options=branch_options,
        default=default_branches,
        key="taxonomy_branch_probe_selector",
        help="Сначала идут подозрительные ветки из audit, дальше доступны все ветки из preview summary.",
    )
    manual_branch_text = st.text_input(
        "Или добавьте ветки вручную",
        value="",
        key="taxonomy_branch_probe_manual_branches",
        help="Можно вставить точные branch path через `;` или с новой строки, если их неудобно искать в списке.",
    )
    manual_branches = [
        branch.strip()
        for branch in re.split(r"[;\r\n]+", manual_branch_text or "")
        if branch.strip()
    ]
    selected_branches = selected_branches + [branch for branch in manual_branches if branch not in selected_branches]

    probe_tree_path = clean_dir / "taxonomy_probe_tree.json"
    probe_summary_path = clean_dir / "taxonomy_probe_branch_family_summary.csv"
    probe_audit_path = clean_dir / "taxonomy_probe_branch_cleanup_audit.csv"
    probe_report_path = get_search_taxonomy_probe_report_path(clean_dir)

    if st.button("⚡ Построить branch probe по выбранным веткам", key="build_taxonomy_branch_probe_btn"):
        if not selected_branches:
            st.warning("⚠️ Сначала выберите хотя бы одну ветку для branch probe.")
        else:
            try:
                probe_tree_path, probe_summary_path, probe_audit_path = build_search_taxonomy_branch_probe(
                    clean_dir,
                    selected_branches,
                )
                st.success(f"✓ Branch probe обновлен: {probe_tree_path.name}")
            except Exception as exc:
                logger.error("❌ Taxonomy branch probe failed: %s", exc, exc_info=True)
                st.error(f"❌ Не удалось построить branch probe: {exc}")

    probe_paths = [probe_tree_path, probe_summary_path, probe_audit_path, probe_report_path]
    if not all(path.exists() for path in probe_paths):
        return

    try:
        probe_report = json.loads(probe_report_path.read_text(encoding="utf-8"))
        probe_snapshot = json.loads(probe_tree_path.read_text(encoding="utf-8"))
        probe_summary_df = pd.read_csv(probe_summary_path, sep=";", encoding="utf-8")
        probe_audit_df = pd.read_csv(probe_audit_path, sep=";", encoding="utf-8")
    except Exception as exc:
        st.error(f"❌ Не удалось прочитать branch probe: {exc}")
        return

    probe_stats = dict(probe_snapshot.get("catalog_stats", {}) or {})
    probe_metric_col1, probe_metric_col2, probe_metric_col3 = st.columns(3)
    probe_metric_col1.metric("Rows в branch probe", int(probe_stats.get("rows_total", 0)))
    probe_metric_col2.metric("Выбранных веток", len(probe_stats.get("selected_branches", []) or []))
    probe_metric_col3.metric("Подозрительных веток в probe", len(probe_audit_df))

    st.caption("Для анализа Codex обычно достаточно одного файла `taxonomy_probe_report.json`.")

    probe_download_col1, probe_download_col2 = st.columns([1.4, 1])
    with probe_download_col1:
        st.download_button(
            "📥 Скачать единый branch probe report",
            probe_report_path.read_bytes(),
            file_name=_taxonomy_snapshot_download_filename(probe_report_path),
            mime="application/json",
            key="download_taxonomy_probe_report_json",
            on_click="ignore",
        )
    with probe_download_col2:
        st.caption(
            f"В отчете уже есть: {len(probe_report.get('branches', []) or [])} веток и "
            f"{len(probe_report.get('suspicious_branches', []) or [])} suspicious branches."
        )

    with st.expander("Технические файлы branch probe", expanded=False):
        probe_download_col1, probe_download_col2, probe_download_col3 = st.columns(3)
        with probe_download_col1:
            st.download_button(
                "📥 Скачать branch probe tree",
                probe_tree_path.read_bytes(),
                file_name=_taxonomy_snapshot_download_filename(probe_tree_path),
                mime="application/json",
                key="download_taxonomy_probe_tree_json",
                on_click="ignore",
            )
        with probe_download_col2:
            st.download_button(
                "📥 Скачать branch probe summary",
                probe_summary_path.read_bytes(),
                file_name=_taxonomy_snapshot_download_filename(probe_summary_path),
                mime="text/csv",
                key="download_taxonomy_probe_summary_csv",
                on_click="ignore",
            )
        with probe_download_col3:
            st.download_button(
                "📥 Скачать все подозрительные ветки branch probe",
                probe_audit_path.read_bytes(),
                file_name=_taxonomy_snapshot_download_filename(probe_audit_path),
                mime="text/csv",
                key="download_taxonomy_probe_audit_csv",
                on_click="ignore",
            )

    if probe_report.get("summary_lines"):
        st.caption(" | ".join(str(item) for item in probe_report.get("summary_lines", [])[:5]))

    if probe_audit_df.empty:
        st.success("✅ В branch probe нет явно подозрительных веток по текущим правилам.")
    else:
        st.caption(
            "На экране показывается top-20 веток из branch probe. "
            "Полный список остается в выгрузке `taxonomy_probe_branch_cleanup_audit.csv`."
        )
        st.dataframe(_prepare_df_for_display(probe_audit_df.head(20)), width="stretch")

    st.divider()
    st.markdown("**🧠 Gemini draft для taxonomy**")
    st.caption(
        "Строит черновик mapping только по текущему branch probe. "
        "Ничего не меняет в боевых правилах автоматически: это отдельный draft JSON/CSV для review."
    )
    gemini_api_key = _get_gemini_api_key()
    if not gemini_api_key:
        st.info("🔑 Gemini API key не найден. Draft пока недоступен.")
        return

    draft_json_path = clean_dir / "taxonomy_bootstrap_draft.json"
    draft_csv_path = clean_dir / "taxonomy_bootstrap_draft.csv"
    probe_summary_branch_count = (
        int(probe_summary_df["search_branch_path"].astype(str).nunique())
        if not probe_summary_df.empty and "search_branch_path" in probe_summary_df.columns
        else 0
    )
    max_draft_branches = max(
        1,
        min(
            20,
            probe_summary_branch_count
            if probe_summary_branch_count > 0
            else len(probe_audit_df)
            if not probe_audit_df.empty
            else 1,
        ),
    )
    default_draft_branches = max(1, min(5, max_draft_branches))
    draft_branch_count = int(
        st.number_input(
            "Сколько веток отправлять в Gemini draft",
            min_value=1,
            max_value=max_draft_branches,
            value=default_draft_branches,
            step=1,
            key="taxonomy_bootstrap_branch_count",
            help="Рекомендуется 3-8 веток за итерацию, чтобы draft оставался понятным и дешевым.",
        )
    )
    if st.button("🧠 Построить Gemini draft по branch probe", key="build_taxonomy_bootstrap_draft_btn"):
        try:
            draft_json_path, draft_csv_path = build_search_taxonomy_bootstrap_draft(
                clean_dir,
                api_key=gemini_api_key,
                max_branches=draft_branch_count,
            )
            st.success(f"✓ Gemini draft обновлен: {draft_json_path.name}")
        except Exception as exc:
            logger.error("❌ Taxonomy bootstrap draft failed: %s", exc, exc_info=True)
            st.error(f"❌ Не удалось построить Gemini draft: {exc}")

    if not draft_json_path.exists() or not draft_csv_path.exists():
        return

    try:
        draft_payload = json.loads(draft_json_path.read_text(encoding="utf-8"))
        draft_df = pd.read_csv(draft_csv_path, sep=";", encoding="utf-8")
    except Exception as exc:
        st.error(f"❌ Не удалось прочитать Gemini draft: {exc}")
        return

    draft_metric_col1, draft_metric_col2, draft_metric_col3 = st.columns(3)
    draft_metric_col1.metric("Веток в draft", len(draft_df))
    draft_metric_col2.metric("Модель", str(draft_payload.get("model_name", "")))
    draft_metric_col3.metric(
        "Средняя confidence",
        f"{float(pd.to_numeric(draft_df.get('confidence'), errors='coerce').fillna(0.0).mean() if not draft_df.empty else 0.0):.2f}",
    )

    draft_download_col1, draft_download_col2 = st.columns(2)
    with draft_download_col1:
        st.download_button(
            "📥 Скачать Gemini draft JSON",
            draft_json_path.read_bytes(),
            file_name=_taxonomy_snapshot_download_filename(draft_json_path),
            mime="application/json",
            key="download_taxonomy_bootstrap_draft_json",
            on_click="ignore",
        )
    with draft_download_col2:
        st.download_button(
            "📥 Скачать Gemini draft CSV",
            draft_csv_path.read_bytes(),
            file_name=_taxonomy_snapshot_download_filename(draft_csv_path),
            mime="text/csv",
            key="download_taxonomy_bootstrap_draft_csv",
            on_click="ignore",
        )

    if draft_df.empty:
        st.info("📭 Gemini draft пустой для текущего branch probe.")
    else:
        st.caption(
            "На экране показывается top-20 предложений из Gemini draft. "
            "Полный список остается в выгрузке `taxonomy_bootstrap_draft.csv`."
        )
        st.dataframe(_prepare_df_for_display(draft_df.head(20)), width="stretch")


# ============ MAIN UI ============

def main():
    st.title("🔍 ReMo Matcher")
    st.markdown("*Семантическое сопоставление номенклатуры с товарной БД*")
    build_sha = os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("RAILWAY_GIT_COMMIT")
    if build_sha:
        st.caption(f"Build: `{build_sha[:8]}`")
        logger.info("🚢 Build commit: %s", build_sha)

    _restore_active_run_state()
    tab1, tab2, tab3 = st.tabs(["📄 Заполнение КП", "🧪 Debug / Admin", "📊 История"])

    with st.sidebar:
        st.caption("📄 Основной сценарий: вкладка «Заполнение КП».")
        st.caption("🧪 Технические действия: вкладка «Debug / Admin».")

    with tab2:
        st.header("🧪 Debug / Admin")
        st.caption("Диагностика, coverage audit и техническое управление каталогом и matcher.")
        _render_debug_run_section(_get_active_or_preferred_run())
        st.divider()
        st.subheader("Admin каталога и matcher")

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

        st.divider()
        _render_search_taxonomy_snapshot_section(catalog_readiness.clean_dir)
        st.divider()
        _render_search_taxonomy_preview_section(catalog_readiness.clean_dir)
        st.divider()

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
        parallel_requests = int(st.session_state.get("matcher_parallel_requests", get_matcher_parallel_requests()))
        st.info(
            f"Текущий параллелизм matcher: до {parallel_requests} строк одновременно. "
            "Это главный рычаг ускорения, если Gemini и сеть выдерживают нагрузку."
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
                "Параллельных строк matcher",
                min_value=1,
                max_value=25,
                step=1,
                key="matcher_parallel_requests",
                help="Сколько строк matcher обрабатывает одновременно. Ускоряет прогон, но повышает нагрузку на Gemini API и CPU.",
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

        mode_options = ["exact", "analog", "assembly"]
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
    
    with tab1:
        st.header("📄 Заполнение КП")
        st.markdown(
            "Загрузите КП, и сервис заполнит цену, найденную номенклатуру и артикул. "
            "Если в строке есть артикул, поиск идет сначала по нему; если артикула нет, используется поиск по названию и семейству."
        )

        uploaded_file = st.file_uploader(
            "Выберите Excel файл коммерческого предложения",
            type=['xlsx', 'xls'],
            help="Поддерживаются ReMo-шаблоны и близкие Excel-файлы с колонками вроде 'Наименование' / 'Артикул'. Если заголовки лежат в первой строке таблицы, сервис попробует поднять их автоматически."
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
                        logger.info("✅ Processing run created from UI: %s", run_id)
                        st.success(f"✅ Прогон `{run_id}` запущен в фоне.")
                    except Exception as e:
                        logger.error(f"❌ Ошибка при запуске фоновой обработки: {e}", exc_info=True)
                        st.markdown(
                            f'<div class="error-box">❌ Ошибка запуска обработки: {str(e)}</div>',
                            unsafe_allow_html=True,
                        )
                        st.error(str(e))

        # Панель прогресса рендерится ПОСЛЕ формы, чтобы видеть
        # только что созданный прогон (session_state уже обновлён).
        run_for_display = _get_active_or_preferred_run()
        if run_for_display is not None:
            if run_for_display.status in ("queued", "running"):
                _render_active_run_panel_live()
            else:
                _render_active_run_panel_static()
    
    with tab1:
        st.divider()
        st.subheader("Результат заполнения КП")
        run = _get_active_or_preferred_run()
        if run is None:
            st.info("📤 Загрузите файл КП и запустите обработку. Последних прогонов пока нет.")
        elif run.status in ("queued", "running"):
            st.info(
                f"⏳ Прогон `{run.run_id}` еще выполняется "
                f"({run.status}). Следите за прогрессом выше в блоке «Текущий прогон»."
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
            df, stats, load_error = _load_run_results_for_ui(run)
            if load_error is not None:
                st.error(f"❌ Не удалось загрузить результаты прогона `{run.run_id}`: {load_error}")
                df = None
                stats = None

            if df is not None and stats is not None:
                st.caption(f"Открыт прогон: `{run.run_id}`")
                if has_processing_run_draft(run):
                    st.info("📝 Для этого прогона есть автосохраненный черновик правок.")
                _render_main_kp_statistics(stats, df)
                st.divider()
                st.caption("На главной вкладке показана КП-версия результата без технических debug-колонок. Полная таблица доступна во вкладке «Debug / Admin».")
                main_result_df = _build_main_kp_result_df(df)

                default_mode = "Коррекция" if st.session_state.get("active_run_mode") == "correction" else "Просмотр"
                mode = st.radio(
                    "Режим",
                    ["Просмотр", "Коррекция"],
                    index=1 if default_mode == "Коррекция" else 0,
                    horizontal=True,
                )
                st.session_state.active_run_mode = "correction" if mode == "Коррекция" else "view"

                if mode == "Коррекция":
                    edited_df = show_corrections_table(df, visible_columns=list(main_result_df.columns))
                    if not _dataframes_equal_for_persistence(edited_df, df):
                        save_processing_run_draft(run.run_id, edited_df)
                        st.session_state.df_processed = edited_df.copy()
                        df = edited_df
                        main_result_df = _build_main_kp_result_df(df)
                        run = get_processing_run(run.run_id) or run
                        st.session_state.active_run_loaded_at = run.updated_at
                        st.caption(f"Черновик правок автосохранен: {run.updated_at}")
                    if st.button("💾 Сохранить правки", key="save_corrections"):
                        save_processing_run_draft(run.run_id, df)
                        run = get_processing_run(run.run_id) or run
                        st.session_state.active_run_loaded_at = run.updated_at
                        st.success("✓ Правки сохранены")
                else:
                    st.info(f"📌 Показано {len(main_result_df)} строк")
                    _render_static_result_table(main_result_df)

                st.divider()

                output_format = st.radio("Формат для скачивания", ["Excel", "CSV"])
                main_result_df = _build_main_kp_result_df(df)

                download_col1, download_col2 = st.columns(2)

                with download_col1:
                    if output_format == "Excel":
                        try:
                            excel_buffer = io.BytesIO()
                            main_result_df.to_excel(excel_buffer, index=False, engine='openpyxl')
                            excel_buffer.seek(0)
                            st.download_button(
                                "📥 Скачать Excel",
                                excel_buffer.getvalue(),
                                _result_download_filename(run, ".xlsx"),
                                "application/vnd.ms-excel",
                                key=f"download_result_excel_{run.run_id}",
                                on_click="ignore",
                            )
                            logger.info("✓ Excel успешно сгенерирован для скачивания")
                        except Exception as e:
                            st.error(f"❌ Ошибка при сохранении Excel: {str(e)}")
                            logger.error(f"Ошибка Excel: {e}", exc_info=True)

                with download_col2:
                    csv_data = main_result_df.to_csv(index=False, sep=';', encoding='utf-8').encode("utf-8")
                    st.download_button(
                        "📥 Скачать CSV",
                        csv_data,
                        _result_download_filename(run, ".csv"),
                        "text/csv",
                        key=f"download_result_csv_{run.run_id}",
                        on_click="ignore",
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
                        st.success(f"✓ Выбран прогон `{selected_run.run_id}`. Откройте его на вкладке «Заполнение КП».")
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
