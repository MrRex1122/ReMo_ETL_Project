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
import re
import math
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from catalog_merge import build_merged_catalog
from config import (
    get_catalog_csv_path,
    get_matcher_parallel_requests,
    get_matcher_cache_db_path,
    get_matcher_local_confidence_threshold,
    get_matcher_local_margin_threshold,
    get_matcher_models,
    get_matcher_context_chunk_size,
    get_matcher_max_context_chunks,
    get_matcher_retrieval_candidates,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

MISSING_POSITION_TEXT = "Позиция отсутствует"
GROUP_TOKEN_STOPWORDS = {"и", "в", "на", "для", "с", "по", "из", "шт", "мм", "м", "к", "u", "duplex"}
CANONICAL_NAME_COLUMN = "Наименование"
CANONICAL_ARTICLE_COLUMN = "Артикул"
CANONICAL_PRICE_COLUMN = "Цена розничная"
MATCH_MODE_EXACT = "exact"
MATCH_MODE_ANALOG = "analog"

TERM_NORMALIZATION_ALIASES = {
    "patch cord": "патч корд",
    "patch-cord": "патч корд",
    "patchcord": "патч корд",
    "патч-корд": "патч корд",
    "патчкорд": "патч корд",
    "шнур коммутационный": "патч корд",
    "коммутационный шнур": "патч корд",
}

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
    
    def __init__(self, gemini_api_key: str, db_csv_path: str, cache_db: str = "matcher_cache.db", parallel_requests: int | None = None, catalog_sample_items: int = 500, match_mode: str = MATCH_MODE_EXACT):
        """
        Args:
            gemini_api_key: API ÐºÐ»ÑŽÑ‡ Google Gemini
            db_csv_path: ÐŸÑƒÑ‚ÑŒ Ðº price_clean.csv Ñ Ñ‚Ð¾Ð²Ð°Ñ€Ð½Ð¾Ð¹ Ð±Ð°Ð·Ð¾Ð¹
            cache_db: Ð‘Ð” Ð´Ð»Ñ ÐºÑÑˆÐ¸Ñ€Ð¾Ð²Ð°Ð½Ð¸Ñ Ñ€ÐµÐ·ÑƒÐ»ÑŒÑ‚Ð°Ñ‚Ð¾Ð² ÑÐ¾Ð¿Ð¾ÑÑ‚Ð°Ð²Ð»ÐµÐ½Ð¸Ñ
        """
        self.api_key = gemini_api_key
        self.db_csv_path = self._resolve_catalog_csv_path(db_csv_path)
        self.cache_db = str(get_matcher_cache_db_path(cache_db))
        self.catalog = None
        self.catalog_dict = None
        self.catalog_normalized_dict = {}
        self.catalog_items = []
        self.group_index = {}
        self.token_idf = {}
        self.catalog_text = None
        self.local_confidence_threshold = get_matcher_local_confidence_threshold()
        self.local_margin_threshold = get_matcher_local_margin_threshold()
        self.backend = None
        self.client = None
        self.legacy_genai = None
        self.model = None
        self.model_name = None
        self.parallel_requests = min(10, max(1, int(parallel_requests or get_matcher_parallel_requests())))
        self.catalog_sample_items = max(50, int(catalog_sample_items))
        self.match_mode = self._sanitize_match_mode(match_mode)
        self.context_chunk_size = get_matcher_context_chunk_size()
        self.max_context_chunks = get_matcher_max_context_chunks()
        self.retrieval_candidates_limit = get_matcher_retrieval_candidates()
        self.local_confidence_threshold = get_matcher_local_confidence_threshold()
        self.local_margin_threshold = get_matcher_local_margin_threshold()
        
        # Ð˜Ð½Ð¸Ñ†Ð¸Ð°Ð»Ð¸Ð·Ð°Ñ†Ð¸Ñ Gemini
        if GENAI_SDK_AVAILABLE:
            try:
                self.client = genai_sdk.Client(api_key=self.api_key)
                self.backend = "google-genai"
                logger.info("Gemini backend: google-genai")
            except Exception as e:
                logger.warning(f"Failed to initialize google-genai: {e}")

        if self.backend is None:
            try:
                import google.generativeai as legacy_genai
            except ImportError as e:
                raise ImportError(
                    "Install Gemini SDK: pip install google-genai "
                    "(fallback: google-generativeai)"
                ) from e

            legacy_genai.configure(api_key=self.api_key)
            self.legacy_genai = legacy_genai
            self.backend = "google-generativeai"
            logger.info("Gemini backend: google-generativeai (fallback)")
        
        # Ð˜Ð½Ð¸Ñ†Ð¸Ð°Ð»Ð¸Ð·Ð°Ñ†Ð¸Ñ ÐºÑÑˆÐ°
        self._init_cache_db()
        self._load_catalog()
        
        logger.info("ReMoMatcher initialized")
    

    def _resolve_catalog_csv_path(self, db_csv_path: str) -> str:
        source_path = Path(str(db_csv_path))
        if source_path.is_dir():
            merged_path = source_path / "price_clean_merged.csv"
            resolved = build_merged_catalog(source_path, merged_path)
            logger.info(f"🧩 Объединенный каталог подготовлен: {resolved}")
            return str(resolved)
        return str(source_path)

    def _sanitize_match_mode(self, value: str | None) -> str:
        mode = str(value or '').strip().lower()
        if mode in {MATCH_MODE_EXACT, MATCH_MODE_ANALOG}:
            return mode
        return MATCH_MODE_EXACT

    def _normalize_query_terms(self, text: str) -> str:
        normalized = str(text or '').lower()
        for source, target in TERM_NORMALIZATION_ALIASES.items():
            normalized = normalized.replace(source, target)
        return normalized

    def _classify_item_type(self, text: str) -> str:
        normalized = self._normalize_query_terms(text)

        if 'патч корд' in normalized:
            return 'patch_cord'

        bulk_markers = ('витая пара', 'utp', 'ftp', 'f/utp', 'u/utp', 'бухта', '305м', '305 м', '500м', '500 м')
        if any(marker in normalized for marker in bulk_markers):
            return 'bulk_twisted_pair'

        if 'коаксиаль' in normalized or 'rg-' in normalized or '75 ом' in normalized or '50 ом' in normalized:
            return 'coax'

        return 'other'

    def _is_disallowed_category_substitution(self, query: str, candidate_name: str) -> bool:
        query_type = self._classify_item_type(query)
        candidate_type = self._classify_item_type(candidate_name)

        if query_type == 'patch_cord' and candidate_type == 'bulk_twisted_pair':
            return True

        if self.match_mode == MATCH_MODE_EXACT:
            if query_type != 'other' and candidate_type != 'other' and query_type != candidate_type:
                return True

        return False

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
        logger.info("Cache DB initialized")
    
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
        logger.info(f"Loading catalog from {self.db_csv_path}")
        
        self.catalog = pd.read_csv(
            self.db_csv_path,
            sep=';',
            encoding='utf-8',
            low_memory=False,
        )
        logger.info(f"Loaded catalog items: {len(self.catalog)}")
        
        # Подготовить словарь для быстрого поиска
        self.catalog_dict = {}
        self.catalog_normalized_dict = {}
        self.catalog_items = []
        token_to_items: Dict[str, List[Dict]] = defaultdict(list)
        token_doc_frequency: Dict[str, int] = defaultdict(int)
        total_items = 0
        for idx, row in self.catalog.iterrows():
            name = str(row.get(CANONICAL_NAME_COLUMN, '')).strip()
            article = str(row.get(CANONICAL_ARTICLE_COLUMN, '')).strip()
            price = float(row.get(CANONICAL_PRICE_COLUMN, 0)) if CANONICAL_PRICE_COLUMN in row else None

            if name:
                tokens = sorted(set(self._tokenize(name)))
                item = {
                    'name': name,
                    'name_lc': name.lower(),
                    'article': article,
                    'price': price,
                    'row_idx': idx,
                    'tokens': tokens,
                }
                self.catalog_dict[name.lower()] = item
                normalized_name = self._normalize_text(name)
                if normalized_name and normalized_name not in self.catalog_normalized_dict:
                    self.catalog_normalized_dict[normalized_name] = item
                self.catalog_items.append(item)
                total_items += 1
                for token in tokens:
                    token_to_items[token].append(item)
                    token_doc_frequency[token] += 1

        self.group_index = {
            token: items
            for token, items in token_to_items.items()
            if len(items) >= 3
        }
        self.token_idf = {
            token: math.log((1 + total_items) / (1 + freq)) + 1.0
            for token, freq in token_doc_frequency.items()
        }

        # Подготовить текстовый формат каталога для Gemini
        self._prepare_catalog_text(max_items=self.catalog_sample_items)
    
    def _prepare_catalog_text(self, max_items: int = 500):
        """Подготовить каталог в текстовом формате для контекста Gemini."""
        limit = min(max_items, len(self.catalog))
        sample = self.catalog.head(limit)

        catalog_lines = []
        for idx, row in sample.iterrows():
            line = f"• {row.get(CANONICAL_NAME_COLUMN, 'N/A')} | Артикул: {row.get(CANONICAL_ARTICLE_COLUMN, 'N/A')} | Цена: {row.get(CANONICAL_PRICE_COLUMN, 'N/A')}"
            catalog_lines.append(line)

        self.catalog_text = "\n".join(catalog_lines[:300])  # Ограничить для контекста
        logger.info(f"✓ Каталог подготовлен ({len(catalog_lines)} товаров в контексте)")

    def _normalize_text(self, text: str) -> str:
        cleaned = re.sub(r"[^\w\dа-яА-ЯёЁ]+", " ", str(text).lower(), flags=re.UNICODE)
        return " ".join(cleaned.split())

    def _tokenize(self, text: str) -> List[str]:
        tokens = re.findall(r"[a-zA-Zа-яА-Я0-9]+", str(text).lower())
        return [token for token in tokens if len(token) >= 2 and token not in GROUP_TOKEN_STOPWORDS]

    def _rank_group_candidates(self, query: str) -> List[Dict]:
        """Вернуть ранжированные кандидаты по токен-группам запроса."""
        query_tokens = self._tokenize(query)
        if not query_tokens or not self.group_index:
            return []

        query_token_set = set(query_tokens)
        retrieval_limit = max(1, int(getattr(self, "retrieval_candidates_limit", 1200)))
        per_token_cap = retrieval_limit
        candidate_stats: Dict[str, Dict] = {}

        for token in query_token_set:
            token_weight = getattr(self, "token_idf", {}).get(token, 1.0)
            for item in self.group_index.get(token, [])[:per_token_cap]:
                key = item['name_lc']
                entry = candidate_stats.get(key)
                if entry is None:
                    entry = {
                        'item': item,
                        'overlap_count': 0,
                        'idf_score': 0.0,
                    }
                    candidate_stats[key] = entry
                entry['overlap_count'] += 1
                entry['idf_score'] += token_weight

        if not candidate_stats:
            return []

        ranked = sorted(
            candidate_stats.values(),
            key=lambda entry: (
                entry['idf_score'],
                entry['overlap_count'],
                -entry['item']['row_idx'],
            ),
            reverse=True,
        )

        return [entry['item'] for entry in ranked[:retrieval_limit]]

    def _build_context_for_query(self, query: str, max_lines: int = 300) -> str:
        """Собрать контекст по релевантным группам, а не случайным позициям."""
        ranked_items = self._rank_group_candidates(query)
        if not ranked_items:
            return self.catalog_text

        lines = [
            f"• {item['name']} | Артикул: {item.get('article', 'N/A')} | Цена: {item.get('price', 'N/A')}"
            for item in ranked_items[:max_lines]
        ]
        return "\n".join(lines) if lines else self.catalog_text

    def _build_context_chunks(self, query: str, chunk_size: int | None = None, max_chunks: int | None = None) -> List[str]:
        """Сформировать несколько чанков контекста для повторных попыток Gemini."""
        ranked_items = self._rank_group_candidates(query)
        if not ranked_items:
            return [self.catalog_text]

        chunk_size = max(50, int(chunk_size or getattr(self, "context_chunk_size", 300)))
        max_chunks = max(1, int(max_chunks or getattr(self, "max_context_chunks", 4)))

        chunks = []
        for offset in range(0, len(ranked_items), chunk_size):
            if len(chunks) >= max_chunks:
                break
            chunk_items = ranked_items[offset: offset + chunk_size]
            if not chunk_items:
                continue
            chunk_text = "\n".join(
                f"• {item['name']} | Артикул: {item.get('article', 'N/A')} | Цена: {item.get('price', 'N/A')}"
                for item in chunk_items
            )
            if chunk_text.strip():
                chunks.append(chunk_text)

        return chunks or [self.catalog_text]

    def _hash_query(self, query: str) -> str:
        """Хэш запроса для кэша"""
        normalized = self._normalize_text(query)
        value = normalized if normalized else str(query).lower()
        return hashlib.md5(value.encode()).hexdigest()

    def _normalize_text(self, text: str) -> str:
        cleaned = re.sub(r"[^\w\dа-яА-ЯёЁ]+", " ", str(text).lower(), flags=re.UNICODE)
        return " ".join(cleaned.split())

    def _tokenize(self, normalized_text: str) -> List[str]:
        return [token for token in normalized_text.split() if len(token) >= 2]

    def _load_prompt_template(self) -> str:
        """Загрузить шаблон prompt из файла или вернуть дефолтный."""
        path_raw = os.getenv("REMO_MATCH_PROMPT_TEMPLATE_PATH")
        if not path_raw:
            return DEFAULT_MATCH_PROMPT_TEMPLATE

        path = Path(path_raw)
        if not path.exists():
            logger.warning(f"Prompt template not found at {path}; using default template")
            return DEFAULT_MATCH_PROMPT_TEMPLATE

        try:
            custom_template = path.read_text(encoding="utf-8").strip()
            if "{catalog_context}" not in custom_template or "{query}" not in custom_template:
                logger.warning(
                    "Custom prompt template misses required placeholders {catalog_context}/{query}; using default"
                )
                return DEFAULT_MATCH_PROMPT_TEMPLATE
            logger.info(f"✓ Custom prompt template loaded: {path}")
            return custom_template
        except Exception as e:
            logger.warning(f"Failed to read custom prompt template: {e}; using default")
            return DEFAULT_MATCH_PROMPT_TEMPLATE

    def _build_match_prompt(self, query: str, catalog_context: str) -> str:
        return self.prompt_template.format(query=query, catalog_context=catalog_context)

    def _rank_candidates(self, query: str, limit: int = 40) -> List[Tuple[float, Dict]]:
        """Вернуть кандидатов с оценками релевантности."""
        normalized_query = self._normalize_text(query)
        query_tokens = self._tokenize(normalized_query)
        if not query_tokens:
            return [(1.0, item) for item in self.catalog_items[:limit]]

        candidate_map = {}
        for token in query_tokens:
            for item in self.token_index.get(token, []):
                key = item['name_lc']
                if key not in candidate_map:
                    candidate_map[key] = item

        if not candidate_map:
            candidate_map = {item['name_lc']: item for item in self.catalog_items[: min(800, len(self.catalog_items))]}

        scored: List[Tuple[float, Dict]] = []
        query_set = set(query_tokens)
        for item in candidate_map.values():
            candidate_tokens = set(self._tokenize(item.get('normalized_name', '')))
            if not candidate_tokens:
                continue
            overlap = len(query_set & candidate_tokens)
            union = len(query_set | candidate_tokens)
            jaccard = overlap / union if union else 0
            ratio = SequenceMatcher(None, normalized_query, item.get('normalized_name', '')).ratio()
            score = (jaccard * 0.75) + (ratio * 0.25)
            scored.append((score, item))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [(score, item) for score, item in scored[:limit] if score > 0]

    def _select_candidates(self, query: str, limit: int = 40) -> List[Dict]:
        """Выбрать топ-кандидатов из каталога для передачи в Gemini."""
        ranked = self._rank_candidates(query, limit)
        return [item for score, item in ranked]

    def _try_local_semantic_match(self, query: str) -> Optional[Dict]:
        """Попытаться вернуть уверенный локальный матч без Gemini."""
        ranked = self._rank_candidates(query, limit=2)
        if not ranked:
            return None

        best_score, best_item = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        margin = best_score - second_score

        if best_score < self.local_confidence_threshold or margin < self.local_margin_threshold:
            return None

        logger.info(
            "High-confidence local match: %s (score=%.3f margin=%.3f)",
            query,
            best_score,
            margin,
        )
        self._save_to_cache(
            query,
            best_item['name'],
            best_item['price'],
            best_item['article'],
            float(best_score),
            "local_semantic_match",
        )
        return {
            'found_name': best_item['name'],
            'price': best_item['price'],
            'article': best_item['article'],
            'similarity_score': float(best_score),
            'from_cache': False,
            'success': True,
            'error': None
        }

    def _build_catalog_context(self, candidates: List[Dict], max_lines: int = 60) -> str:
        if not candidates:
            return self.catalog_text

        lines = []
        for item in candidates[:max_lines]:
            lines.append(
                f"• {item.get('name', 'N/A')} | Артикул: {item.get('article', 'N/A')} | Цена: {item.get('price', 'N/A')}"
            )
        return "\n".join(lines)
    
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

                # Не используем кэш для "не найдено":
                # такие позиции нужно прогонять повторно при новом запуске,
                # чтобы поймать улучшения каталога/моделей.
                if found_name == MISSING_POSITION_TEXT:
                    return None

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
                logger.warning(f"Cache read error: {e}")
        
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
            logger.warning(f"Cache write error: {e}")
    
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
                'error': None,
                'reason': reasoning,
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
                logger.info(f"Exact match found: {query}")
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
                logger.info(f"Normalized match found: {query}")
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
            
            normalized_query = self._normalize_text(query)
            normalized_match = getattr(self, "catalog_normalized_dict", {}).get(normalized_query)
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

            # Использовать Gemini для семантического поиска
            logger.info(f"Gemini search: {query}")
            result = self._match_with_gemini(query)
            
            return result
            
        except Exception as e:
            logger.error(f"Matching error: {e}", exc_info=True)
            return {
                'found_name': None,
                'price': None,
                'article': None,
                'similarity_score': 0,
                'from_cache': False,
                'success': False,
                'error': str(e),
                'reason': '',
            }

    def _candidate_models(self) -> List[str]:
        preferred = [self.model_name, *get_matcher_models()]
        result = []
        seen = set()
        for name in preferred:
            model_name = str(name or '').strip()
            if not model_name or model_name in seen:
                continue
            seen.add(model_name)
            result.append(model_name)
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

        raise RuntimeError("Gemini backend is not initialized")
    
    def _match_with_gemini(self, query: str) -> Dict:
        """Использовать Gemini для сопоставления"""

        context_chunks = self._build_context_chunks(query)

        def build_prompt(context_text: str) -> str:
            return f"""Ты эксперт по технической номенклатуре оборудования, кабеля и материалов.

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
5. Для режима analog можно предложить максимально близкий аналог, но не смешивай разные товарные типы (пример: патч-корд нельзя заменять на витую пару в бухте)
6. Вывод ТОЛЬКО в формате JSON (без лишнего текста)

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
                raise ValueError("JSON not found in model response")

            gemini_result = json.loads(raw_text[start_idx:end_idx])
            found_name = gemini_result.get('found_name')
            article = gemini_result.get('article')
            confidence = float(gemini_result.get('confidence', 0) or 0)
            reasoning = str(gemini_result.get('reasoning') or '').strip()

            price = None
            if found_name:
                if self._is_disallowed_category_substitution(query, str(found_name)):
                    found_name = MISSING_POSITION_TEXT
                    reasoning = reasoning or (
                        'Найдена позиция другого типа: для патч-корда нельзя подставлять витую пару в бухте.'
                    )
                else:
                    match = self.catalog_dict.get(str(found_name).lower())
                    if match:
                        price = match['price']
                        article = article or match['article']
            else:
                found_name = MISSING_POSITION_TEXT

            if found_name == MISSING_POSITION_TEXT and not reasoning:
                reasoning = 'Релевантный товар в текущем каталоге не найден.'

            return {
                'found_name': found_name,
                'price': price,
                'article': article,
                'similarity_score': confidence,
                'from_cache': False,
                'success': True,
                'error': None,
                'reason': reasoning,
            }

        try:
            candidate_names = self._candidate_models()
            last_error = None
            last_missing_result = None
            last_raw_text = ""

            for chunk_idx, context_text in enumerate(context_chunks, start=1):
                prompt = build_prompt(context_text)
                if len(context_chunks) > 1:
                    logger.info(f"🔁 Попытка контекста {chunk_idx}/{len(context_chunks)} для: {query}")

                for model_name in candidate_names:
                    try:
                        raw_text = self._generate_gemini_text(prompt, model_name)
                        parsed = parse_result(raw_text)
                        self.model_name = model_name

                        if parsed['found_name'] == MISSING_POSITION_TEXT:
                            last_missing_result = parsed
                            last_raw_text = raw_text
                            logger.warning(f"⚠️ Товар не найден для: {query} (контекст {chunk_idx})")
                            continue

                        self._save_to_cache(
                            query,
                            parsed['found_name'],
                            parsed['price'],
                            parsed['article'] or '',
                            parsed['similarity_score'],
                            raw_text,
                        )
                        logger.info(f"✓ Найдено: {parsed['found_name']} (confidence: {parsed['similarity_score']})")
                        return parsed
                    except Exception as model_error:
                        last_error = model_error
                        logger.warning(f"Модель {model_name} не сработала: {model_error}")

            if last_missing_result is not None:
                self._save_to_cache(
                    query,
                    last_missing_result['found_name'],
                    last_missing_result['price'],
                    last_missing_result['article'] or '',
                    last_missing_result['similarity_score'],
                    last_raw_text,
                )
                return last_missing_result

            raise RuntimeError(f"Gemini fallback exhausted: {last_error}")

        except Exception as e:
            logger.error(f"Gemini API error: {e}", exc_info=True)
            return {
                'found_name': MISSING_POSITION_TEXT,
                'price': None,
                'article': None,
                'similarity_score': 0,
                'from_cache': False,
                'success': False,
                'error': str(e),
                'reason': '',
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
            logger.warning(f"History write error: {e}")
    

    def _run_matches_parallel(self, tasks: List[Tuple[int, str]]) -> List[Tuple[int, Dict]]:
        """Выполнить сопоставление запросов с ограниченным параллелизмом."""
        if not tasks:
            return []

        # По требованию: запускать максимум параллельных запросов — по числу позиций.
        workers = max(1, len(tasks))
        if workers <= 1:
            return [(idx, self.match(query, use_cache=True)) for idx, query in tasks]

        logger.info(f"⚡ Параллельная обработка включена: {workers} запросов одновременно (по числу позиций)")
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
        logger.info(f"Start processing Excel: {excel_path}")
        
        # Загрузить Excel
        try:
            df = pd.read_excel(excel_path)
        except Exception as e:
            logger.error(f"Failed to read Excel: {e}")
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
            raise ValueError("Required nomenclature column not found")
        
        logger.info(f"Detected source column: {col_b}")
        
        # Подготовить столбцы для результатов без дублирования имен.
        # Это убирает ошибку вида: "cannot insert Артикул, already exists".
        if 'Цена' not in df.columns:
            df['Цена'] = pd.Series([None] * len(df), dtype='float64')
        else:
            df["Цена"] = pd.to_numeric(df["Цена"], errors="coerce").astype("float64")

        for text_col in ("Найденная номенклатура", "Артикул", "Ошибка сопоставления", "Причина отсутствия"):
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
            found_name = result.get("found_name") or MISSING_POSITION_TEXT
            df.at[idx, "Цена"] = result.get("price")
            df.at[idx, "Найденная номенклатура"] = found_name
            df.at[idx, "Артикул"] = result.get("article")
            df.at[idx, "Ошибка сопоставления"] = result.get("error")
            df.at[idx, "Причина отсутствия"] = result.get("reason") if found_name == MISSING_POSITION_TEXT else None

            if result.get("from_cache"):
                stats["from_cache"] += 1

            if found_name == MISSING_POSITION_TEXT:
                stats["not_found"] += 1
            else:
                stats["found"] += 1

            if not result.get("success", True):
                stats["errors"] += 1
                logger.warning(f"⚠️ [{idx + 1}] Ошибка: {result.get('error')}")
        
        # Сохранить результат
        if output_path is None:
            src = Path(excel_path)
            output_path = str(src.with_name(f"{src.stem}_matched{src.suffix}"))

        try:
            df.to_excel(output_path, index=False)
            logger.info(f"Result saved: {output_path}")
        except Exception as e:
            logger.error(f"Failed to save Excel: {e}")
            raise
        
        # Вывести статистику
        logger.info("\n" + "="*60)
        logger.info("PROCESSING STATS")
        logger.info("="*60)
        logger.info(f"Total rows:         {stats['total']}")
        logger.info(f"Matched:            {stats['found']}")
        logger.info(f"Not found:          {stats['not_found']}")
        logger.info(f"From cache:         {stats['from_cache']}")
        logger.info(f"Errors:             {stats['errors']}")
        logger.info(f"Success rate:       {stats['found']/stats['total']*100:.1f}%" if stats['total'] > 0 else "N/A")
        logger.info("="*60 + "\n")
        
        return df, stats


if __name__ == "__main__":
    # ÐŸÑ€Ð¸Ð¼ÐµÑ€ Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ð½Ð¸Ñ
    API_KEY = os.getenv('GEMINI_API_KEY')
    if not API_KEY:
        print("Set GEMINI_API_KEY environment variable")
        print("Windows: set GEMINI_API_KEY=your_key")
        print("Linux/Mac: export GEMINI_API_KEY=your_key")
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
    print("TEST MATCHING")
    print("="*60 + "\n")
    
    for query in test_queries:
        result = matcher.match(query)
        print(f"Query:      {query}")
        print(f"Found:      {result['found_name']}")
        print(f"Article:    {result['article']}")
        print(f"Price:      {result['price']}")
        print(f"Confidence: {result['similarity_score']}")
        print("-" * 60)
