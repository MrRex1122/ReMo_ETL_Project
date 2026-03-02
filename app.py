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
import tempfile
from datetime import datetime
import sqlite3
import logging
import io
import json
from config import get_catalog_csv_path, get_upload_dir, get_matcher_cache_db_path
from catalog_snapshot import prepare_catalog_snapshot
from google_drive_sync import sync_drive_folder_csvs
from etl_pipeline import PriceETL
from main import convert_csv
from snapshot_export import build_public_export_url, get_snapshot_xlsx_status, start_snapshot_xlsx_build

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
    st.session_state.db_csv_path = str(get_upload_dir() / 'clean')
if 'matcher_db_csv' not in st.session_state:
    st.session_state.matcher_db_csv = None
if 'matcher_parallel_requests' not in st.session_state:
    st.session_state.matcher_parallel_requests = 1
if 'matcher_catalog_sample_items' not in st.session_state:
    st.session_state.matcher_catalog_sample_items = 1500
if 'matcher_mode' not in st.session_state:
    st.session_state.matcher_mode = 'exact'
if 'matcher_settings_signature' not in st.session_state:
    st.session_state.matcher_settings_signature = None
if 'show_results' not in st.session_state:
    st.session_state.show_results = False
if 'show_corrections' not in st.session_state:
    st.session_state.show_corrections = False

if 'catalog_snapshot_bundle' not in st.session_state:
    st.session_state.catalog_snapshot_bundle = None
if 'catalog_snapshot_xlsx_status' not in st.session_state:
    st.session_state.catalog_snapshot_xlsx_status = "idle"
if 'catalog_snapshot_xlsx_path' not in st.session_state:
    st.session_state.catalog_snapshot_xlsx_path = None
if 'catalog_snapshot_xlsx_url' not in st.session_state:
    st.session_state.catalog_snapshot_xlsx_url = None




def _catalog_source_path() -> Path:
    """Вернуть актуальный источник каталога для matcher и выгрузки."""
    clean_dir = get_upload_dir() / "clean"
    if clean_dir.exists():
        return clean_dir
    return get_catalog_csv_path(st.session_state.get('db_csv_path'))



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

def _validate_runtime_readiness(db_csv: str) -> list[str]:
    """Проверить готовность приложения к обработке перед запуском matcher."""
    issues = []

    api_key = _get_gemini_api_key()
    if not api_key:
        issues.append("Не задан GEMINI_API_KEY")

    source_path = Path(db_csv)
    if source_path.is_dir():
        clean_files = list(source_path.glob('*_clean.csv'))
        if not clean_files:
            issues.append(f"В папке нет файлов *_clean.csv: {db_csv}")
    elif not source_path.exists():
        issues.append(f"Не найден каталог price_clean.csv: {db_csv}")

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

def get_matcher() -> ReMoMatcher:
    """Получить или инициализировать экземпляр matcher"""
    db_csv = str(_catalog_source_path())
    settings_signature = (
        int(st.session_state.get('matcher_parallel_requests', 1)),
        int(st.session_state.get('matcher_catalog_sample_items', 500)),
        str(st.session_state.get('matcher_mode', 'exact')),
    )
    needs_reinit = (
        st.session_state.matcher is None
        or st.session_state.matcher_db_csv != db_csv
        or st.session_state.matcher_settings_signature != settings_signature
    )

    if needs_reinit:
        logger.info("🔄 Инициализация ReMoMatcher...")
        api_key = _get_gemini_api_key()
        
        if not api_key:
            logger.error("❌ GEMINI_API_KEY не установлен")
            st.error("❌ GEMINI_API_KEY не установлен!")
            st.info("""
            **Как установить:**
            1. Создайте файл `.streamlit/secrets.toml` в папке проекта:
            ```
            GEMINI_API_KEY = "ваш_ключ"
            ```
            2. Или установите переменную окружения:
            ```bash
            export GEMINI_API_KEY="ваш_ключ"
            ```
            """)
            st.stop()
        
        if not Path(db_csv).exists():
            logger.error(f"❌ Файл не найден: {db_csv}")
            st.error(f"❌ Файл не найден: {db_csv}")
            st.info(
                "Для Railway задайте путь к каталогу через переменную окружения "
                "`REMO_DB_CSV` (или `REMO_UPLOAD_DIR`) и убедитесь, что файл "
                "`price_clean.csv` существует в контейнере."
            )
            st.stop()
        
        with st.spinner("⏳ Инициализация ReMo Matcher..."):
            try:
                st.session_state.matcher = ReMoMatcher(
                    api_key,
                    db_csv,
                    parallel_requests=int(st.session_state.get('matcher_parallel_requests', 1)),
                    catalog_sample_items=int(st.session_state.get('matcher_catalog_sample_items', 500)),
                    match_mode=str(st.session_state.get('matcher_mode', 'exact')),
                )
                st.session_state.matcher_db_csv = db_csv
                st.session_state.matcher_settings_signature = settings_signature
                logger.info("✓ ReMoMatcher успешно инициализирован")
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации: {e}", exc_info=True)
                st.error(f"❌ Ошибка инициализации: {str(e)}")
                st.stop()
    
    return st.session_state.matcher


