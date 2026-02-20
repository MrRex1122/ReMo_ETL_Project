"""
ReMo Matcher v1.0
Ð¡ÐµÐ¼Ð°Ð½Ñ‚Ð¸Ñ‡ÐµÑÐºÐ¾Ðµ ÑÐ¾Ð¿Ð¾ÑÑ‚Ð°Ð²Ð»ÐµÐ½Ð¸Ðµ Ð½Ð¾Ð¼ÐµÐ½ÐºÐ»Ð°Ñ‚ÑƒÑ€Ñ‹ Ñ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ð½Ð¸ÐµÐ¼ Gemini API
"""

import pandas as pd
import json
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import logging
import hashlib
import os
from pathlib import Path
from catalog_schema import (
    CANONICAL_ARTICLE_COLUMN,
    CANONICAL_NAME_COLUMN,
    CANONICAL_PRICE_COLUMN,
    canonicalize_catalog_columns,
)
from config import get_catalog_csv_path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

MISSING_POSITION_TEXT = "Позиция отсутствует"

DEFAULT_MATCH_PROMPT_TEMPLATE = dedent(
    """
    Ты эксперт по технической номенклатуре оборудования, кабеля и материалов.

    Задача: Найти в каталоге товар, который ТОЧНО соответствует запросу пользователя.

    КАТАЛОГ ДОСТУПНЫХ ТОВАРОВ:
    {catalog_context}

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
).strip()

try:
    from google import genai as genai_sdk
    GENAI_SDK_AVAILABLE = True
except ImportError:
    genai_sdk = None
    GENAI_SDK_AVAILABLE = False


class ReMoMatcher:
    """
    ÐžÑÐ½Ð¾Ð²Ð½Ð¾Ð¹ ÐºÐ»Ð°ÑÑ Ð´Ð»Ñ ÑÐµÐ¼Ð°Ð½Ñ‚Ð¸Ñ‡ÐµÑÐºÐ¾Ð³Ð¾ ÑÐ¾Ð¿Ð¾ÑÑ‚Ð°Ð²Ð»ÐµÐ½Ð¸Ñ Ð½Ð¾Ð¼ÐµÐ½ÐºÐ»Ð°Ñ‚ÑƒÑ€Ñ‹
    
    Workflow:
    1. Ð—Ð°Ð³Ñ€ÑƒÐ·Ð¸Ñ‚ÑŒ Ñ‚Ð¾Ð²Ð°Ñ€Ð½ÑƒÑŽ Ð‘Ð” (price_clean.csv)
    2. Ð”Ð»Ñ ÐºÐ°Ð¶Ð´Ð¾Ð³Ð¾ Ñ‚Ð¾Ð²Ð°Ñ€Ð° Ð¸Ð· ÐšÐŸ Ð½Ð°Ð¹Ñ‚Ð¸ ÑÐ¾Ð¾Ñ‚Ð²ÐµÑ‚ÑÑ‚Ð²Ð¸Ðµ Ð² Ð‘Ð”
    3. Ð’ÐµÑ€Ð½ÑƒÑ‚ÑŒ: (Ð½Ð°Ð¹Ð´ÐµÐ½Ð½Ð¾Ðµ Ð¸Ð¼Ñ, Ñ†ÐµÐ½Ð°, Ð°Ñ€Ñ‚Ð¸ÐºÑƒÐ»)
    """
    
    def __init__(self, gemini_api_key: str, db_csv_path: str, cache_db: str | None = None):
        """
        Args:
            gemini_api_key: API ÐºÐ»ÑŽÑ‡ Google Gemini
            db_csv_path: ÐŸÑƒÑ‚ÑŒ Ðº price_clean.csv Ñ Ñ‚Ð¾Ð²Ð°Ñ€Ð½Ð¾Ð¹ Ð±Ð°Ð·Ð¾Ð¹
            cache_db: Ð‘Ð” Ð´Ð»Ñ ÐºÑÑˆÐ¸Ñ€Ð¾Ð²Ð°Ð½Ð¸Ñ Ñ€ÐµÐ·ÑƒÐ»ÑŒÑ‚Ð°Ñ‚Ð¾Ð² ÑÐ¾Ð¿Ð¾ÑÑ‚Ð°Ð²Ð»ÐµÐ½Ð¸Ñ
        """
        self.api_key = gemini_api_key
        self.db_csv_path = db_csv_path
        self.cache_db = str(get_matcher_cache_db_path(cache_db))
        self.catalog = None
        self.catalog_dict = None
        self.catalog_normalized_dict = None
        self.catalog_text = None
        self.backend = None
        self.client = None
        self.legacy_genai = None
        self.model = None
        self.model_name = None
        self.prompt_template = self._load_prompt_template()
        
        # Ð˜Ð½Ð¸Ñ†Ð¸Ð°Ð»Ð¸Ð·Ð°Ñ†Ð¸Ñ Gemini
        if GENAI_SDK_AVAILABLE:
            try:
                self.client = genai_sdk.Client(api_key=self.api_key)
                self.backend = "google-genai"
                logger.info("âœ“ Gemini backend: google-genai")
            except Exception as e:
                logger.warning(f"ÐÐµ ÑƒÐ´Ð°Ð»Ð¾ÑÑŒ Ð¸Ð½Ð¸Ñ†Ð¸Ð°Ð»Ð¸Ð·Ð¸Ñ€Ð¾Ð²Ð°Ñ‚ÑŒ google-genai: {e}")

        if self.backend is None:
            try:
                import google.generativeai as legacy_genai
            except ImportError as e:
                raise ImportError(
                    "Ð£ÑÑ‚Ð°Ð½Ð¾Ð²Ð¸Ñ‚Ðµ Gemini SDK: pip install google-genai "
                    "(fallback: google-generativeai)"
                ) from e

            legacy_genai.configure(api_key=self.api_key)
            self.legacy_genai = legacy_genai
            self.backend = "google-generativeai"
            logger.info("âœ“ Gemini backend: google-generativeai (fallback)")
        
        # Ð˜Ð½Ð¸Ñ†Ð¸Ð°Ð»Ð¸Ð·Ð°Ñ†Ð¸Ñ ÐºÑÑˆÐ°
        self._init_cache_db()
        self._load_catalog()
        
        logger.info("âœ“ ReMoMatcher Ð¸Ð½Ð¸Ñ†Ð¸Ð°Ð»Ð¸Ð·Ð¸Ñ€Ð¾Ð²Ð°Ð½")
    
    def _init_cache_db(self):
        """Ð˜Ð½Ð¸Ñ†Ð¸Ð°Ð»Ð¸Ð·Ð¸Ñ€Ð¾Ð²Ð°Ñ‚ÑŒ Ð‘Ð” ÐºÑÑˆÐ°"""
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
        logger.info("âœ“ Cache DB Ð¸Ð½Ð¸Ñ†Ð¸Ð°Ð»Ð¸Ð·Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð°")
    
    @staticmethod
    def _clean_text_value(value: object) -> str:
        if pd.isna(value):
            return ""
        text = str(value).strip()
        if text.lower() in {"nan", "none", "<na>"}:
            return ""
        return text

    @staticmethod
    def _parse_price_value(value: object) -> Optional[float]:
        if pd.isna(value):
            return None
        if isinstance(value, (int, float)):
            return float(value)

        cleaned = (
            str(value)
            .replace("\xa0", "")
            .replace(" ", "")
            .replace(",", ".")
        )
        cleaned = "".join(ch for ch in cleaned if ch.isdigit() or ch in {".", "-"})
        if not cleaned:
            return None

        try:
            return float(cleaned)
        except ValueError:
            return None

    def _load_catalog(self):
        """Загрузить товарный каталог"""
        logger.info(f"📦 Загрузка каталога из {self.db_csv_path}")

        raw_catalog = pd.read_csv(self.db_csv_path, sep=';', encoding='utf-8')
        self.catalog = canonicalize_catalog_columns(raw_catalog, create_missing=False)
        logger.info(f"✓ Загружено товаров: {len(self.catalog)}")

        if CANONICAL_NAME_COLUMN not in self.catalog.columns:
            raise ValueError(
                f"В каталоге не найдена колонка '{CANONICAL_NAME_COLUMN}'. "
                f"Доступные колонки: {list(self.catalog.columns)}"
            )

        # Подготовить словарь для быстрого поиска
        self.catalog_dict = {}
        self.catalog_normalized_dict = {}
        for idx, row in self.catalog.iterrows():
            name = self._clean_text_value(row.get(CANONICAL_NAME_COLUMN, ""))
            article = self._clean_text_value(row.get(CANONICAL_ARTICLE_COLUMN, ""))
            price = self._parse_price_value(row.get(CANONICAL_PRICE_COLUMN))

            if name:
                item = {
                    'name': name,
                    'name_lc': name.lower(),
                    'article': article,
                    'price': price,
                    'row_idx': idx,
                }

        # Подготовить текстовый формат каталога для Gemini
        self._prepare_catalog_text()

    def _prepare_catalog_text(self, max_items: int = 500):
        """Подготовить каталог в текстовом формате для контекста Gemini"""
        if max_items is None:
            max_items = get_matcher_catalog_sample_items()
        sample = self.catalog.sample(n=min(max_items, len(self.catalog)))

        catalog_lines = []
        for _, row in sample.iterrows():
            line = (
                f"• {row.get(CANONICAL_NAME_COLUMN, 'N/A')} | "
                f"Артикул: {row.get(CANONICAL_ARTICLE_COLUMN, 'N/A')} | "
                f"Цена: {row.get(CANONICAL_PRICE_COLUMN, 'N/A')}"
            )
            catalog_lines.append(line)

        self.catalog_text = "\n".join(catalog_lines[:300])
        logger.info(f"✓ Каталог подготовлен ({len(catalog_lines)} товаров в контексте)")

    def _hash_query(self, query: str) -> str:
        """Ð¥ÑÑˆ Ð·Ð°Ð¿Ñ€Ð¾ÑÐ° Ð´Ð»Ñ ÐºÑÑˆÐ°"""
        return hashlib.md5(query.lower().encode()).hexdigest()

    def _normalize_text(self, text: str) -> str:
        cleaned = re.sub(r"[^\w\dа-яА-ЯёЁ]+", " ", str(text).lower(), flags=re.UNICODE)
        return " ".join(cleaned.split())
    
    def _get_from_cache(self, query: str) -> Optional[Dict]:
        """ÐŸÐ¾Ð»ÑƒÑ‡Ð¸Ñ‚ÑŒ Ñ€ÐµÐ·ÑƒÐ»ÑŒÑ‚Ð°Ñ‚ Ð¸Ð· ÐºÑÑˆÐ°"""
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
                logger.debug(f"ðŸ’¾ Ð ÐµÐ·ÑƒÐ»ÑŒÑ‚Ð°Ñ‚ Ð½Ð°Ð¹Ð´ÐµÐ½ Ð² ÐºÑÑˆÐµ: {query}")
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
            logger.warning(f"âš ï¸ ÐžÑˆÐ¸Ð±ÐºÐ° Ñ‡Ñ‚ÐµÐ½Ð¸Ñ ÐºÑÑˆÐ°: {e}")
        
        return None
    
    def _save_to_cache(self, query: str, found_name: str, price: Optional[float], 
                       article: str, similarity_score: float, raw_response: str):
        """Ð¡Ð¾Ñ…Ñ€Ð°Ð½Ð¸Ñ‚ÑŒ Ñ€ÐµÐ·ÑƒÐ»ÑŒÑ‚Ð°Ñ‚ Ð² ÐºÑÑˆ"""
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
            logger.warning(f"âš ï¸ ÐžÑˆÐ¸Ð±ÐºÐ° ÑÐ¾Ñ…Ñ€Ð°Ð½ÐµÐ½Ð¸Ñ Ð² ÐºÑÑˆ: {e}")
    
    def match(self, query: str, use_cache: bool = True) -> Dict:
        """
        Ð¡Ð¾Ð¿Ð¾ÑÑ‚Ð°Ð²Ð¸Ñ‚ÑŒ Ð½Ð¾Ð¼ÐµÐ½ÐºÐ»Ð°Ñ‚ÑƒÑ€Ñƒ Ð¸Ð· ÐšÐŸ Ñ Ñ‚Ð¾Ð²Ð°Ñ€Ð½Ð¾Ð¹ Ð‘Ð”
        
        Args:
            query: ÐÐ°Ð¸Ð¼ÐµÐ½Ð¾Ð²Ð°Ð½Ð¸Ðµ Ð¸Ð· ÑÑ‚Ð¾Ð»Ð±Ñ†Ð° B ÐšÐŸ
            use_cache: Ð˜ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÑŒ ÐºÑÑˆ?
        
        Returns:
            {
                'found_name': 'ÐÐ°Ð¹Ð´ÐµÐ½Ð½Ð¾Ðµ Ð¸Ð¼Ñ Ð¸Ð· Ð‘Ð”',
                'price': 1234.56,
                'article': 'ART-001',
                'similarity_score': 0.95,
                'from_cache': False,
                'success': True,
                'error': None
            }
        """
        
        # ÐŸÑ€Ð¾Ð²ÐµÑ€Ð¸Ñ‚ÑŒ ÐºÑÑˆ
        if use_cache:
            cached = self._get_from_cache(query)
            if cached:
                return cached
        
        try:
            # Ð¢Ð¾Ñ‡Ð½Ð¾Ðµ ÑÐ¾Ð²Ð¿Ð°Ð´ÐµÐ½Ð¸Ðµ Ð² ÑÐ»Ð¾Ð²Ð°Ñ€Ðµ
            exact_match = self.catalog_dict.get(query.lower())
            if exact_match:
                logger.info(f"âœ“ Ð¢Ð¾Ñ‡Ð½Ð¾Ðµ ÑÐ¾Ð²Ð¿Ð°Ð´ÐµÐ½Ð¸Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½Ð¾: {query}")
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

            # Нормализованное совпадение (ускоряет кейсы с лишними символами/пробелами)
            normalized_query = self._normalize_text(query)
            normalized_match = self.catalog_normalized_dict.get(normalized_query)
            if normalized_match:
                logger.info(f"✓ Нормализованное совпадение найдено: {query}")
                self._save_to_cache(
                    query,
                    normalized_match['name'],
                    normalized_match['price'],
                    normalized_match['article'],
                    0.98,
                    "normalized_match",
                )
                return {
                    'found_name': normalized_match['name'],
                    'price': normalized_match['price'],
                    'article': normalized_match['article'],
                    'similarity_score': 0.98,
                    'from_cache': False,
                    'success': True,
                    'error': None
                }
            
            # Ð˜ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÑŒ Gemini Ð´Ð»Ñ ÑÐµÐ¼Ð°Ð½Ñ‚Ð¸Ñ‡ÐµÑÐºÐ¾Ð³Ð¾ Ð¿Ð¾Ð¸ÑÐºÐ°
            logger.info(f"ðŸ” ÐŸÐ¾Ð¸ÑÐº Ð² Gemini: {query}")
            result = self._match_with_gemini(query)
            
            return result
            
        except Exception as e:
            logger.error(f"âŒ ÐžÑˆÐ¸Ð±ÐºÐ° ÑÐ¾Ð¿Ð¾ÑÑ‚Ð°Ð²Ð»ÐµÐ½Ð¸Ñ: {e}", exc_info=True)
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
        preferred = [self.model_name, *get_matcher_models()]
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
            if self.model is None or self.model_name != model_name:
                self.model = self.legacy_genai.GenerativeModel(model_name)
                self.model_name = model_name
            response = self.model.generate_content(prompt, stream=False)
            return (response.text or '').strip()

        raise RuntimeError("Gemini backend Ð½Ðµ Ð¸Ð½Ð¸Ñ†Ð¸Ð°Ð»Ð¸Ð·Ð¸Ñ€Ð¾Ð²Ð°Ð½")
    
    def _match_with_gemini(self, query: str) -> Dict:
        """Ð˜ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÑŒ Gemini Ð´Ð»Ñ ÑÐ¾Ð¿Ð¾ÑÑ‚Ð°Ð²Ð»ÐµÐ½Ð¸Ñ"""

        prompt = f"""Ð¢Ñ‹ ÑÐºÑÐ¿ÐµÑ€Ñ‚ Ð¿Ð¾ Ñ‚ÐµÑ…Ð½Ð¸Ñ‡ÐµÑÐºÐ¾Ð¹ Ð½Ð¾Ð¼ÐµÐ½ÐºÐ»Ð°Ñ‚ÑƒÑ€Ðµ Ð¾Ð±Ð¾Ñ€ÑƒÐ´Ð¾Ð²Ð°Ð½Ð¸Ñ, ÐºÐ°Ð±ÐµÐ»Ñ Ð¸ Ð¼Ð°Ñ‚ÐµÑ€Ð¸Ð°Ð»Ð¾Ð².

Ð—Ð°Ð´Ð°Ñ‡Ð°: ÐÐ°Ð¹Ñ‚Ð¸ Ð² ÐºÐ°Ñ‚Ð°Ð»Ð¾Ð³Ðµ Ñ‚Ð¾Ð²Ð°Ñ€, ÐºÐ¾Ñ‚Ð¾Ñ€Ñ‹Ð¹ Ð¢ÐžÐ§ÐÐž ÑÐ¾Ð¾Ñ‚Ð²ÐµÑ‚ÑÑ‚Ð²ÑƒÐµÑ‚ Ð·Ð°Ð¿Ñ€Ð¾ÑÑƒ Ð¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÐµÐ»Ñ.

ÐšÐÐ¢ÐÐ›ÐžÐ“ Ð”ÐžÐ¡Ð¢Ð£ÐŸÐÐ«Ð¥ Ð¢ÐžÐ’ÐÐ ÐžÐ’:
{self.catalog_text}

Ð—ÐÐŸÐ ÐžÐ¡ ÐŸÐžÐ›Ð¬Ð—ÐžÐ’ÐÐ¢Ð•Ð›Ð¯: "{query}"

Ð˜ÐÐ¡Ð¢Ð Ð£ÐšÐ¦Ð˜Ð˜:
1. Ð’Ð½Ð¸Ð¼Ð°Ñ‚ÐµÐ»ÑŒÐ½Ð¾ Ð¿Ñ€Ð¾Ð°Ð½Ð°Ð»Ð¸Ð·Ð¸Ñ€ÑƒÐ¹ Ð·Ð°Ð¿Ñ€Ð¾Ñ Ð¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÐµÐ»Ñ
2. ÐÐ°Ð¹Ð´Ð¸ Ð² ÐºÐ°Ñ‚Ð°Ð»Ð¾Ð³Ðµ Ñ‚Ð¾Ð²Ð°Ñ€ Ñ ÐœÐÐšÐ¡Ð˜ÐœÐÐ›Ð¬ÐÐ«Ðœ ÑÐµÐ¼Ð°Ð½Ñ‚Ð¸Ñ‡ÐµÑÐºÐ¸Ð¼ ÑÐ¾Ð²Ð¿Ð°Ð´ÐµÐ½Ð¸ÐµÐ¼
3. Ð£Ñ‡Ð¸Ñ‚Ñ‹Ð²Ð°Ð¹:
   - Ð¢ÐµÑ…Ð½Ð¸Ñ‡ÐµÑÐºÐ¸Ðµ Ñ…Ð°Ñ€Ð°ÐºÑ‚ÐµÑ€Ð¸ÑÑ‚Ð¸ÐºÐ¸ (ÑÐµÑ‡ÐµÐ½Ð¸Ðµ, Ð²Ð¾Ð»ÑŒÑ‚Ð°Ð¶, Ð¼Ð°Ñ‚ÐµÑ€Ð¸Ð°Ð», Ñ€Ð°Ð·Ð¼ÐµÑ€Ñ‹)
   - ÐÐ°Ð·Ð½Ð°Ñ‡ÐµÐ½Ð¸Ðµ Ñ‚Ð¾Ð²Ð°Ñ€Ð° (ÐºÐ°Ð±ÐµÐ»ÑŒ, ÐºÐ¾Ð½Ð´Ð¸Ñ†Ð¸Ð¾Ð½ÐµÑ€, ÑÐ²Ð°Ñ€Ð¾Ñ‡Ð½Ñ‹Ð¹ Ð°Ð¿Ð¿Ð°Ñ€Ð°Ñ‚ Ð¸ Ñ‚.Ð´.)
   - ÐÐ»ÑŒÑ‚ÐµÑ€Ð½Ð°Ñ‚Ð¸Ð²Ð½Ñ‹Ðµ Ð½Ð°Ð·Ð²Ð°Ð½Ð¸Ñ Ð¸ Ð°Ð±Ð±Ñ€ÐµÐ²Ð¸Ð°Ñ‚ÑƒÑ€Ñ‹
4. Ð•ÑÐ»Ð¸ Ñ€ÐµÐ»ÐµÐ²Ð°Ð½Ñ‚Ð½Ð¾Ð³Ð¾ Ð°Ð½Ð°Ð»Ð¾Ð³Ð° Ð½ÐµÑ‚, Ð²ÐµÑ€Ð½Ð¸ found_name=null
5. Ð’Ñ‹Ð²Ð¾Ð´ Ð¢ÐžÐ›Ð¬ÐšÐž Ð² Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚Ðµ JSON (Ð±ÐµÐ· Ð»Ð¸ÑˆÐ½ÐµÐ³Ð¾ Ñ‚ÐµÐºÑÑ‚Ð°)

Ð¤ÐžÐ ÐœÐÐ¢ ÐžÐ¢Ð’Ð•Ð¢Ð:
{{
    "found_name": "Ð¢Ð¾Ñ‡Ð½Ð¾Ðµ Ð½Ð°Ð·Ð²Ð°Ð½Ð¸Ðµ Ð¸Ð· ÐºÐ°Ñ‚Ð°Ð»Ð¾Ð³Ð°",
    "article": "ÐÑ€Ñ‚Ð¸ÐºÑƒÐ» Ñ‚Ð¾Ð²Ð°Ñ€Ð°",
    "confidence": 0.95,
    "reasoning": "ÐšÑ€Ð°Ñ‚ÐºÐ¾Ðµ Ð¾Ð±ÑŠÑÑÐ½ÐµÐ½Ð¸Ðµ Ð¿Ð¾Ñ‡ÐµÐ¼Ñƒ ÑÑ‚Ð¾ ÑÐ¾Ð²Ð¿Ð°Ð´ÐµÐ½Ð¸Ðµ"
}}

Ð•ÑÐ»Ð¸ Ñ‚Ð¾Ð²Ð°Ñ€ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½:
{{
    "found_name": null,
    "article": null,
    "confidence": 0,
    "reasoning": "Ñ‚Ð¾Ð²Ð°Ñ€ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½ Ð² ÐºÐ°Ñ‚Ð°Ð»Ð¾Ð³Ðµ"
}}
"""

        def parse_result(raw_text: str) -> Dict:
            start_idx = raw_text.find('{')
            end_idx = raw_text.rfind('}') + 1
            if start_idx == -1 or end_idx <= start_idx:
                raise ValueError("JSON Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½ Ð² Ð¾Ñ‚Ð²ÐµÑ‚Ðµ")

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
                        logger.warning(f"âš ï¸ Ð¢Ð¾Ð²Ð°Ñ€ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½ Ð´Ð»Ñ: {query}")
                    else:
                        logger.info(f"âœ“ ÐÐ°Ð¹Ð´ÐµÐ½Ð¾: {parsed['found_name']} (confidence: {parsed['similarity_score']})")
                    return parsed
                except Exception as model_error:
                    last_error = model_error
                    logger.warning(f"ÐœÐ¾Ð´ÐµÐ»ÑŒ {model_name} Ð½Ðµ ÑÑ€Ð°Ð±Ð¾Ñ‚Ð°Ð»Ð°: {model_error}")

            raise RuntimeError(f"Gemini fallback exhausted: {last_error}")

        except Exception as e:
            logger.error(f"âŒ ÐžÑˆÐ¸Ð±ÐºÐ° Gemini API: {e}", exc_info=True)
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
        """Ð¡Ð¾Ñ…Ñ€Ð°Ð½Ð¸Ñ‚ÑŒ Ñ€ÐµÐ·ÑƒÐ»ÑŒÑ‚Ð°Ñ‚ Ð² Ð¸ÑÑ‚Ð¾Ñ€Ð¸ÑŽ"""
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
            logger.warning(f"âš ï¸ ÐžÑˆÐ¸Ð±ÐºÐ° ÑÐ¾Ñ…Ñ€Ð°Ð½ÐµÐ½Ð¸Ñ Ð² Ð¸ÑÑ‚Ð¾Ñ€Ð¸ÑŽ: {e}")
    
    def process_excel(self, excel_path: str, output_path: str = None) -> Tuple[pd.DataFrame, Dict]:
        """Обработать весь Excel файл КП"""
        logger.info(f"📊 Начало обработки: {excel_path}")

        try:
            df = pd.read_excel(excel_path)
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки Excel: {e}")
            raise

        # Найти целевой столбец с номенклатурой.
        col_b = None
        for col in df.columns:
            normalized_col = str(col).strip().lower()
            if "наименование" in normalized_col and "оборудован" in normalized_col:
                col_b = col
                break

        if col_b is None and len(df.columns) > 1:
            col_b = df.columns[1]

        if col_b is None:
            raise ValueError("Не найден столбец 'Наименование оборудования, материалов и кабелей'")

        logger.info(f"✓ Найден столбец: {col_b}")

        if "Цена" not in df.columns:
            df["Цена"] = pd.Series([None] * len(df), dtype="float64")
        else:
            df["Цена"] = pd.to_numeric(df["Цена"], errors="coerce").astype("float64")

        for text_col in ("Найденная номенклатура", "Артикул", "Ошибка сопоставления"):
            if text_col not in df.columns:
                df[text_col] = None
            else:
                df[text_col] = df[text_col].astype(object)

        stats = {
            "total": 0,
            "found": 0,
            "not_found": 0,
            "from_cache": 0,
            "errors": 0,
        }

        skip_queries = {
            "наименование",
            "наименование оборудования, материалов и кабелей",
            "nomenclature",
        }

        for idx, row in df.iterrows():
            query = str(row[col_b]).strip()
            if not query or query.lower() == "nan":
                continue

            if query.lower() in skip_queries:
                continue

            stats["total"] += 1
            result = self.match(query, use_cache=True)

            found_name = result.get("found_name") or MISSING_POSITION_TEXT
            df.at[idx, "Цена"] = result.get("price")
            df.at[idx, "Найденная номенклатура"] = found_name
            df.at[idx, "Артикул"] = result.get("article")
            df.at[idx, "Ошибка сопоставления"] = result.get("error")

            if result.get("from_cache"):
                stats["from_cache"] += 1

            if found_name == MISSING_POSITION_TEXT:
                stats["not_found"] += 1
            else:
                stats["found"] += 1

            if not result.get("success", True):
                stats["errors"] += 1
                logger.warning(f"⚠️ [{idx + 1}] Ошибка: {result.get('error')}")

            if (idx + 1) % 10 == 0:
                logger.info(f"⏳ Обработано {idx + 1}/{len(df)} строк")

        if output_path is None:
            src = Path(excel_path)
            output_path = str(src.with_name(f"{src.stem}_matched{src.suffix}"))

        try:
            df.to_excel(output_path, index=False)
            logger.info(f"✓ Результат сохранен: {output_path}")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения Excel: {e}")
            raise

        logger.info("\n" + "=" * 60)
        logger.info("📊 СТАТИСТИКА ОБРАБОТКИ")
        logger.info("=" * 60)
        logger.info(f"Всего строк:        {stats['total']}")
        logger.info(f"Найдено товаров:    {stats['found']}")
        logger.info(f"Не найдено:         {stats['not_found']}")
        logger.info(f"Из кэша:            {stats['from_cache']}")
        logger.info(f"Ошибок:             {stats['errors']}")
        if stats["total"] > 0:
            logger.info(f"Успешность:         {stats['found'] / stats['total'] * 100:.1f}%")
        else:
            logger.info("Успешность:         N/A")
        logger.info("=" * 60 + "\n")

        return df, stats


if __name__ == "__main__":
    # ÐŸÑ€Ð¸Ð¼ÐµÑ€ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ð½Ð¸Ñ
    API_KEY = os.getenv('GEMINI_API_KEY')
    if not API_KEY:
        print("âš ï¸ Ð£ÑÑ‚Ð°Ð½Ð¾Ð²Ð¸Ñ‚Ðµ Ð¿ÐµÑ€ÐµÐ¼ÐµÐ½Ð½ÑƒÑŽ Ð¾ÐºÑ€ÑƒÐ¶ÐµÐ½Ð¸Ñ GEMINI_API_KEY")
        print("ÐÐ° Windows: set GEMINI_API_KEY=Ð²Ð°Ñˆ_ÐºÐ»ÑŽÑ‡")
        print("ÐÐ° Linux/Mac: export GEMINI_API_KEY=Ð²Ð°Ñˆ_ÐºÐ»ÑŽÑ‡")
        exit(1)
    
    matcher = ReMoMatcher(
        gemini_api_key=API_KEY,
        db_csv_path=str(get_catalog_csv_path())
    )
    
    # Ð¢ÐµÑÑ‚Ð¾Ð²Ð¾Ðµ ÑÐ¾Ð¿Ð¾ÑÑ‚Ð°Ð²Ð»ÐµÐ½Ð¸Ðµ
    test_queries = [
        "ÐšÐ°Ð±ÐµÐ»ÑŒ Ð¼ÐµÐ´Ð½Ñ‹Ð¹ 4ÐºÐ².Ð¼Ð¼",
        "ÐŸÑ€Ð¾Ð²Ð¾Ð´ Cu 4x2.5",
        "Ð¡Ð²Ð°Ñ€Ð¾Ñ‡Ð½Ñ‹Ð¹ Ð°Ð¿Ð¿Ð°Ñ€Ð°Ñ‚ Ð¸Ð½Ð²ÐµÑ€Ñ‚Ð¾Ñ€",
    ]
    
    print("\n" + "="*60)
    print("ðŸ§ª Ð¢Ð•Ð¡Ð¢ÐžÐ’ÐžÐ• Ð¡ÐžÐŸÐžÐ¡Ð¢ÐÐ’Ð›Ð•ÐÐ˜Ð•")
    print("="*60 + "\n")
    
    for query in test_queries:
        result = matcher.match(query)
        print(f"Ð—Ð°Ð¿Ñ€Ð¾Ñ:     {query}")
        print(f"ÐÐ°Ð¹Ð´ÐµÐ½Ð¾:    {result['found_name']}")
        print(f"ÐÑ€Ñ‚Ð¸ÐºÑƒÐ»:    {result['article']}")
        print(f"Ð¦ÐµÐ½Ð°:       {result['price']}")
        print(f"Ð£Ð²ÐµÑ€ÐµÐ½Ð½Ð¾ÑÑ‚ÑŒ: {result['similarity_score']}")
        print("-" * 60)
