"""
ReMo Matcher UI
Streamlit интерфейс для семантического сопоставления номенклатуры
"""

import streamlit as st
import pandas as pd
import os
from matcher import ReMoMatcher, MISSING_POSITION_TEXT
from pathlib import Path
import tempfile
from datetime import datetime
import sqlite3
import logging
import io
from contextlib import redirect_stdout
from config import get_catalog_csv_path, get_upload_dir
from merge_catalogs import merge_catalogs
from main import convert_csv
from etl_pipeline import PriceETL

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
    st.session_state.db_csv_path = str(get_catalog_csv_path())
if 'matcher_db_csv' not in st.session_state:
    st.session_state.matcher_db_csv = None
if 'processing' not in st.session_state:
    st.session_state.processing = False

SUPPLIER_CATALOGS_DIRNAME = "supplier_catalogs"
MASTER_CATALOG_FILENAME = "price_clean.csv"
CATALOG_MERGE_KEY = "Код ЭТМ"


def get_supplier_catalogs_dir() -> Path:
    storage_dir = get_upload_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)

    supplier_dir = storage_dir / SUPPLIER_CATALOGS_DIRNAME
    supplier_dir.mkdir(parents=True, exist_ok=True)
    return supplier_dir


def get_master_catalog_path() -> Path:
    storage_dir = get_upload_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / MASTER_CATALOG_FILENAME


def get_matcher() -> ReMoMatcher:
    """Получить или инициализировать экземпляр matcher"""
    db_csv = str(get_catalog_csv_path(st.session_state.get('db_csv_path')))
    needs_reinit = (
        st.session_state.matcher is None
        or st.session_state.matcher_db_csv != db_csv
    )

    if needs_reinit:
        logger.info("🔄 Инициализация ReMoMatcher...")
        api_key = None
        try:
            api_key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            # Например, в Railway может не быть .streamlit/secrets.toml.
            # В таком случае используем переменные окружения.
            api_key = None

        api_key = api_key or os.getenv("GEMINI_API_KEY")
        
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
                st.session_state.matcher = ReMoMatcher(api_key, db_csv)
                st.session_state.matcher_db_csv = db_csv
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


def save_uploaded_catalog(uploaded_catalog) -> Path:
    """Save uploaded supplier catalog (raw) to the persistent supplier directory."""
    supplier_dir = get_supplier_catalogs_dir()
    original_name = Path(uploaded_catalog.name).name
    stem = Path(original_name).stem or "catalog"
    suffix = Path(original_name).suffix or ".csv"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target_path = supplier_dir / f"{stem}_{timestamp}_raw{suffix}"
    with open(target_path, 'wb') as fh:
        fh.write(uploaded_catalog.getbuffer())

    logger.info(f"📚 Каталог сохранен: {target_path}")
    return target_path


def prepare_uploaded_catalog(raw_catalog_path: Path) -> Path:
    """Convert and ETL-clean one raw supplier CSV, returning clean catalog path."""
    base_name = raw_catalog_path.name
    if base_name.lower().endswith(".csv"):
        base_name = base_name[:-4]
    if base_name.lower().endswith("_raw"):
        base_name = base_name[:-4]

    converted_path = raw_catalog_path.with_name(f"{base_name}_converted.csv")
    clean_path = raw_catalog_path.with_name(f"{base_name}_clean.csv")

    # convert_csv prints previews; keep Streamlit logs clean.
    with redirect_stdout(io.StringIO()):
        convert_csv(raw_catalog_path, converted_path)

    etl = PriceETL(str(converted_path), str(clean_path))
    etl.run()
    logger.info(f"🧼 Каталог подготовлен: {clean_path}")
    return clean_path


def update_master_catalog(new_catalog_paths: list[Path]) -> tuple[Path, int, int]:
    """Append new supplier catalogs into one master catalog in storage volume."""
    master_path = get_master_catalog_path()

    merge_inputs: list[Path] = []
    if master_path.exists():
        merge_inputs.append(master_path)
    merge_inputs.extend(new_catalog_paths)

    merged_df = merge_catalogs(
        merge_inputs,
        key_col=CATALOG_MERGE_KEY,
        encoding="utf-8",
    )

    temp_path = master_path.with_suffix(".tmp.csv")
    merged_df.to_csv(temp_path, sep=';', encoding='utf-8', index=False)
    temp_path.replace(master_path)

    logger.info(
        f"🧩 Обновлен общий каталог: {master_path} "
        f"({len(merged_df)} строк, {len(merged_df.columns)} колонок)"
    )
    return master_path, len(merged_df), len(merged_df.columns)


