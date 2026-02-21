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
from config import get_catalog_csv_path

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
if 'matcher_parallel_requests' not in st.session_state:
    st.session_state.matcher_parallel_requests = 1
if 'matcher_catalog_sample_items' not in st.session_state:
    st.session_state.matcher_catalog_sample_items = 500
if 'matcher_settings_signature' not in st.session_state:
    st.session_state.matcher_settings_signature = None
if 'show_results' not in st.session_state:
    st.session_state.show_results = False
if 'show_corrections' not in st.session_state:
    st.session_state.show_corrections = False






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

def _validate_runtime_readiness(db_csv: str) -> list[str]:
    """Проверить готовность приложения к обработке перед запуском matcher."""
    issues = []

    api_key = _get_gemini_api_key()
    if not api_key:
        issues.append("Не задан GEMINI_API_KEY")

    if not Path(db_csv).exists():
        issues.append(f"Не найден каталог price_clean.csv: {db_csv}")

    return issues

def get_matcher() -> ReMoMatcher:
    """Получить или инициализировать экземпляр matcher"""
    db_csv = str(get_catalog_csv_path(st.session_state.get('db_csv_path')))
    settings_signature = (
        int(st.session_state.get('matcher_parallel_requests', 1)),
        int(st.session_state.get('matcher_catalog_sample_items', 500)),
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
            st.stop()
        
        with st.spinner("⏳ Инициализация ReMo Matcher..."):
            try:
                st.session_state.matcher = ReMoMatcher(
                    api_key,
                    db_csv,
                    parallel_requests=int(st.session_state.get('matcher_parallel_requests', 1)),
                    catalog_sample_items=int(st.session_state.get('matcher_catalog_sample_items', 500)),
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
    
    # Боковая панель
    with st.sidebar:
        st.header("⚙️ Настройки")
        
        st.subheader("1️⃣ Товарная база данных")
        st.text_input(
            "Путь к price_clean.csv (или к папке с *_clean.csv)",
            key="db_csv_path",
            help="Если указана папка, matcher автоматически соберет единый price_clean_merged.csv из всех *_clean.csv.",
        )
        
        if st.button("🔄 Перезагрузить БД"):
            st.session_state.matcher = None
            st.session_state.matcher_db_csv = None
            st.session_state.matcher_settings_signature = None
            st.success("✓ БД перезагружена")

        st.subheader("2️⃣ Тонкая настройка matcher")
        st.slider(
            "Параллельные запросы к Gemini",
            min_value=1,
            max_value=10,
            key="matcher_parallel_requests",
            help="Чем больше значение, тем быстрее обработка, но выше риск rate-limit/нестабильности.",
        )
        st.slider(
            "Размер сэмпла каталога для контекста",
            min_value=100,
            max_value=1500,
            step=50,
            key="matcher_catalog_sample_items",
            help="Больше контекста может повысить качество, но замедляет и увеличивает токены.",
        )

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

            db_csv = str(get_catalog_csv_path(st.session_state.get('db_csv_path')))
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
            page = st.slider("Страница", 1, max(1, total_pages), 1)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            
            st.dataframe(_prepare_df_for_display(df_view.iloc[start_idx:end_idx]), width="stretch")
            
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
                st.dataframe(_prepare_df_for_display(df_history), width="stretch")
            else:
                st.info("📭 История пуста")
            
            conn.close()
        except Exception as e:
            st.warning(f"⚠️ Не удалось загрузить историю: {e}")


if __name__ == "__main__":
    main()