def process_uploaded_file(uploaded_file) -> tuple:
    """Обработать загруженный файл"""
    
    logger.info(f"📄 Обработка файла: {uploaded_file.name}")
    matcher = get_matcher()
    
    # Сохранить временный файл
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name
        logger.info(f"📝 Временный файл сохранен: {tmp_path}")
    
    try:
        with st.spinner("🔍 Обработка файла (это может занять время)..."):
            logger.info("⏳ Начало обработки файла в matcher.process_excel()")
            df_result, stats = matcher.process_excel(tmp_path)
        
        st.session_state.df_processed = df_result
        st.session_state.stats = stats
        logger.info(f"✓ Файл успешно обработан. Результат: {stats}")
        
        return df_result, stats
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке файла: {e}", exc_info=True)
        raise
    finally:
        os.unlink(tmp_path)
        logger.info(f"🗑️ Временный файл удален")


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
    for idx, raw_path in enumerate(downloaded_raw_paths, start=1):
        source_name = Path(raw_path.name).name
        source_stem = Path(source_name).stem
        logger.info("🧩 Постобработка файла %s/%s: %s", idx, total_files, source_name)

        converted_dir = storage_dir / "converted"
        clean_dir = storage_dir / "clean"
        converted_dir.mkdir(parents=True, exist_ok=True)
        clean_dir.mkdir(parents=True, exist_ok=True)

        converted_path = converted_dir / f"{source_stem}_converted.csv"
        clean_path = clean_dir / f"{source_stem}_clean.csv"

        logger.info("🔄 ETL старт: %s", source_name)
        convert_csv(raw_path, converted_path)
        PriceETL(str(converted_path), str(clean_path)).run()
        saved_paths.append(clean_path)
        logger.info("✅ ETL завершен: %s", clean_path)

    logger.info("✅ Синхронизация и постобработка завершены. Файлов: %s", len(saved_paths))
    return saved_paths


def _run_etl_for_raw_file(raw_path: Path, converted_path: Path, clean_path: Path) -> None:
    """Запустить ETL для raw файла с memory-safe режимом для крупных CSV."""
    threshold_mb = int(os.getenv("REMO_CHUNKED_ETL_THRESHOLD_MB", "512"))
    chunksize = int(os.getenv("REMO_CHUNKED_ETL_CHUNKSIZE", "50000"))
    file_mb = raw_path.stat().st_size / (1024 * 1024)

    if file_mb >= threshold_mb:
        logger.info(
            "🧠 Большой CSV (%.2f MB) — запускаем chunked ETL (threshold=%s MB, chunksize=%s)",
            file_mb,
            threshold_mb,
            chunksize,
        )
        PriceETL(str(raw_path), str(clean_path)).run_chunked(chunksize=chunksize)
        return

    convert_csv(raw_path, converted_path)
    PriceETL(str(converted_path), str(clean_path)).run()


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
    total_files = len(raw_files)
    logger.info("🚀 Этап 2: старт ETL для raw CSV. Файлов: %s", total_files)
    for idx, raw_path in enumerate(raw_files, start=1):
        source_name = raw_path.name
        source_stem = raw_path.stem
        converted_path = converted_dir / f"{source_stem}_converted.csv"
        clean_path = clean_dir / f"{source_stem}_clean.csv"

        logger.info("🧩 ETL файл %s/%s: %s", idx, total_files, source_name)
        _run_etl_for_raw_file(raw_path, converted_path, clean_path)
        saved_paths.append(clean_path)
        logger.info("✅ ETL готов: %s (%s/%s)", clean_path.name, idx, total_files)

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
    
    # Редактируемая таблица
    st.write("**Отредактируйте результаты в таблице ниже:**")
    
    edited_df = st.data_editor(
        df_view,
        width="stretch",
        disabled=['Наименование оборудования, материалов и кабелей'],  # Закрыть от редактирования
        num_rows="fixed"
    )
    
    return edited_df