def list_available_catalogs() -> list[Path]:
    """Вернуть список доступных CSV-каталогов в рабочей папке данных."""
    storage_dir = get_upload_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)
    catalogs = sorted(storage_dir.glob("*.csv"))
    master_path = get_master_catalog_path()
    if master_path in catalogs:
        catalogs.remove(master_path)
        catalogs.insert(0, master_path)
    return catalogs


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
        use_container_width=True,
        disabled=['Наименование оборудования, материалов и кабелей'],  # Закрыть от редактирования
        num_rows="fixed"
    )
    
    return edited_df


# ============ MAIN UI ============

def main():
    st.title("🔍 ReMo Matcher")
    st.markdown("*Семантическое сопоставление номенклатуры с товарной БД*")
    
    # Боковая панель
    with st.sidebar:
        st.header("⚙️ Настройки")
        
        st.subheader("1️⃣ Товарная база данных")

        catalog_upload = st.file_uploader(
            "Загрузить CSV каталог(и) поставщика",
            type=['csv'],
            accept_multiple_files=True,
            help=(
                "Можно загружать сырые CSV: файл автоматически пройдет convert+ETL, "
                "после чего объединится в общий /data/price_clean.csv по ключу 'Код ЭТМ'."
            )
        )

        if catalog_upload and st.button("💾 Загрузить, очистить и объединить", key="save_catalogs_btn"):
            cleaned_catalogs: list[Path] = []
            for uploaded_catalog in catalog_upload:
                try:
                    raw_path = save_uploaded_catalog(uploaded_catalog)
                    clean_path = prepare_uploaded_catalog(raw_path)
                    cleaned_catalogs.append(clean_path)
                    st.success(f"✓ Подготовлен каталог: {uploaded_catalog.name} -> {clean_path.name}")
                except Exception as e:
                    logger.error(f"❌ Ошибка подготовки каталога: {e}", exc_info=True)
                    st.error(f"❌ Не удалось подготовить {uploaded_catalog.name}: {e}")

            if cleaned_catalogs:
                try:
                    with st.spinner("🧩 Обновление общего каталога..."):
                        master_path, rows, cols = update_master_catalog(cleaned_catalogs)

                    st.session_state.db_csv_path = str(master_path)
                    st.session_state.matcher = None
                    st.session_state.matcher_db_csv = None
                    st.success(f"✅ Общий каталог обновлен: {master_path.name} ({rows} строк, {cols} колонок)")
                except Exception as e:
                    logger.error(f"❌ Ошибка объединения каталогов: {e}", exc_info=True)
                    st.error(f"❌ Не удалось обновить общий каталог: {e}")

        available_catalogs = list_available_catalogs()
        if available_catalogs:
            current_catalog = st.session_state.get('db_csv_path')
            options = [str(path) for path in available_catalogs]
            selected_index = options.index(current_catalog) if current_catalog in options else 0
            selected_catalog = st.selectbox(
                "Выбрать активный каталог",
                options=options,
                index=selected_index,
            )
            if selected_catalog != st.session_state.get('db_csv_path'):
                st.session_state.db_csv_path = selected_catalog

        st.text_input(
            "Путь к price_clean.csv",
            key="db_csv_path"
        )
        
        if st.button("🔄 Перезагрузить БД"):
            st.session_state.matcher = None
            st.session_state.matcher_db_csv = None
            st.success("✓ БД перезагружена")
        
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
            cache_file = "matcher_cache.db"
            if Path(cache_file).exists():
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
            
            col1, col2 = st.columns([1, 1])
            with col1:
                process_button = st.button(
                    "🚀 Начать обработку",
                    key="process_btn",
                    disabled=st.session_state.processing,
                )
            
            with col2:
                st.markdown("")  # Выравнивание
            
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
                    
                    with col2:
                        if st.button("✏️ Коррекция"):
                            logger.info("✏️ Пользователь открыл коррекцию")
                            st.session_state.show_corrections = True
                    
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
            page = st.slider("Страница", 1, max(1, total_pages), 1)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            
            st.dataframe(df_view.iloc[start_idx:end_idx], use_container_width=True)
            
            st.markdown(f"Страница {page} из {max(1, total_pages)}")
            
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
            conn = sqlite3.connect("matcher_cache.db")
            
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
                st.dataframe(df_history, use_container_width=True)
            else:
                st.info("📭 История пуста")
            
            conn.close()
        except Exception as e:
            st.warning(f"⚠️ Не удалось загрузить историю: {e}")


if __name__ == "__main__":
    main()
