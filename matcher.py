"""
ReMo Matcher v1.0
Семантическое сопоставление номенклатуры с использованием Gemini API
"""

import pandas as pd
import json
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import logging
import hashlib
import os
import re
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import get_catalog_csv_path, get_matcher_parallel_requests, get_matcher_cache_db_path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

MISSING_POSITION_TEXT = "Позиция отсутствует"
GROUP_TOKEN_STOPWORDS = {"и", "в", "на", "для", "с", "по", "из", "шт", "мм", "м", "к", "u", "duplex"}

try:
    from google import genai as genai_sdk
    GENAI_SDK_AVAILABLE = True
except ImportError:
    genai_sdk = None
    GENAI_SDK_AVAILABLE = False


class ReMoMatcher:
    """
    Основной класс для семантического сопоставления номенклатуры
    
    Workflow:
    1. Загрузить товарную БД (price_clean.csv)
    2. Для каждого товара из КП найти соответствие в БД
    3. Вернуть: (найденное имя, цена, артикул)
    """
    
    def __init__(self, gemini_api_key: str, db_csv_path: str, cache_db: str = "matcher_cache.db", parallel_requests: int | None = None, catalog_sample_items: int = 500):
        """
        Args:
            gemini_api_key: API ключ Google Gemini
            db_csv_path: Путь к price_clean.csv с товарной базой
            cache_db: БД для кэширования результатов сопоставления
        """
        self.api_key = gemini_api_key
        self.db_csv_path = db_csv_path
        self.cache_db = str(get_matcher_cache_db_path(cache_db))
        self.catalog = None
        self.catalog_dict = None
        self.catalog_items = []
        self.group_index = {}
        self.catalog_text = None
        self.backend = None
        self.client = None
        self.legacy_genai = None
        self.model = None
        self.model_name = None
        self.parallel_requests = min(10, max(1, int(parallel_requests or get_matcher_parallel_requests())))
        self.catalog_sample_items = max(50, int(catalog_sample_items))
        
        # Инициализация Gemini
        if GENAI_SDK_AVAILABLE:
            try:
                self.client = genai_sdk.Client(api_key=self.api_key)
                self.backend = "google-genai"
                logger.info("✓ Gemini backend: google-genai")
            except Exception as e:
                logger.warning(f"Не удалось инициализировать google-genai: {e}")

        if self.backend is None:
            try:
                import google.generativeai as legacy_genai
            except ImportError as e:
                raise ImportError(
                    "Установите Gemini SDK: pip install google-genai "
                    "(fallback: google-generativeai)"
                ) from e

            legacy_genai.configure(api_key=self.api_key)
            self.legacy_genai = legacy_genai
            self.backend = "google-generativeai"
            logger.info("✓ Gemini backend: google-generativeai (fallback)")
        
        # Инициализация кэша
        self._init_cache_db()
        self._load_catalog()
        
        logger.info("✓ ReMoMatcher инициализирован")
    
    def _init_cache_db(self):
        """Инициализировать БД кэша"""
        conn = sqlite3.connect(self.cache_db)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS match_cache (
                query_hash TEXT PRIMARY KEY,
                original_query TEXT,
                found_name TEXT,
                price REAL,
                article TEXT,
                similarity_score FLOAT,
                created_at TIMESTAMP,
                gemini_raw_response TEXT
            )
        ''')
        
        cursor.execute('''
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
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✓ Cache DB инициализирована")
    
    def _load_catalog(self):
        """Загрузить товарный каталог"""
        logger.info(f"📦 Загрузка каталога из {self.db_csv_path}")
        
        self.catalog = pd.read_csv(self.db_csv_path, sep=';', encoding='utf-8')
        logger.info(f"✓ Загружено товаров: {len(self.catalog)}")
        
        # Подготовить словарь для быстрого поиска
        self.catalog_dict = {}
        self.catalog_items = []
        token_to_items: Dict[str, List[Dict]] = defaultdict(list)
        for idx, row in self.catalog.iterrows():
            name = str(row.get('Наименование', '')).strip()
            article = str(row.get('Артикул', '')).strip()
            price = float(row.get('Цена розничная', 0)) if 'Цена розничная' in row else None

            if name:
                item = {
                    'name': name,
                    'name_lc': name.lower(),
                    'article': article,
                    'price': price,
                    'row_idx': idx,
                }
                self.catalog_dict[name.lower()] = item
                self.catalog_items.append(item)
                for token in self._tokenize(name):
                    token_to_items[token].append(item)

        self.group_index = {
            token: items
            for token, items in token_to_items.items()
            if len(items) >= 3
        }

        # Подготовить текстовый формат каталога для Gemini
        self._prepare_catalog_text(max_items=self.catalog_sample_items)
    
    def _prepare_catalog_text(self, max_items: int = 500):
        """Подготовить каталог в текстовом формате для контекста Gemini."""
        limit = min(max_items, len(self.catalog))
        sample = self.catalog.head(limit)

        catalog_lines = []
        for idx, row in sample.iterrows():
            line = f"• {row.get('Наименование', 'N/A')} | Артикул: {row.get('Артикул', 'N/A')} | Цена: {row.get('Цена розничная', 'N/A')}"
            catalog_lines.append(line)

        self.catalog_text = "\n".join(catalog_lines[:300])  # Ограничить для контекста
        logger.info(f"✓ Каталог подготовлен ({len(catalog_lines)} товаров в контексте)")

    def _tokenize(self, text: str) -> List[str]:
        tokens = re.findall(r"[a-zA-Zа-яА-Я0-9]+", str(text).lower())
        return [token for token in tokens if len(token) >= 2 and token not in GROUP_TOKEN_STOPWORDS]

    def _build_context_for_query(self, query: str, max_lines: int = 300) -> str:
        """Собрать контекст по релевантным группам, а не случайным позициям."""
        query_tokens = self._tokenize(query)
        if not query_tokens or not self.group_index:
            return self.catalog_text

        candidate_map: Dict[str, Dict] = {}
        query_token_set = set(query_tokens)
        for token in query_token_set:
            for item in self.group_index.get(token, []):
                candidate_map[item['name_lc']] = item

        if not candidate_map:
            return self.catalog_text

        def score(item: Dict) -> Tuple[int, int]:
            item_tokens = set(self._tokenize(item['name']))
            overlap = len(item_tokens.intersection(query_token_set))
            return (overlap, -item['row_idx'])

        ranked_items = sorted(candidate_map.values(), key=score, reverse=True)
        lines = [
            f"• {item['name']} | Артикул: {item.get('article', 'N/A')} | Цена: {item.get('price', 'N/A')}"
            for item in ranked_items[:max_lines]
        ]
        return "\n".join(lines) if lines else self.catalog_text

    def _hash_query(self, query: str) -> str:
        """Хэш запроса для кэша"""
        return hashlib.md5(query.lower().encode()).hexdigest()
    
    def _get_from_cache(self, query: str) -> Optional[Dict]:
        """Получить результат из кэша"""
        query_hash = self._hash_query(query)
        
        try:
            conn = sqlite3.connect(self.cache_db)
            cursor = conn.cursor()
            
            cursor.execute(
                'SELECT found_name, price, article, similarity_score FROM match_cache WHERE query_hash = ?',
                (query_hash,)
            )
            result = cursor.fetchone()
            conn.close()
            
            if result:
                logger.debug(f"💾 Результат найден в кэше: {query}")
                found_name = result[0] or MISSING_POSITION_TEXT
                return {
                    'found_name': found_name,
                    'price': result[1],
                    'article': result[2],
                    'similarity_score': result[3] or 0,
                    'from_cache': True,
                    'success': True,
                    'error': None
                }
        except Exception as e:
            logger.warning(f"⚠️ Ошибка чтения кэша: {e}")
        
        return None
    
    def _save_to_cache(self, query: str, found_name: str, price: Optional[float], 
                       article: str, similarity_score: float, raw_response: str):
        """Сохранить результат в кэш"""
        query_hash = self._hash_query(query)
        
        try:
            conn = sqlite3.connect(self.cache_db)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO match_cache 
                (query_hash, original_query, found_name, price, article, similarity_score, created_at, gemini_raw_response)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (query_hash, query, found_name, price, article, similarity_score, datetime.now(), raw_response))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"⚠️ Ошибка сохранения в кэш: {e}")
    
    def match(self, query: str, use_cache: bool = True) -> Dict:
        """
        Сопоставить номенклатуру из КП с товарной БД
        
        Args:
            query: Наименование из столбца B КП
            use_cache: Использовать кэш?
        
        Returns:
            {
                'found_name': 'Найденное имя из БД',
                'price': 1234.56,
                'article': 'ART-001',
                'similarity_score': 0.95,
                'from_cache': False,
                'success': True,
                'error': None
            }
        """
        
        # Проверить кэш
        if use_cache:
            cached = self._get_from_cache(query)
            if cached:
                return cached
        
        try:
            # Точное совпадение в словаре
            exact_match = self.catalog_dict.get(query.lower())
            if exact_match:
                logger.info(f"✓ Точное совпадение найдено: {query}")
                self._save_to_cache(query, exact_match['name'], exact_match['price'], 
                                   exact_match['article'], 1.0, "exact_match")
                return {
                    'found_name': exact_match['name'],
                    'price': exact_match['price'],
                    'article': exact_match['article'],
                    'similarity_score': 1.0,
                    'from_cache': False,
                    'success': True,
                    'error': None
                }
            
            # Использовать Gemini для семантического поиска
            logger.info(f"🔍 Поиск в Gemini: {query}")
            result = self._match_with_gemini(query)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Ошибка сопоставления: {e}", exc_info=True)
            return {
                'found_name': None,
                'price': None,
                'article': None,
                'similarity_score': 0,
                'from_cache': False,
                'success': False,
                'error': str(e)
            }

    def _candidate_models(self) -> List[str]:
        preferred = [
            self.model_name,
            'gemini-2.5-flash',
            'gemini-2.5-flash-lite',
            'gemini-2.0-flash',
            'gemini-2.0-flash-lite',
            'gemini-1.5-flash',
            'gemini-1.5-flash-8b',
            'gemini-1.5-pro',
            'gemini-pro',
        ]
        result = []
        seen = set()
        for name in preferred:
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(name)
        return result

    def _generate_gemini_text(self, prompt: str, model_name: str) -> str:
        if self.backend == "google-genai":
            response = self.client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            return (getattr(response, 'text', None) or '').strip()

        if self.backend == "google-generativeai":
            # Локальный инстанс безопаснее для многопоточной обработки.
            model = self.legacy_genai.GenerativeModel(model_name)
            response = model.generate_content(prompt, stream=False)
            return (response.text or '').strip()

        raise RuntimeError("Gemini backend не инициализирован")
    
    def _match_with_gemini(self, query: str) -> Dict:
        """Использовать Gemini для сопоставления"""

        context_text = self._build_context_for_query(query)
        prompt = f"""Ты эксперт по технической номенклатуре оборудования, кабеля и материалов.

Задача: Найти в каталоге товар, который ТОЧНО соответствует запросу пользователя.

КАТАЛОГ ДОСТУПНЫХ ТОВАРОВ:
{context_text}

ЗАПРОС ПОЛЬЗОВАТЕЛЯ: "{query}"

ИНСТРУКЦИИ:
1. Внимательно проанализируй запрос пользователя
2. Найди в каталоге товар с МАКСИМАЛЬНЫМ семантическим совпадением
3. Учитывай:
   - Технические характеристики (сечение, вольтаж, материал, размеры)
   - Назначение товара (кабель, кондиционер, сварочный аппарат и т.д.)
   - Альтернативные названия и аббревиатуры
4. Если релевантного аналога нет, верни found_name=null
5. Вывод ТОЛЬКО в формате JSON (без лишнего текста)

ФОРМАТ ОТВЕТА:
{{
    "found_name": "Точное название из каталога",
    "article": "Артикул товара",
    "confidence": 0.95,
    "reasoning": "Краткое объяснение почему это совпадение"
}}

Если товар не найден:
{{
    "found_name": null,
    "article": null,
    "confidence": 0,
    "reasoning": "товар не найден в каталоге"
}}
"""

        def parse_result(raw_text: str) -> Dict:
            start_idx = raw_text.find('{')
            end_idx = raw_text.rfind('}') + 1
            if start_idx == -1 or end_idx <= start_idx:
                raise ValueError("JSON не найден в ответе")

            gemini_result = json.loads(raw_text[start_idx:end_idx])
            found_name = gemini_result.get('found_name')
            article = gemini_result.get('article')
            confidence = float(gemini_result.get('confidence', 0) or 0)

            price = None
            if found_name:
                match = self.catalog_dict.get(str(found_name).lower())
                if match:
                    price = match['price']
                    article = article or match['article']
            else:
                found_name = MISSING_POSITION_TEXT

            result = {
                'found_name': found_name,
                'price': price,
                'article': article,
                'similarity_score': confidence,
                'from_cache': False,
                'success': True,
                'error': None
            }
            self._save_to_cache(query, found_name, price, article or '', confidence, raw_text)
            return result

        try:
            candidate_names = self._candidate_models()
            last_error = None
            for model_name in candidate_names:
                try:
                    raw_text = self._generate_gemini_text(prompt, model_name)
                    parsed = parse_result(raw_text)
                    self.model_name = model_name
                    if parsed['found_name'] == MISSING_POSITION_TEXT:
                        logger.warning(f"⚠️ Товар не найден для: {query}")
                    else:
                        logger.info(f"✓ Найдено: {parsed['found_name']} (confidence: {parsed['similarity_score']})")
                    return parsed
                except Exception as model_error:
                    last_error = model_error
                    logger.warning(f"Модель {model_name} не сработала: {model_error}")

            raise RuntimeError(f"Gemini fallback exhausted: {last_error}")

        except Exception as e:
            logger.error(f"❌ Ошибка Gemini API: {e}", exc_info=True)
            return {
                'found_name': MISSING_POSITION_TEXT,
                'price': None,
                'article': None,
                'similarity_score': 0,
                'from_cache': False,
                'success': False,
                'error': str(e)
            }
    
    def save_to_history(self, query: str, found_name: str, price: Optional[float], 
                        article: str, user_approved: bool, correction_note: str = ""):
        """Сохранить результат в историю"""
        try:
            conn = sqlite3.connect(self.cache_db)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO match_history 
                (original_query, found_name, price, article, user_approved, correction_note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (query, found_name, price, article, user_approved, correction_note, datetime.now()))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"⚠️ Ошибка сохранения в историю: {e}")
    

    def _run_matches_parallel(self, tasks: List[Tuple[int, str]]) -> List[Tuple[int, Dict]]:
        """Выполнить сопоставление запросов с ограниченным параллелизмом."""
        if not tasks:
            return []

        workers = getattr(self, "parallel_requests", 1)
        if workers <= 1:
            return [(idx, self.match(query, use_cache=True)) for idx, query in tasks]

        logger.info(f"⚡ Параллельная обработка включена: {workers} запросов одновременно")
        results: List[Tuple[int, Dict]] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(self.match, query, True): idx
                for idx, query in tasks
            }
            completed = 0
            total = len(tasks)
            for future in as_completed(future_map):
                idx = future_map[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = {
                        'found_name': MISSING_POSITION_TEXT,
                        'price': None,
                        'article': None,
                        'similarity_score': 0,
                        'from_cache': False,
                        'success': False,
                        'error': str(e),
                    }
                results.append((idx, result))
                completed += 1
                if completed % 10 == 0 or completed == total:
                    logger.info(f"⏳ Обработано {completed}/{total} строк")

        return results

    def process_excel(self, excel_path: str, output_path: str = None) -> Tuple[pd.DataFrame, Dict]:
        """
        Обработать весь Excel файл КП
        
        Args:
            excel_path: Путь к исходному Excel файлу
            output_path: Путь для сохранения результата (если не указан, использует исходный путь с _matched суффиксом)
        
        Returns:
            (обработанный DataFrame, статистика)
        """
        logger.info(f"📊 Начало обработки: {excel_path}")
        
        # Загрузить Excel
        try:
            df = pd.read_excel(excel_path)
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки Excel: {e}")
            raise
        
        # Найти столбец B (по названию или номеру)
        col_b = None
        for col in df.columns:
            if 'наименование' in str(col).lower() and 'оборудование' in str(col).lower():
                col_b = col
                break
        
        if col_b is None and len(df.columns) > 1:
            col_b = df.columns[1]  # Столбец B (индекс 1)
        
        if col_b is None:
            raise ValueError("Не найден столбец 'Наименование оборудования, материалов и кабелей'")
        
        logger.info(f"✓ Найден столбец: {col_b}")
        
        # Подготовить столбцы для результатов без дублирования имен.
        # Это убирает ошибку вида: "cannot insert Артикул, already exists".
        if 'Цена' not in df.columns:
            df['Цена'] = pd.Series([None] * len(df), dtype='float64')
        else:
            df['Цена'] = pd.to_numeric(df['Цена'], errors='coerce').astype('float64')

        for text_col in ('Найденная номенклатура', 'Артикул', 'Ошибка сопоставления'):
            if text_col not in df.columns:
                df[text_col] = None
            else:
                df[text_col] = df[text_col].astype(object)
        
        # Обработать каждую строку
        stats = {
            'total': 0,
            'found': 0,
            'not_found': 0,
            'from_cache': 0,
            'errors': 0
        }

        tasks: List[Tuple[int, str]] = []
        for idx, row in df.iterrows():
            query = str(row[col_b]).strip()
            if not query or query.lower() == 'nan':
                continue
            if query.strip().lower() in {
                'наименование',
                'наименование оборудования, материалов и кабелей',
                'nomenclature',
            }:
                continue
            tasks.append((idx, query))

        stats['total'] = len(tasks)
        for idx, result in self._run_matches_parallel(tasks):
            # Заполнить результаты
            found_name = result.get('found_name') or MISSING_POSITION_TEXT
            df.at[idx, 'Цена'] = result.get('price')
            df.at[idx, 'Найденная номенклатура'] = found_name
            df.at[idx, 'Артикул'] = result.get('article')
            df.at[idx, 'Ошибка сопоставления'] = result.get('error')

            if result.get('from_cache'):
                stats['from_cache'] += 1

            if found_name == MISSING_POSITION_TEXT:
                stats['not_found'] += 1
            else:
                stats['found'] += 1

            if not result.get('success', True):
                stats['errors'] += 1
                logger.warning(f"⚠️ [{idx+1}] Ошибка: {result.get('error')}")
        
        # Сохранить результат
        if output_path is None:
            src = Path(excel_path)
            output_path = str(src.with_name(f"{src.stem}_matched{src.suffix}"))
        
        try:
            df.to_excel(output_path, index=False)
            logger.info(f"✓ Результат сохранен: {output_path}")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения Excel: {e}")
            raise
        
        # Вывести статистику
        logger.info("\n" + "="*60)
        logger.info("📊 СТАТИСТИКА ОБРАБОТКИ")
        logger.info("="*60)
        logger.info(f"Всего строк:        {stats['total']}")
        logger.info(f"Найдено товаров:    {stats['found']}")
        logger.info(f"Не найдено:         {stats['not_found']}")
        logger.info(f"Из кэша:            {stats['from_cache']}")
        logger.info(f"Ошибок:             {stats['errors']}")
        logger.info(f"Успешность:         {stats['found']/stats['total']*100:.1f}%" if stats['total'] > 0 else "N/A")
        logger.info("="*60 + "\n")
        
        return df, stats


if __name__ == "__main__":
    # Пример использования
    API_KEY = os.getenv('GEMINI_API_KEY')
    if not API_KEY:
        print("⚠️ Установите переменную окружения GEMINI_API_KEY")
        print("На Windows: set GEMINI_API_KEY=ваш_ключ")
        print("На Linux/Mac: export GEMINI_API_KEY=ваш_ключ")
        exit(1)
    
    matcher = ReMoMatcher(
        gemini_api_key=API_KEY,
        db_csv_path=str(get_catalog_csv_path())
    )
    
    # Тестовое сопоставление
    test_queries = [
        "Кабель медный 4кв.мм",
        "Провод Cu 4x2.5",
        "Сварочный аппарат инвертор",
    ]
    
    print("\n" + "="*60)
    print("🧪 ТЕСТОВОЕ СОПОСТАВЛЕНИЕ")
    print("="*60 + "\n")
    
    for query in test_queries:
        result = matcher.match(query)
        print(f"Запрос:     {query}")
        print(f"Найдено:    {result['found_name']}")
        print(f"Артикул:    {result['article']}")
        print(f"Цена:       {result['price']}")
        print(f"Уверенность: {result['similarity_score']}")
        print("-" * 60)