# ============ MAIN UI ============

def main():
    st.title("🔍 ReMo Matcher")
    st.markdown("*Семантическое сопоставление номенклатуры с товарной БД*")
    build_sha = os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("RAILWAY_GIT_COMMIT")
    if build_sha:
        st.caption(f"Build: `{build_sha[:8]}`")
        logger.info("🚢 Build commit: %s", build_sha)
    
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
            for uploaded_catalog in catalog_upload:
                try:
                    saved_path = save_uploaded_catalog(uploaded_catalog, run_etl=run_etl_before_save)
                    st.success(f"✓ Сохранен каталог: {saved_path.name}")
                except Exception as e:
                    logger.error(f"❌ Ошибка сохранения каталога: {e}", exc_info=True)
                    st.error(f"❌ Не удалось сохранить {uploaded_catalog.name}: {e}")

            st.session_state.matcher = None
            st.session_state.matcher_db_csv = None

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

                        st.session_state.matcher = None
                        st.session_state.matcher_db_csv = None
                        st.session_state.matcher_settings_signature = None
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
                    st.session_state.matcher = None
                    st.session_state.matcher_db_csv = None
                    st.session_state.matcher_settings_signature = None
            except Exception as e:
                logger.error(f"❌ Ошибка этапа ETL для raw CSV: {e}", exc_info=True)
                st.error(f"❌ Не удалось выполнить ETL для raw CSV: {e}")

        st.caption("Источник каталога выбирается автоматически")
        st.info(
            "Используется только объединенный каталог без дублей: "
            "из всех *_clean.csv в папке `clean` формируется `price_clean_merged.csv`."
        )
        st.code(str(_catalog_source_path()))
        
        if st.button("🔄 Перезагрузить БД"):
            st.session_state.matcher = None
            st.session_state.matcher_db_csv = None
            st.session_state.matcher_settings_signature = None
            st.session_state.catalog_snapshot_bundle = None
            st.session_state.catalog_snapshot_xlsx_status = "idle"
            st.session_state.catalog_snapshot_xlsx_path = None
            st.session_state.catalog_snapshot_xlsx_url = None
            st.success("✓ БД перезагружена")

        st.caption("Проверка входной БД (после merge и до matcher)")
        if st.button("📥 Подготовить выгрузку входной БД"):
            try:
                snapshot_bundle = prepare_catalog_snapshot(
                    str(_catalog_source_path()),
                    merge_all_sources=True,
                )
                st.session_state.catalog_snapshot_bundle = snapshot_bundle
                st.session_state.catalog_snapshot_xlsx_status = snapshot_bundle.xlsx_status
                st.session_state.catalog_snapshot_xlsx_path = (
                    str(snapshot_bundle.xlsx_path) if snapshot_bundle.xlsx_path is not None else None
                )
                st.session_state.catalog_snapshot_xlsx_url = snapshot_bundle.public_xlsx_url
                st.success(f"✓ БД подготовлена: {snapshot_bundle.resolved_csv_path}")
            except Exception as e:
                logger.error(f"❌ Ошибка подготовки выгрузки БД: {e}", exc_info=True)
                st.error(f"❌ Не удалось подготовить БД: {e}")

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

            stats = bundle.duplicate_stats or {}
            size_mb = bundle.resolved_csv_size_bytes / (1024 * 1024)
            st.write(f"Активный источник: `{bundle.resolved_csv_path}`")
            st.write(f"Размер CSV: **{size_mb:.2f} MB**")
            st.write(f"Строк всего: **{stats.get('rows_total', 0)}**")
            st.write(
                f"Дублей: **{stats.get('duplicates_total', 0)}** "
                f"(артикул: {stats.get('duplicates_by_article', 0)}, "
                f"наименование: {stats.get('duplicates_by_name', 0)})"
            )

            st.link_button(
                "⬇️ Скачать входную БД (CSV)",
                bundle.public_csv_url,
                use_container_width=True,
            )

            if bundle.public_duplicate_csv_url:
                st.link_button(
                    "⬇️ Скачать только дубли (CSV)",
                    bundle.public_duplicate_csv_url,
                    use_container_width=True,
                )

            if st.button("🧮 Подготовить Excel-файл"):
                try:
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
        st.slider(
            "Размер сэмпла каталога для контекста",
            min_value=100,
            max_value=5000,
            step=50,
            key="matcher_catalog_sample_items",
            help="Больше контекста обычно повышает точность сопоставления, но замедляет обработку и увеличивает токены.",
        )

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
                st.session_state.processing = True
                try:
                    df_result, stats = process_uploaded_file(uploaded_file)

                    # Успешно
                    st.markdown('<div class="success-box">✅ Обработка завершена успешно!</div>',
                               unsafe_allow_html=True)
                    logger.info("✅ Обработка успешно завершена")

                    show_statistics(stats)

                    # Опции после обработки
                    col1, col2, col3 = st.columns(3)

                    with col1:
                        if st.button("📋 Просмотреть результаты"):
                            logger.info("📋 Пользователь открыл результаты")
                            st.session_state.show_results = True
                            st.session_state.show_corrections = False
                            st.rerun()

                    with col2:
                        if st.button("✏️ Коррекция"):
                            logger.info("✏️ Пользователь открыл коррекцию")
                            st.session_state.show_results = True
                            st.session_state.show_corrections = True
                            st.rerun()

                    with col3:
                        output_filename = f"{uploaded_file.name.split('.')[0]}_matched_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                        csv_data = df_result.to_csv(index=False, sep=';', encoding='utf-8')
                        st.download_button(
                            "💾 Скачать результат",
                            csv_data,
                            output_filename,
                            "text/csv",
                            key="download_csv"
                        )
                        logger.info(f"💾 Кнопка скачивания готова: {output_filename}")

                except Exception as e:
                    logger.error(f"❌ Ошибка при обработке: {e}", exc_info=True)
                    st.markdown(f'<div class="error-box">❌ Ошибка: {str(e)}</div>',
                               unsafe_allow_html=True)
                    st.error(str(e))
                finally:
                    st.session_state.processing = False
    
    with tab2:
        st.header("📋 Результаты обработки")
        
        if st.session_state.df_processed is not None:
            df = st.session_state.df_processed
            stats = st.session_state.stats

            show_statistics(stats)

            st.divider()

            default_mode = "Коррекция" if st.session_state.get('show_corrections') else "Просмотр"
            mode = st.radio("Режим", ["Просмотр", "Коррекция"], index=1 if default_mode == "Коррекция" else 0, horizontal=True)

            if mode == "Коррекция":
                edited_df = show_corrections_table(df)
                if st.button("💾 Сохранить правки", key="save_corrections"):
                    st.session_state.df_processed = edited_df.copy()
                    st.session_state.show_corrections = False
                    st.success("✓ Правки сохранены")
                    st.rerun()

            # Фильтры
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
            
            # Применить фильтр
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
            
            # Применить сортировку
            if sort_by == "Названию":
                df_view = df_view.sort_values(by=df.columns[1], na_position='last')
            elif sort_by == "Цене":
                df_view = df_view.sort_values(by='Цена', ascending=False, na_position='last')
            
            st.info(f"📌 Отображено {len(df_view)} из {len(df)} записей")
            
            # Таблица с пагинацией
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
            
            # Скачать
            st.divider()
            
            output_format = st.radio("Формат для скачивания", ["Excel", "CSV"])
            
            col1, col2 = st.columns(2)
            
            with col1:
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
            
            with col2:
                csv_data = df.to_csv(index=False, sep=';', encoding='utf-8')
                st.download_button(
                    "📥 Скачать CSV",
                    csv_data,
                    f"result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    "text/csv"
                )
        else:
            st.info("📤 Загрузите файл и обработайте его сначала")
    
    with tab3:
        st.header("📊 История обработок")
        
        try:
            conn = sqlite3.connect(str(get_matcher_cache_db_path()))
            _ensure_history_table_exists(conn)
            
            # История результатов
            df_history = pd.read_sql_query(
                "SELECT * FROM match_history ORDER BY created_at DESC LIMIT 100",
                conn
            )
            
            if not df_history.empty:
                st.subheader(f"Последние {len(df_history)} операций")
                
                # Статистика
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
                
                # Таблица истории
                st.dataframe(_prepare_df_for_display(df_history), width="stretch")
            else:
                st.info("📭 История пуста")
            
            conn.close()
        except Exception as e:
            st.warning(f"⚠️ Не удалось загрузить историю: {e}")


if __name__ == "__main__":
    main()
