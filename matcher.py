from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from catalog_search import (
    SEARCH_CATALOG_FILENAME,
    clean_text_value as shared_clean_text_value,
    classify_item_type as shared_classify_item_type,
    derive_branch_from_text as shared_derive_branch_from_text,
    extract_item_markers as shared_extract_item_markers,
    get_search_catalog_readiness,
    normalize_branch_path as shared_normalize_branch_path,
    normalize_catalog_branch_from_row as shared_normalize_catalog_branch_from_row,
    normalize_query_terms as shared_normalize_query_terms,
    normalize_text as shared_normalize_text,
    tokenize as shared_tokenize,
)
from catalog_merge import get_catalog_readiness
from catalog_schema import (
    CANONICAL_ARTICLE_COLUMN,
    CANONICAL_NAME_COLUMN,
    CANONICAL_PRICE_COLUMN,
    canonicalize_catalog_columns,
)
from config import (
    get_catalog_csv_path,
    get_matcher_cache_db_path,
    get_matcher_context_chunk_size,
    get_matcher_local_confidence_threshold,
    get_matcher_local_margin_threshold,
    get_matcher_max_context_chunks,
    get_matcher_models,
    get_matcher_parallel_requests,
    get_matcher_retrieval_candidates,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

MISSING_POSITION_TEXT = "Позиция отсутствует"
MATCH_MODE_EXACT = "exact"
MATCH_MODE_ANALOG = "analog"
BRANCH_PATH_SEPARATOR = " > "
TOP_BRANCH_COUNT = 3
DEFAULT_TAXONOMY_RULES_PATH = Path(__file__).with_name("taxonomy_rules.json")
DEFAULT_MATCH_PROMPT_TEMPLATE = (
    "Ты эксперт по технической номенклатуре.\n"
    "Запрос: {query}\n"
    "Контекст каталога:\n"
    "{catalog_context}\n"
    "Верни только JSON."
)
GROUP_TOKEN_STOPWORDS = {
    "и",
    "в",
    "во",
    "на",
    "для",
    "с",
    "со",
    "по",
    "из",
    "шт",
    "мм",
    "см",
    "м",
    "к",
    "за",
    "u",
    "the",
    "zero",
}
TERM_NORMALIZATION_ALIASES = {
    "patch cord": "патч корд",
    "patch-cord": "патч корд",
    "patchcord": "патч корд",
    "патч-корд": "патч корд",
    "патчкорд": "патч корд",
    "шнур коммутационный": "патч корд",
    "коммутационный шнур": "патч корд",
    "zero-u": "zero u",
    '19"': "19 inch",
    "19''": "19 inch",
}

DEFAULT_TAXONOMY_RULES: Dict[str, Any] = {
    "class_code_map": {},
    "class_name_map": {
        "шкафы телекоммуникационные": ["телеком", "шкафы"],
        "кабели пвх силовые без брони": ["электрика", "кабели", "силовые", "pvc", "без брони"],
        "кабели hf (безгалогеновые) силовые без брони": ["электрика", "кабели", "силовые", "hf", "без брони"],
        "провода монтажные установочные": ["электрика", "провода", "монтажные"],
        "провода бытовые": ["электрика", "провода", "бытовые"],
        "автоматические выключатели модульные": ["электрика", "автоматы", "модульные"],
        "автоматические выключатели в литом корпусе стационарные": ["электрика", "автоматы", "литой корпус"],
    },
    "keyword_routes": [
        {"patterns": ["pdu", "блок розеток"], "path": ["телеком", "питание", "pdu"], "weight": 4.0},
        {"patterns": ["zero u"], "path": ["телеком", "питание", "pdu", "zero u"], "weight": 5.0},
        {"patterns": ["патч панель", "патч-панель"], "path": ["телеком", "коммутация", "патч панели"], "weight": 4.5},
        {"patterns": ["патч корд", "patch cord"], "path": ["телеком", "кабели", "патч корды"], "weight": 4.5},
        {"patterns": ["органайзер"], "path": ["телеком", "аксессуары", "кабельные органайзеры"], "weight": 4.0},
        {"patterns": ["шкаф", "стойк"], "path": ["телеком", "шкафы"], "weight": 3.2},
        {"patterns": ["датчик"], "path": ["автоматика", "датчики"], "weight": 3.2},
        {"patterns": ["кабель", "utp", "ftp"], "path": ["электрика", "кабели"], "weight": 2.8},
        {"patterns": ["провод"], "path": ["электрика", "провода"], "weight": 2.8},
        {"patterns": ["автомат"], "path": ["электрика", "автоматы"], "weight": 3.5},
        {"patterns": ["розетка"], "path": ["электрика", "розетки"], "weight": 3.0},
        {"patterns": ["светильник"], "path": ["свет", "светильники"], "weight": 3.0},
    ],
    "synonyms": {
        "коммутационный шнур": "патч корд",
        "патч-корд": "патч корд",
        "патчкорд": "патч корд",
        "zero-u": "zero u",
        '19"': "19 inch",
        "19''": "19 inch",
        "cat 6": "cat6",
        "кат 6": "cat6",
        "cat 5e": "cat5e",
        "кат 5e": "cat5e",
    },
    "attribute_patterns": {
        "category": [
            {"regex": r"\bcat\s*6a?\b|\bкат\s*6a?\b", "value": "cat6"},
            {"regex": r"\bcat\s*5e\b|\bкат\s*5e\b", "value": "cat5e"},
        ],
        "rack_unit": [
            {"regex": r"\bzero\s*u\b", "value": "zero u"},
            {"regex": r"\b(\d+)\s*u\b", "group": 1},
        ],
        "rack_size": [
            {"regex": r"\b19\s*(?:inch|дюйм)\b", "value": "19 inch"},
        ],
    },
    "section_row_patterns": [
        r"^шкафы(?:\s+\S+){0,4}$",
        r"^кабели(?:\s+\S+){0,4}$",
        r"^коммутация(?:\s+\S+){0,4}$",
        r"^электрика(?:\s+\S+){0,4}$",
        r"^свет(?:\s+\S+){0,4}$",
        r"^датчики(?:\s+\S+){0,4}$",
    ],
    "branch_priorities": {
        "телеком > питание > pdu > zero u": 0.35,
        "телеком > питание > pdu": 0.25,
        "телеком > коммутация > патч панели": 0.3,
        "телеком > кабели > патч корды": 0.3,
    },
    "conflict_rules": [
        {"when": "zero_u", "penalize_patterns": ["1u"], "penalty": 0.18},
        {"when": "rack_1u", "penalize_patterns": ["zero u"], "penalty": 0.18},
        {"when": "category_cat6", "penalize_patterns": ["cat5e"], "penalty": 0.2},
        {"when": "category_cat5e", "penalize_patterns": ["cat6"], "penalty": 0.2},
    ],
}

try:
    from google import genai as genai_sdk
    from google.genai import types as genai_types

    GENAI_SDK_AVAILABLE = True
except ImportError:
    genai_sdk = None
    genai_types = None
    GENAI_SDK_AVAILABLE = False

try:
    import google.generativeai as legacy_genai_sdk

    LEGACY_GENAI_AVAILABLE = True
except ImportError:
    legacy_genai_sdk = None
    LEGACY_GENAI_AVAILABLE = False


def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


class ReMoMatcher:
    """Matcher for mapping free-form commercial proposal rows to supplier catalog items."""

    def __init__(
        self,
        gemini_api_key: str,
        db_csv_path: str,
        cache_db: str = "matcher_cache.db",
        parallel_requests: int | None = None,
        catalog_sample_items: int = 500,
        match_mode: str = MATCH_MODE_EXACT,
    ):
        self.api_key = gemini_api_key
        self.db_csv_path = self._resolve_catalog_csv_path(db_csv_path)
        self.cache_db = str(get_matcher_cache_db_path(cache_db))
        self.catalog: pd.DataFrame | None = None
        self.catalog_dict: Dict[str, Dict[str, Any]] = {}
        self.catalog_normalized_dict: Dict[str, Dict[str, Any]] = {}
        self.catalog_items: List[Dict[str, Any]] = []
        self.token_index: Dict[str, List[Dict[str, Any]]] = {}
        self.group_index: Dict[str, List[Dict[str, Any]]] = {}
        self.token_idf: Dict[str, float] = {}
        self.branch_index: Dict[str, List[Dict[str, Any]]] = {}
        self.branch_prefix_index: Dict[str, List[Dict[str, Any]]] = {}
        self.branch_token_index: Dict[str, List[str]] = {}
        self.class_code_index: Dict[str, str] = {}
        self.branch_priority_scores: Dict[str, float] = {}
        self.catalog_text: str = ""
        self.backend: str | None = None
        self.client = None
        self.legacy_genai = None
        self.model_name: str | None = None
        self.parallel_requests = min(10, max(1, int(parallel_requests or get_matcher_parallel_requests())))
        self.catalog_sample_items = max(50, int(catalog_sample_items))
        self.match_mode = self._sanitize_match_mode(match_mode)
        self.context_chunk_size = get_matcher_context_chunk_size()
        self.max_context_chunks = get_matcher_max_context_chunks()
        self.retrieval_candidates_limit = get_matcher_retrieval_candidates()
        self.local_confidence_threshold = get_matcher_local_confidence_threshold()
        self.local_margin_threshold = get_matcher_local_margin_threshold()
        self.prompt_template = self._load_prompt_template()
        self.taxonomy_rules = self._load_taxonomy_rules()

        if GENAI_SDK_AVAILABLE:
            try:
                self.client = genai_sdk.Client(api_key=self.api_key)
                self.backend = "google-genai"
                logger.info("Gemini backend: google-genai")
            except Exception as exc:
                logger.warning("Failed to initialize google-genai: %s", exc)

        if self.backend is None and LEGACY_GENAI_AVAILABLE:
            try:
                legacy_genai_sdk.configure(api_key=self.api_key)
                self.legacy_genai = legacy_genai_sdk
                self.backend = "google-generativeai"
                logger.info("Gemini backend: google-generativeai")
            except Exception as exc:
                logger.warning("Failed to initialize google-generativeai: %s", exc)

        if self.backend is None:
            logger.warning("Gemini SDK is unavailable; matcher will fall back to local-only routing when possible.")

        self._init_cache_db()
        self._load_catalog()
        logger.info("ReMoMatcher initialized")

    def _resolve_catalog_csv_path(self, db_csv_path: str) -> str:
        source_path = Path(str(db_csv_path))
        search_readiness = get_search_catalog_readiness(source_path)
        if source_path.is_dir() or source_path.name == SEARCH_CATALOG_FILENAME:
            if search_readiness.state == "ready":
                logger.info("📄 Matcher using prepared search catalog: %s", search_readiness.search_path)
                return str(search_readiness.search_path)
            merged_readiness = get_catalog_readiness(source_path)
            if merged_readiness.state == "ready":
                logger.info(
                    "📄 Matcher falling back to merged catalog: %s reason=%s",
                    merged_readiness.merged_path,
                    search_readiness.reason or "search catalog is not ready",
                )
                return str(merged_readiness.merged_path)
            if merged_readiness.state == "missing":
                raise FileNotFoundError(
                    merged_readiness.reason or f"Merged catalog not prepared: {merged_readiness.merged_path}"
                )
            if merged_readiness.state == "stale":
                raise RuntimeError(
                    merged_readiness.reason or f"Merged catalog is stale: {merged_readiness.merged_path}"
                )
            raise RuntimeError(merged_readiness.reason or f"Catalog is not ready: {source_path}")
        readiness = get_catalog_readiness(source_path)
        if readiness.state == "ready":
            logger.info("📄 Matcher using prepared merged catalog: %s", readiness.merged_path)
            return str(readiness.merged_path)
        if readiness.state == "missing":
            raise FileNotFoundError(
                readiness.reason or f"Merged catalog not prepared: {readiness.merged_path}"
            )
        if readiness.state == "stale":
            raise RuntimeError(
                readiness.reason or f"Merged catalog is stale: {readiness.merged_path}"
            )
        raise RuntimeError(readiness.reason or f"Catalog is not ready: {source_path}")

    def _sanitize_match_mode(self, value: str | None) -> str:
        mode = str(value or "").strip().lower()
        if mode in {MATCH_MODE_EXACT, MATCH_MODE_ANALOG}:
            return mode
        return MATCH_MODE_EXACT

    def _load_taxonomy_rules(self) -> Dict[str, Any]:
        path_raw = os.getenv("REMO_TAXONOMY_RULES_PATH")
        path = Path(path_raw) if path_raw else DEFAULT_TAXONOMY_RULES_PATH
        rules = DEFAULT_TAXONOMY_RULES
        if not path.exists():
            return rules
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return _merge_dicts(DEFAULT_TAXONOMY_RULES, loaded)
        except Exception as exc:
            logger.warning("Failed to load taxonomy rules from %s: %s", path, exc)
        return rules

    def _load_prompt_template(self) -> str:
        path_raw = os.getenv("REMO_MATCH_PROMPT_TEMPLATE_PATH")
        if not path_raw:
            return DEFAULT_MATCH_PROMPT_TEMPLATE

        path = Path(path_raw)
        if not path.exists():
            logger.warning("Prompt template not found at %s; using default template", path)
            return DEFAULT_MATCH_PROMPT_TEMPLATE

        try:
            custom_template = path.read_text(encoding="utf-8").strip()
            if "{catalog_context}" not in custom_template or "{query}" not in custom_template:
                logger.warning(
                    "Custom prompt template misses required placeholders {catalog_context}/{query}; using default",
                )
                return DEFAULT_MATCH_PROMPT_TEMPLATE
            return custom_template
        except Exception as exc:
            logger.warning("Failed to read custom prompt template: %s; using default", exc)
            return DEFAULT_MATCH_PROMPT_TEMPLATE

    def _build_match_prompt(self, query: str, catalog_context: str) -> str:
        template = getattr(self, "prompt_template", DEFAULT_MATCH_PROMPT_TEMPLATE)
        return template.format(query=query, catalog_context=catalog_context)

    @staticmethod
    def _clean_text_value(value: object) -> str:
        return shared_clean_text_value(value)

    @staticmethod
    def _parse_price_value(value: object) -> Optional[float]:
        if pd.isna(value):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
        cleaned = "".join(ch for ch in cleaned if ch.isdigit() or ch in {".", "-"})
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _normalize_query_terms(self, text: str) -> str:
        return shared_normalize_query_terms(text, synonyms=getattr(self, "taxonomy_rules", {}).get("synonyms", {}))

    def _normalize_text(self, text: str) -> str:
        return shared_normalize_text(text, synonyms=getattr(self, "taxonomy_rules", {}).get("synonyms", {}))

    def _tokenize(self, text: str) -> List[str]:
        return shared_tokenize(
            text,
            synonyms=getattr(self, "taxonomy_rules", {}).get("synonyms", {}),
            stopwords=GROUP_TOKEN_STOPWORDS,
        )

    def _classify_item_type(self, text: str) -> str:
        return shared_classify_item_type(text, synonyms=getattr(self, "taxonomy_rules", {}).get("synonyms", {}))

    def _is_disallowed_category_substitution(self, query: str, candidate_name: str) -> bool:
        query_type = self._classify_item_type(query)
        candidate_type = self._classify_item_type(candidate_name)
        if query_type == "patch_cord" and candidate_type == "bulk_twisted_pair":
            return True
        if getattr(self, "match_mode", MATCH_MODE_EXACT) == MATCH_MODE_EXACT:
            if query_type != "other" and candidate_type != "other" and query_type != candidate_type:
                return True
        return False

    def _init_cache_db(self) -> None:
        conn = sqlite3.connect(self.cache_db)
        cursor = conn.cursor()
        cursor.execute(
            """
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
            """,
        )
        cursor.execute(
            """
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
            """,
        )
        conn.commit()
        conn.close()

    def _normalize_branch_path(self, segments: Iterable[str]) -> str:
        return shared_normalize_branch_path(segments)

    def _derive_branch_from_text(self, *texts: str) -> str:
        return shared_derive_branch_from_text(
            *texts,
            keyword_routes=getattr(self, "taxonomy_rules", {}).get("keyword_routes", []),
            synonyms=getattr(self, "taxonomy_rules", {}).get("synonyms", {}),
        )

    def _normalize_catalog_branch(self, row: pd.Series | Dict[str, Any]) -> str:
        return shared_normalize_catalog_branch_from_row(row, taxonomy_rules=getattr(self, "taxonomy_rules", {}))

    def _build_branch_index(self) -> None:
        self.branch_index = defaultdict(list)
        self.branch_prefix_index = defaultdict(list)
        self.branch_token_index = defaultdict(list)
        self.class_code_index = {}
        self.branch_priority_scores = {}

        seen_branch_tokens: Dict[str, set[str]] = defaultdict(set)
        for item in self.catalog_items:
            branch_path = item.get("branch_path") or "прочее"
            self.branch_index[branch_path].append(item)

            segments = [segment.strip() for segment in branch_path.split(BRANCH_PATH_SEPARATOR) if segment.strip()]
            for idx in range(1, len(segments) + 1):
                prefix = BRANCH_PATH_SEPARATOR.join(segments[:idx])
                self.branch_prefix_index[prefix].append(item)

            tokens = set(item.get("tokens", []))
            tokens.update(self._tokenize(branch_path))
            tokens.update(self._tokenize(item.get("class_name", "")))
            tokens.update(self._tokenize(item.get("item_type", "")))
            for token in tokens:
                if branch_path not in seen_branch_tokens[token]:
                    self.branch_token_index[token].append(branch_path)
                    seen_branch_tokens[token].add(branch_path)

            class_code = self._clean_text_value(item.get("class_code"))
            if class_code and class_code not in self.class_code_index:
                self.class_code_index[class_code] = branch_path

        priority_rules = getattr(self, "taxonomy_rules", {}).get("branch_priorities", {})
        self.branch_priority_scores = {
            str(key).strip().lower(): float(value)
            for key, value in priority_rules.items()
        }

        self.branch_index = dict(self.branch_index)
        self.branch_prefix_index = dict(self.branch_prefix_index)
        self.branch_token_index = dict(self.branch_token_index)

    def _load_catalog(self) -> None:
        logger.info("Loading catalog from %s", self.db_csv_path)
        self.catalog = pd.read_csv(self.db_csv_path, sep=";", encoding="utf-8", low_memory=False)
        self.catalog = canonicalize_catalog_columns(self.catalog, create_missing=True)

        if CANONICAL_NAME_COLUMN not in self.catalog.columns:
            raise ValueError("Catalog name column cannot be resolved")
        if self.catalog[CANONICAL_NAME_COLUMN].fillna("").astype(str).str.strip().eq("").all():
            raise ValueError("Catalog name column cannot be resolved")

        self.catalog_dict = {}
        self.catalog_normalized_dict = {}
        self.catalog_items = []
        token_to_items: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        token_doc_frequency: Counter[str] = Counter()

        for idx, row in self.catalog.iterrows():
            name = self._clean_text_value(row.get(CANONICAL_NAME_COLUMN))
            if not name:
                continue

            article = self._clean_text_value(row.get(CANONICAL_ARTICLE_COLUMN))
            price = self._parse_price_value(row.get(CANONICAL_PRICE_COLUMN))
            item_type = self._clean_text_value(row.get("Тип изделия"))
            class_name = self._clean_text_value(row.get("Название класса"))
            combined_text = " ".join(filter(None, [name, item_type, class_name]))
            normalized_name = self._clean_text_value(row.get("search_normalized_name")) or self._normalize_text(name)

            tokens: List[str] = []
            precomputed_tokens_raw = self._clean_text_value(row.get("search_tokens_json"))
            if precomputed_tokens_raw:
                try:
                    loaded_tokens = json.loads(precomputed_tokens_raw)
                    if isinstance(loaded_tokens, list):
                        tokens = sorted(
                            {
                                self._clean_text_value(token)
                                for token in loaded_tokens
                                if self._clean_text_value(token)
                            }
                        )
                except (TypeError, ValueError, json.JSONDecodeError):
                    tokens = []
            if not tokens:
                tokens = sorted(set(self._tokenize(combined_text or normalized_name)))

            branch_path = self._clean_text_value(row.get("search_branch_path")) or self._normalize_catalog_branch(row)
            branch_leaf = self._clean_text_value(row.get("search_branch_leaf")) or branch_path.split(BRANCH_PATH_SEPARATOR)[-1]
            entity_type = self._clean_text_value(row.get("search_entity_type")) or self._classify_item_type(combined_text)

            item_markers: Dict[str, Any] = {}
            precomputed_markers_raw = self._clean_text_value(row.get("search_item_markers_json"))
            if precomputed_markers_raw:
                try:
                    loaded_markers = json.loads(precomputed_markers_raw)
                    if isinstance(loaded_markers, dict):
                        item_markers = {
                            self._clean_text_value(key): self._clean_text_value(value)
                            for key, value in loaded_markers.items()
                            if self._clean_text_value(key)
                        }
                except (TypeError, ValueError, json.JSONDecodeError):
                    item_markers = {}
            if not item_markers:
                item_markers = shared_extract_item_markers(
                    combined_text,
                    attribute_patterns=getattr(self, "taxonomy_rules", {}).get("attribute_patterns", {}),
                    synonyms=getattr(self, "taxonomy_rules", {}).get("synonyms", {}),
                )

            item = {
                "name": name,
                "name_lc": name.lower(),
                "normalized_name": normalized_name,
                "article": article,
                "price": price,
                "row_idx": int(idx),
                "tokens": tokens,
                "branch_path": branch_path,
                "branch_leaf": branch_leaf,
                "class_name": class_name,
                "class_code": self._clean_text_value(row.get("Код класса")),
                "item_type": item_type,
                "cable_execution": self._clean_text_value(row.get("Тип исполнения кабельного изделия")),
                "manufacturer": self._clean_text_value(row.get("Производитель")),
                "entity_type": entity_type,
                "item_markers": item_markers,
            }

            self.catalog_dict.setdefault(item["name_lc"], item)
            if normalized_name and normalized_name not in self.catalog_normalized_dict:
                self.catalog_normalized_dict[normalized_name] = item

            self.catalog_items.append(item)
            for token in tokens:
                token_to_items[token].append(item)
            for token in set(tokens):
                token_doc_frequency[token] += 1

        total_items = max(1, len(self.catalog_items))
        self.token_index = dict(token_to_items)
        self.group_index = {
            token: items
            for token, items in token_to_items.items()
            if len(items) >= 3
        }
        self.token_idf = {
            token: math.log((1 + total_items) / (1 + freq)) + 1.0
            for token, freq in token_doc_frequency.items()
        }
        self._build_branch_index()
        self._prepare_catalog_text(max_items=int(getattr(self, "catalog_sample_items", 500)))
        logger.info("Loaded catalog items: %s", len(self.catalog_items))

    def _prepare_catalog_text(self, max_items: int = 500) -> None:
        catalog = getattr(self, "catalog", None)
        if catalog is None or catalog.empty:
            self.catalog_text = ""
            return
        limit = min(max_items, len(catalog))
        sample = catalog.head(limit)
        lines = []
        for _, row in sample.iterrows():
            lines.append(
                f"• {row.get(CANONICAL_NAME_COLUMN, 'N/A')} | Артикул: {row.get(CANONICAL_ARTICLE_COLUMN, 'N/A')} | "
                f"Цена: {row.get(CANONICAL_PRICE_COLUMN, 'N/A')}"
            )
        self.catalog_text = "\n".join(lines[:300])

    def _rank_group_candidates(self, query: str) -> List[Dict[str, Any]]:
        query_tokens = self._tokenize(query)
        group_index = getattr(self, "group_index", {}) or {}
        if not query_tokens or not group_index:
            return []

        candidate_stats: Dict[str, Dict[str, Any]] = {}
        retrieval_limit = max(1, int(getattr(self, "retrieval_candidates_limit", 1200)))
        for token in set(query_tokens):
            token_weight = getattr(self, "token_idf", {}).get(token, 1.0)
            for item in group_index.get(token, [])[:retrieval_limit]:
                key = item.get("name_lc") or item.get("name", "").lower()
                entry = candidate_stats.setdefault(
                    key,
                    {"item": item, "overlap_count": 0, "idf_score": 0.0},
                )
                entry["overlap_count"] += 1
                entry["idf_score"] += token_weight

        ranked = sorted(
            candidate_stats.values(),
            key=lambda entry: (
                entry["idf_score"],
                entry["overlap_count"],
                -int(entry["item"].get("row_idx", 0)),
            ),
            reverse=True,
        )
        return [entry["item"] for entry in ranked[:retrieval_limit]]

    def _build_context_for_query(self, query: str, max_lines: int = 300) -> str:
        ranked_items = self._rank_group_candidates(query)
        if not ranked_items:
            return getattr(self, "catalog_text", "")
        lines = [
            f"• {item.get('name', 'N/A')} | Артикул: {item.get('article', 'N/A')} | Цена: {item.get('price', 'N/A')}"
            for item in ranked_items[:max_lines]
        ]
        return "\n".join(lines) if lines else getattr(self, "catalog_text", "")

    def _build_context_chunks(
        self,
        query: str,
        chunk_size: int | None = None,
        max_chunks: int | None = None,
    ) -> List[str]:
        ranked_items = self._rank_group_candidates(query)
        if not ranked_items:
            fallback = getattr(self, "catalog_text", "")
            return [fallback] if fallback else []

        chunk_size = max(50, int(chunk_size or getattr(self, "context_chunk_size", 300)))
        max_chunks = max(1, int(max_chunks or getattr(self, "max_context_chunks", 4)))
        chunks: List[str] = []
        for offset in range(0, len(ranked_items), chunk_size):
            if len(chunks) >= max_chunks:
                break
            chunk_items = ranked_items[offset : offset + chunk_size]
            chunk_text = "\n".join(
                f"• {item.get('name', 'N/A')} | Артикул: {item.get('article', 'N/A')} | Цена: {item.get('price', 'N/A')}"
                for item in chunk_items
            )
            if chunk_text.strip():
                chunks.append(chunk_text)
        return chunks or [getattr(self, "catalog_text", "")]

    def _hash_query(self, query: str) -> str:
        normalized = self._normalize_text(query)
        value = normalized if normalized else str(query).lower()
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    def _rank_candidates(
        self,
        query: str,
        limit: int = 40,
        candidate_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Tuple[float, Dict[str, Any]]]:
        normalized_query = self._normalize_text(query)
        query_tokens = self._tokenize(normalized_query)
        pool = candidate_pool if candidate_pool is not None else getattr(self, "catalog_items", [])
        if not pool:
            return []

        if candidate_pool is None:
            candidate_map: Dict[str, Dict[str, Any]] = {}
            token_index = getattr(self, "token_index", {}) or {}
            for token in query_tokens:
                for item in token_index.get(token, []):
                    candidate_map.setdefault(item.get("name_lc", item["name"].lower()), item)
            if not candidate_map:
                fallback = pool[: min(800, len(pool))]
                candidate_map = {item.get("name_lc", item["name"].lower()): item for item in fallback}
            items = list(candidate_map.values())
        else:
            items = pool

        query_set = set(query_tokens)
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for item in items:
            candidate_name = item.get("normalized_name") or self._normalize_text(item.get("name", ""))
            candidate_tokens = set(item.get("tokens") or self._tokenize(candidate_name))
            if not candidate_tokens:
                continue
            overlap = len(query_set & candidate_tokens)
            union = len(query_set | candidate_tokens)
            jaccard = overlap / union if union else 0.0
            ratio = SequenceMatcher(None, normalized_query, candidate_name).ratio()
            score = (jaccard * 0.75) + (ratio * 0.25)
            scored.append((float(score), item))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [(score, item) for score, item in scored[:limit] if score > 0]

    def _select_candidates(
        self,
        query: str,
        limit: int = 40,
        candidate_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        return [item for score, item in self._rank_candidates(query, limit=limit, candidate_pool=candidate_pool)]

    def _try_local_semantic_match(
        self,
        query: str,
        candidate_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        ranked = self._rank_candidates(query, limit=2, candidate_pool=candidate_pool)
        if not ranked:
            return None

        best_score, best_item = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        margin = best_score - second_score

        if best_score < getattr(self, "local_confidence_threshold", 0.92):
            return None
        if margin < getattr(self, "local_margin_threshold", 0.08):
            return None
        if self._is_disallowed_category_substitution(query, best_item.get("name", "")):
            return None
        result = self._build_result_from_item(best_item, float(best_score), "local_semantic_match", False, "", "")
        result["_matched_item"] = best_item
        return result

    def _build_catalog_context(self, candidates: List[Dict[str, Any]], max_lines: int = 60) -> str:
        if not candidates:
            return getattr(self, "catalog_text", "")
        lines = []
        for item in candidates[:max_lines]:
            lines.append(
                f"• {item.get('name', 'N/A')} | Артикул: {item.get('article', 'N/A')} | Цена: {item.get('price', 'N/A')}"
            )
        return "\n".join(lines)

    def _get_from_cache(self, query: str) -> Optional[Dict[str, Any]]:
        query_hash = self._hash_query(query)
        try:
            conn = sqlite3.connect(self.cache_db)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT found_name, price, article, similarity_score FROM match_cache WHERE query_hash = ?",
                (query_hash,),
            )
            result = cursor.fetchone()
            conn.close()
        except Exception as exc:
            logger.warning("Cache read error: %s", exc)
            return None

        if not result:
            return None

        found_name = result[0] or MISSING_POSITION_TEXT
        if found_name == MISSING_POSITION_TEXT:
            return None

        return {
            "found_name": found_name,
            "price": result[1],
            "article": result[2],
            "similarity_score": result[3] or 0.0,
            "from_cache": True,
            "success": True,
            "error": None,
            "reason": "",
            "category_path": None,
            "confidence_level": "high",
            "requires_review": "нет",
            "alternatives": "",
            "resolution_source": "cache",
        }

    def _save_to_cache(
        self,
        query: str,
        found_name: str,
        price: Optional[float],
        article: str,
        similarity_score: float,
        raw_response: str,
    ) -> None:
        query_hash = self._hash_query(query)
        try:
            conn = sqlite3.connect(self.cache_db)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO match_cache
                (query_hash, original_query, found_name, price, article, similarity_score, created_at, gemini_raw_response)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query_hash,
                    query,
                    found_name,
                    price,
                    article,
                    similarity_score,
                    datetime.now(),
                    raw_response,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("Cache write error: %s", exc)

    def _detect_query_row_type(self, query: str) -> str:
        text = self._clean_text_value(query)
        if not text:
            return "empty"
        normalized = self._normalize_text(text)
        patterns = getattr(self, "taxonomy_rules", {}).get("section_row_patterns", [])
        for pattern in patterns:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return "section"
        tokens = self._tokenize(normalized)
        if len(tokens) <= 4 and not re.search(r"\d", normalized):
            for token in ("шкафы", "кабели", "коммутация", "электрика", "датчики", "свет"):
                if normalized.startswith(token):
                    return "section"
        return "item"

    def _extract_query_features(self, query: str) -> Dict[str, Any]:
        original = self._clean_text_value(query)
        normalized = self._normalize_text(original)
        tokens = self._tokenize(normalized)
        features: Dict[str, Any] = {
            "original_text": original,
            "normalized_text": normalized,
            "tokens": tokens,
            "row_type": self._detect_query_row_type(original),
            "entity_type": self._classify_item_type(original),
            "attributes": {},
        }

        rules = getattr(self, "taxonomy_rules", {}).get("attribute_patterns", {})
        for feature_name, matchers in rules.items():
            for matcher in matchers:
                regex = matcher.get("regex")
                if not regex:
                    continue
                match = re.search(regex, normalized, flags=re.IGNORECASE)
                if not match:
                    continue
                value = match.group(int(matcher["group"])) if "group" in matcher else matcher.get("value")
                if value:
                    features["attributes"][feature_name] = str(value).lower()
                    break

        length_match = re.search(r"(\d+(?:[.,]\d+)?)\s*м\b", normalized)
        if length_match:
            features["attributes"]["length_m"] = length_match.group(1).replace(",", ".")

        current_match = re.search(r"(\d+(?:[.,]\d+)?)\s*а\b", normalized)
        if current_match:
            features["attributes"]["current_a"] = current_match.group(1).replace(",", ".")

        if "zero u" in normalized:
            features["attributes"]["zero_u"] = "yes"
        if features["attributes"].get("rack_unit") == "1":
            features["attributes"]["rack_1u"] = "yes"
        if "19 inch" in normalized:
            features["attributes"]["rack_size"] = "19 inch"

        branch_hint = self._derive_branch_from_text(original)
        if branch_hint and branch_hint != "прочее":
            features["branch_hint"] = branch_hint
        return features

    def _rank_branches(self, query_features: Dict[str, Any]) -> List[Dict[str, Any]]:
        scores: Dict[str, float] = defaultdict(float)
        normalized = query_features.get("normalized_text", "")
        tokens = query_features.get("tokens", [])
        branch_hint = query_features.get("branch_hint")

        for rule in getattr(self, "taxonomy_rules", {}).get("keyword_routes", []):
            path = self._normalize_branch_path(rule.get("path", []))
            if not path:
                continue
            weight = float(rule.get("weight", 1.0))
            for pattern in rule.get("patterns", []):
                pattern_norm = self._normalize_text(pattern)
                if pattern_norm and pattern_norm in normalized:
                    scores[path] += weight

        if branch_hint:
            scores[branch_hint] += 2.5

        branch_token_index = getattr(self, "branch_token_index", {}) or {}
        token_idf = getattr(self, "token_idf", {}) or {}
        for token in set(tokens):
            for branch in branch_token_index.get(token, []):
                scores[branch] += 0.45 * float(token_idf.get(token, 1.0))

        entity_type = query_features.get("entity_type")
        for branch in getattr(self, "branch_index", {}) or {}:
            branch_norm = self._normalize_text(branch)
            if entity_type == "pdu" and "pdu" in branch_norm:
                scores[branch] += 1.2
            elif entity_type == "rack" and "шкаф" in branch_norm:
                scores[branch] += 1.0
            elif entity_type == "patch_panel" and "патч панел" in branch_norm:
                scores[branch] += 1.2
            elif entity_type == "patch_cord" and "патч корд" in branch_norm:
                scores[branch] += 1.2
            elif entity_type == "cable" and "кабел" in branch_norm:
                scores[branch] += 0.8
            elif entity_type == "wire" and "провод" in branch_norm:
                scores[branch] += 0.8

        if query_features.get("attributes", {}).get("zero_u"):
            for branch in getattr(self, "branch_index", {}) or {}:
                if "zero u" in self._normalize_text(branch):
                    scores[branch] += 2.5

        for branch, boost in getattr(self, "branch_priority_scores", {}).items():
            scores[branch] += float(boost)

        if not scores:
            counts = Counter(item.get("branch_path", "прочее") for item in getattr(self, "catalog_items", []))
            return [{"path": path, "score": float(count)} for path, count in counts.most_common(TOP_BRANCH_COUNT)]

        ranked = sorted(
            scores.items(),
            key=lambda pair: (pair[1], len(getattr(self, "branch_prefix_index", {}).get(pair[0], []))),
            reverse=True,
        )
        return [{"path": path, "score": float(score)} for path, score in ranked[:TOP_BRANCH_COUNT]]

    def _collect_branch_candidates(self, branches: List[Any], limit: int | None = None) -> List[Dict[str, Any]]:
        limit = max(1, int(limit or getattr(self, "retrieval_candidates_limit", 3000)))
        prefix_index = getattr(self, "branch_prefix_index", {}) or {}
        exact_index = getattr(self, "branch_index", {}) or {}
        branch_paths: List[str] = []
        for branch in branches:
            if isinstance(branch, dict):
                path = str(branch.get("path") or "").strip()
            else:
                path = str(branch or "").strip()
            if path:
                branch_paths.append(path)

        candidates: List[Dict[str, Any]] = []
        seen: set[int] = set()
        for path in branch_paths:
            pool = prefix_index.get(path) or exact_index.get(path) or []
            for item in pool:
                row_idx = int(item.get("row_idx", -1))
                if row_idx in seen:
                    continue
                candidates.append(item)
                seen.add(row_idx)
                if len(candidates) >= limit:
                    return candidates
        return candidates

    def _branch_match_bonus(self, branch_scores: Dict[str, float], item_branch: str) -> float:
        if not branch_scores:
            return 0.0
        if item_branch in branch_scores:
            return min(0.22, branch_scores[item_branch] * 0.04)
        for branch_path, score in branch_scores.items():
            if item_branch.startswith(branch_path):
                return min(0.18, score * 0.03)
        return 0.0

    def _apply_attribute_score(self, query_features: Dict[str, Any], item: Dict[str, Any], base_score: float) -> float:
        score = base_score
        normalized_name = item.get("normalized_name") or self._normalize_text(item.get("name", ""))
        branch_path = item.get("branch_path", "")
        attributes = query_features.get("attributes", {})

        if query_features.get("entity_type") == item.get("entity_type"):
            score += 0.08

        category = attributes.get("category")
        if category:
            if category in normalized_name or category in self._normalize_text(branch_path):
                score += 0.12
            else:
                score -= 0.18

        rack_unit = attributes.get("rack_unit")
        if rack_unit:
            if rack_unit == "zero u":
                if "zero u" in normalized_name:
                    score += 0.14
                elif "1u" in normalized_name:
                    score -= 0.18
            elif f"{rack_unit}u" in normalized_name.replace(" ", ""):
                score += 0.12

        if attributes.get("rack_size") == "19 inch":
            if "19 inch" in normalized_name:
                score += 0.06
            elif "19" in item.get("name", ""):
                score += 0.03

        length_m = attributes.get("length_m")
        if length_m and length_m in normalized_name.replace(",", "."):
            score += 0.06

        current_a = attributes.get("current_a")
        if current_a and current_a in normalized_name.replace(",", "."):
            score += 0.05

        if self._is_disallowed_category_substitution(query_features.get("original_text", ""), item.get("name", "")):
            score -= 0.35

        for conflict in getattr(self, "taxonomy_rules", {}).get("conflict_rules", []):
            marker = conflict.get("when")
            patterns = conflict.get("penalize_patterns", [])
            penalty = float(conflict.get("penalty", 0.0))
            if marker == "zero_u" and attributes.get("zero_u") and any(pat in normalized_name for pat in patterns):
                score -= penalty
            elif marker == "rack_1u" and attributes.get("rack_1u") and any(pat in normalized_name for pat in patterns):
                score -= penalty
            elif marker == "category_cat6" and attributes.get("category") == "cat6" and any(pat in normalized_name for pat in patterns):
                score -= penalty
            elif marker == "category_cat5e" and attributes.get("category") == "cat5e" and any(pat in normalized_name for pat in patterns):
                score -= penalty

        return max(0.0, min(0.999, score))

    def _score_candidates_locally(self, query_features: Dict[str, Any], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        ranked = self._rank_candidates(
            query_features.get("original_text", ""),
            limit=max(40, min(len(candidates), 80)),
            candidate_pool=candidates,
        )
        if not ranked:
            return []

        branch_scores = {
            entry["path"]: float(entry["score"])
            for entry in query_features.get("ranked_branches", [])
            if isinstance(entry, dict) and entry.get("path")
        }
        scored_entries: List[Dict[str, Any]] = []
        for lexical_score, item in ranked:
            score = lexical_score
            score += self._branch_match_bonus(branch_scores, item.get("branch_path", ""))
            score = self._apply_attribute_score(query_features, item, score)
            scored_entries.append({"item": item, "score": float(score), "lexical_score": float(lexical_score)})

        scored_entries.sort(
            key=lambda entry: (entry["score"], entry["lexical_score"], -int(entry["item"].get("row_idx", 0))),
            reverse=True,
        )
        return scored_entries

    def _confidence_level_from_score(self, score: float, requires_review: bool) -> str:
        if requires_review:
            return "medium" if score >= 0.8 else "low"
        if score >= 0.92:
            return "high"
        if score >= 0.75:
            return "medium"
        return "low"

    def _format_alternatives(self, scored_entries: List[Dict[str, Any]], skip_first: bool = False, limit: int = 3) -> str:
        if not scored_entries:
            return ""
        rows = scored_entries[1:] if skip_first else scored_entries
        parts = []
        for entry in rows[:limit]:
            item = entry["item"]
            article = self._clean_text_value(item.get("article"))
            article_suffix = f" [{article}]" if article else ""
            parts.append(f"{item.get('name', 'N/A')}{article_suffix}")
        return " | ".join(parts)

    def _build_result_from_item(
        self,
        item: Dict[str, Any],
        score: float,
        source: str,
        requires_review: bool,
        alternatives: str,
        reason: str,
    ) -> Dict[str, Any]:
        return {
            "found_name": item.get("name") or MISSING_POSITION_TEXT,
            "price": item.get("price"),
            "article": item.get("article") or None,
            "similarity_score": float(score),
            "from_cache": False,
            "success": True,
            "error": None,
            "reason": reason,
            "category_path": item.get("branch_path"),
            "confidence_level": self._confidence_level_from_score(score, requires_review),
            "requires_review": "да" if requires_review else "нет",
            "alternatives": alternatives,
            "resolution_source": source,
        }

    def _build_missing_result(self, query: str, reason: str, error: str | None = None, alternatives: str = "") -> Dict[str, Any]:
        return {
            "found_name": MISSING_POSITION_TEXT,
            "price": None,
            "article": None,
            "similarity_score": 0.0,
            "from_cache": False,
            "success": error is None,
            "error": error,
            "reason": reason or f"Позиция '{query}' не найдена",
            "category_path": None,
            "confidence_level": "low",
            "requires_review": "да",
            "alternatives": alternatives,
            "resolution_source": "unresolved",
        }

    def _candidate_models(self) -> List[str]:
        preferred = [getattr(self, "model_name", None), *get_matcher_models()]
        result: List[str] = []
        seen: set[str] = set()
        for name in preferred:
            model_name = str(name or "").strip()
            if not model_name or model_name in seen:
                continue
            seen.add(model_name)
            result.append(model_name)
        return result

    def _generate_gemini_text(self, prompt: str, model_name: str) -> str:
        if self.backend == "google-genai" and self.client is not None:
            request_kwargs: Dict[str, Any] = {"model": model_name, "contents": prompt}
            if genai_types is not None:
                request_kwargs["config"] = genai_types.GenerateContentConfig(
                    automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True),
                    tool_config=genai_types.ToolConfig(
                        function_calling_config=genai_types.FunctionCallingConfig(mode="NONE"),
                    ),
                )
            response = self.client.models.generate_content(**request_kwargs)
            return (getattr(response, "text", None) or "").strip()

        if self.backend == "google-generativeai" and self.legacy_genai is not None:
            model = self.legacy_genai.GenerativeModel(model_name)
            response = model.generate_content(prompt, stream=False)
            return (response.text or "").strip()

        raise RuntimeError("Gemini backend is not initialized")

    def _build_narrow_candidate_chunks(
        self,
        branches: List[str],
        candidates: List[Dict[str, Any]],
        query_features: Dict[str, Any] | None = None,
    ) -> List[str]:
        if not candidates:
            return []
        chunk_size = 8
        chunks: List[str] = []
        for offset in range(0, len(candidates), chunk_size):
            chunk = candidates[offset : offset + chunk_size]
            lines = []
            if branches:
                lines.append("Вероятные ветки: " + " | ".join(branches))
            if query_features:
                attrs = query_features.get("attributes", {})
                if attrs:
                    parts = [f"{key}={value}" for key, value in attrs.items()]
                    lines.append("Признаки запроса: " + ", ".join(parts))
            for idx, item in enumerate(chunk, start=1):
                lines.append(
                    f"{idx}. {item.get('name', 'N/A')} | Артикул: {item.get('article', 'N/A')} | "
                    f"Цена: {item.get('price', 'N/A')} | Категория: {item.get('branch_path', 'N/A')}"
                )
            chunks.append("\n".join(lines))
            if len(chunks) >= max(1, int(getattr(self, "max_context_chunks", 3))):
                break
        return chunks

    def _parse_gemini_result(
        self,
        query: str,
        raw_text: str,
        candidate_lookup: Dict[str, Dict[str, Any]],
        article_lookup: Dict[str, Dict[str, Any]],
        source: str,
    ) -> Dict[str, Any]:
        start_idx = raw_text.find("{")
        end_idx = raw_text.rfind("}") + 1
        if start_idx == -1 or end_idx <= start_idx:
            raise ValueError("JSON not found in model response")

        payload = json.loads(raw_text[start_idx:end_idx])
        found_name = self._clean_text_value(payload.get("found_name"))
        article = self._clean_text_value(payload.get("article"))
        confidence = float(payload.get("confidence", 0) or 0)
        reasoning = self._clean_text_value(payload.get("reasoning"))

        matched_item = None
        if found_name:
            matched_item = candidate_lookup.get(found_name.lower()) or getattr(self, "catalog_dict", {}).get(found_name.lower())
        if matched_item is None and article:
            matched_item = article_lookup.get(article.lower())

        if matched_item is None:
            return self._build_missing_result(query, reasoning or "Gemini не выбрал валидного кандидата")

        return self._build_result_from_item(
            matched_item,
            score=max(0.0, min(0.999, confidence)),
            source=source,
            requires_review=confidence < 0.9,
            alternatives="",
            reason=reasoning,
        )

    def _match_with_gemini(
        self,
        query: str,
        query_features: Optional[Dict[str, Any]] = None,
        branches: Optional[List[str]] = None,
        candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if candidates:
            context_chunks = self._build_narrow_candidate_chunks(branches or [], candidates, query_features)
            source = "local_tree+gemini"
        else:
            context_chunks = self._build_context_chunks(query)
            source = "gemini"

        if not context_chunks:
            return self._build_missing_result(query, "Контекст для Gemini отсутствует")

        candidate_lookup = {
            item.get("name", "").lower(): item
            for item in (candidates or [])
            if item.get("name")
        }
        article_lookup = {
            item.get("article", "").lower(): item
            for item in (candidates or [])
            if item.get("article")
        }

        def build_prompt(context_text: str) -> str:
            if candidates:
                return (
                    "Ты выбираешь лучший товар только из уже отобранного короткого списка.\n"
                    f"Запрос КП: {query}\n"
                    f"Строка типа: {(query_features or {}).get('row_type', 'item')}\n"
                    f"Категории: {' | '.join(branches or [])}\n"
                    "Ниже только допустимые кандидаты:\n"
                    f"{context_text}\n\n"
                    "Выбери лучший кандидат только из этого списка. Если все слабые, все равно выбери лучший.\n"
                    "Верни только JSON: "
                    '{"found_name":"Точное имя из списка","article":"Артикул из списка или null","confidence":0.0,"reasoning":"краткое объяснение"}'
                )
            return (
                "Ты эксперт по технической номенклатуре оборудования, кабеля и материалов.\n"
                f"Запрос пользователя: {query}\n"
                "Найди лучший товар в каталоге ниже.\n"
                f"{context_text}\n"
                "Верни только JSON: "
                '{"found_name":"Точное название из каталога или null","article":"Артикул или null","confidence":0.0,"reasoning":"краткое объяснение"}'
            )

        last_missing: Dict[str, Any] | None = None
        last_error: Exception | None = None
        last_raw_text = ""

        for context_text in context_chunks:
            prompt = build_prompt(context_text)
            for model_name in self._candidate_models():
                try:
                    raw_text = self._generate_gemini_text(prompt, model_name)
                    parsed = self._parse_gemini_result(query, raw_text, candidate_lookup, article_lookup, source)
                    self.model_name = model_name
                    if parsed["found_name"] == MISSING_POSITION_TEXT:
                        last_missing = parsed
                        last_raw_text = raw_text
                        continue
                    self._save_to_cache(
                        query,
                        parsed["found_name"],
                        parsed["price"],
                        parsed["article"] or "",
                        parsed["similarity_score"],
                        raw_text,
                    )
                    return parsed
                except Exception as exc:
                    last_error = exc
                    logger.warning("Model %s failed: %s", model_name, exc)

        if last_missing is not None:
            self._save_to_cache(
                query,
                last_missing["found_name"],
                last_missing["price"],
                last_missing["article"] or "",
                last_missing["similarity_score"],
                last_raw_text,
            )
            return last_missing

        return self._build_missing_result(query, "", error=str(last_error) if last_error else "Gemini did not return result")

    def _resolve_ambiguous_candidates_with_gemini(
        self,
        query: str,
        query_features: Dict[str, Any],
        branches: List[str],
        scored_entries: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        shortlist = [entry["item"] for entry in scored_entries[: min(12, len(scored_entries))]]
        if not shortlist:
            return None
        try:
            result = self._match_with_gemini(
                query,
                query_features=query_features,
                branches=branches,
                candidates=shortlist,
            )
        except TypeError:
            result = self._match_with_gemini(query)
        if not result or result.get("found_name") == MISSING_POSITION_TEXT:
            return None
        result["alternatives"] = result.get("alternatives") or self._format_alternatives(scored_entries, skip_first=True)
        if result.get("requires_review") not in {"да", "нет"}:
            result["requires_review"] = "да" if result.get("similarity_score", 0) < 0.9 else "нет"
        if not result.get("category_path"):
            match_item = getattr(self, "catalog_dict", {}).get(str(result.get("found_name", "")).lower())
            if match_item:
                result["category_path"] = match_item.get("branch_path")
        result.setdefault(
            "confidence_level",
            self._confidence_level_from_score(result.get("similarity_score", 0), result.get("requires_review") == "да"),
        )
        result.setdefault("resolution_source", "local_tree+gemini")
        return result

    def match(self, query: str, use_cache: bool = True) -> Dict[str, Any]:
        if use_cache:
            cached = self._get_from_cache(query)
            if cached:
                return cached

        try:
            query_text = self._clean_text_value(query)
            if not query_text:
                return self._build_missing_result(query, "Пустая строка")

            exact_match = (getattr(self, "catalog_dict", {}) or {}).get(query_text.lower())
            if exact_match:
                self._save_to_cache(query_text, exact_match["name"], exact_match["price"], exact_match["article"], 1.0, "exact_match")
                return self._build_result_from_item(exact_match, 1.0, "exact_match", False, "", "")

            normalized_query = self._normalize_text(query_text)
            normalized_match = (getattr(self, "catalog_normalized_dict", {}) or {}).get(normalized_query)
            if normalized_match:
                self._save_to_cache(query_text, normalized_match["name"], normalized_match["price"], normalized_match["article"], 0.98, "normalized_match")
                return self._build_result_from_item(normalized_match, 0.98, "normalized_match", False, "", "")

            local_direct = self._try_local_semantic_match(query_text)
            if local_direct:
                self._save_to_cache(
                    query_text,
                    local_direct["found_name"],
                    local_direct["price"],
                    local_direct["article"] or "",
                    local_direct["similarity_score"],
                    "local_semantic_match",
                )
                local_direct.pop("_matched_item", None)
                return local_direct

            query_features = self._extract_query_features(query_text)
            ranked_branches = self._rank_branches(query_features)
            query_features["ranked_branches"] = ranked_branches
            branch_paths = [entry["path"] for entry in ranked_branches if entry.get("path")]
            branch_candidates = self._collect_branch_candidates(branch_paths)
            if not branch_candidates:
                branch_candidates = self._select_candidates(query_text, limit=60)

            scored_entries = self._score_candidates_locally(query_features, branch_candidates)
            if not scored_entries and getattr(self, "catalog_items", []):
                scored_entries = self._score_candidates_locally(query_features, self._select_candidates(query_text, limit=20))
            if not scored_entries:
                return self._match_with_gemini(query_text)

            best_entry = scored_entries[0]
            best_score = float(best_entry["score"])
            second_score = float(scored_entries[1]["score"]) if len(scored_entries) > 1 else 0.0
            margin = best_score - second_score
            top_branch_gap = 0.0
            if len(ranked_branches) > 1:
                top_branch_gap = float(ranked_branches[0]["score"]) - float(ranked_branches[1]["score"])
            elif ranked_branches:
                top_branch_gap = float(ranked_branches[0]["score"])

            strong_local = (
                best_score >= getattr(self, "local_confidence_threshold", 0.92)
                and margin >= getattr(self, "local_margin_threshold", 0.08)
                and top_branch_gap >= 0.15
                and query_features.get("row_type") == "item"
            )
            if strong_local:
                result = self._build_result_from_item(
                    best_entry["item"],
                    best_score,
                    "local_tree",
                    False,
                    self._format_alternatives(scored_entries, skip_first=True),
                    "",
                )
                self._save_to_cache(query_text, result["found_name"], result["price"], result["article"] or "", result["similarity_score"], "local_tree")
                return result

            ambiguous = (
                query_features.get("row_type") == "section"
                or margin < max(0.05, getattr(self, "local_margin_threshold", 0.08))
                or top_branch_gap < 0.15
            )
            if ambiguous:
                gemini_result = self._resolve_ambiguous_candidates_with_gemini(query_text, query_features, branch_paths, scored_entries)
                if gemini_result:
                    return gemini_result

            forced_reason = (
                "Выбран лучший локальный кандидат без достаточного отрыва. Требуется проверка."
                if query_features.get("row_type") == "item"
                else "Строка похожа на раздел каталога; выбран обобщенный лучший кандидат."
            )
            result = self._build_result_from_item(
                best_entry["item"],
                best_score,
                "forced_best_match",
                True,
                self._format_alternatives(scored_entries, skip_first=True),
                forced_reason,
            )
            self._save_to_cache(query_text, result["found_name"], result["price"], result["article"] or "", result["similarity_score"], "forced_best_match")
            return result

        except Exception as exc:
            logger.error("Matching error: %s", exc, exc_info=True)
            return self._build_missing_result(query, "", error=str(exc))

    def save_to_history(
        self,
        query: str,
        found_name: str,
        price: Optional[float],
        article: str,
        user_approved: bool,
        correction_note: str = "",
    ) -> None:
        try:
            conn = sqlite3.connect(self.cache_db)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO match_history
                (original_query, found_name, price, article, user_approved, correction_note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (query, found_name, price, article, user_approved, correction_note, datetime.now()),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("History write error: %s", exc)

    def _run_matches_parallel(self, tasks: List[Tuple[int, str]]) -> List[Tuple[int, Dict[str, Any]]]:
        if not tasks:
            return []

        workers = min(max(1, int(getattr(self, "parallel_requests", 1))), len(tasks))
        if workers <= 1:
            return [(idx, self.match(query, use_cache=True)) for idx, query in tasks]

        results: List[Tuple[int, Dict[str, Any]]] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {pool.submit(self.match, query, True): idx for idx, query in tasks}
            completed = 0
            total = len(tasks)
            for future in as_completed(future_map):
                idx = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = self._build_missing_result("", "", error=str(exc))
                results.append((idx, result))
                completed += 1
                if completed % 10 == 0 or completed == total:
                    logger.info("Processed %s/%s rows", completed, total)
        return results

    def _compose_not_found_reason(self, query: str, result: Dict[str, Any]) -> str:
        query_text = str(query or "").strip()
        model_reason = str((result or {}).get("reason") or "").strip()
        model_error = str((result or {}).get("error") or "").strip()
        if model_error:
            return (
                f"Позиция '{query_text}' не сопоставлена из-за ошибки обращения к модели/сервису: {model_error}. "
                "Рекомендуется повторить попытку позже и проверить доступность API/лимиты."
            )
        if model_reason:
            return (
                f"Позиция '{query_text}' не найдена в текущем каталоге. "
                f"Причина: {model_reason}. "
                "Проверьте формулировку, категорию, ключевые характеристики и наличие аналога в БД поставщика."
            )
        return (
            f"Позиция '{query_text}' не найдена: релевантное совпадение в текущем каталоге отсутствует "
            "или не достигнут порог уверенности. Проверьте, что позиция есть в БД, совпадают категория, "
            "длина/сечение/материал, а также попробуйте режим 'analog' для поиска близкого аналога."
        )

    def process_excel(self, excel_path: str, output_path: str | None = None) -> Tuple[pd.DataFrame, Dict[str, int]]:
        logger.info("Start processing Excel: %s", excel_path)
        df = pd.read_excel(excel_path)

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

        if "Цена" not in df.columns:
            df["Цена"] = pd.Series([None] * len(df), dtype="float64")
        else:
            df["Цена"] = pd.to_numeric(df["Цена"], errors="coerce").astype("float64")

        for text_col in (
            "Найденная номенклатура",
            "Артикул",
            "Ошибка сопоставления",
            "Причина отсутствия",
            "Путь категории",
            "Уровень уверенности",
            "Требует проверки",
            "Альтернативы",
            "Источник решения",
        ):
            if text_col not in df.columns:
                df[text_col] = None
            else:
                df[text_col] = df[text_col].astype(object)

        stats = {"total": 0, "found": 0, "not_found": 0, "from_cache": 0, "errors": 0}
        tasks: List[Tuple[int, str]] = []
        for idx, row in df.iterrows():
            query = str(row[col_b]).strip()
            if not query or query.lower() == "nan":
                continue
            if query.strip().lower() in {"наименование", "наименование оборудования, материалов и кабелей", "nomenclature"}:
                continue
            tasks.append((idx, query))

        stats["total"] = len(tasks)
        task_query_map = {idx: query for idx, query in tasks}
        for idx, result in self._run_matches_parallel(tasks):
            found_name = result.get("found_name") or MISSING_POSITION_TEXT
            df.at[idx, "Цена"] = result.get("price")
            df.at[idx, "Найденная номенклатура"] = found_name
            df.at[idx, "Артикул"] = result.get("article")
            df.at[idx, "Ошибка сопоставления"] = result.get("error")
            df.at[idx, "Путь категории"] = result.get("category_path")
            df.at[idx, "Уровень уверенности"] = result.get("confidence_level")
            df.at[idx, "Требует проверки"] = result.get("requires_review")
            df.at[idx, "Альтернативы"] = result.get("alternatives")
            df.at[idx, "Источник решения"] = result.get("resolution_source")

            if found_name == MISSING_POSITION_TEXT:
                df.at[idx, "Причина отсутствия"] = self._compose_not_found_reason(task_query_map.get(idx, ""), result)
            else:
                df.at[idx, "Причина отсутствия"] = result.get("reason") or None

            if result.get("from_cache"):
                stats["from_cache"] += 1
            if found_name == MISSING_POSITION_TEXT:
                stats["not_found"] += 1
            else:
                stats["found"] += 1
            if not result.get("success", True):
                stats["errors"] += 1

        if output_path is None:
            src = Path(excel_path)
            output_path = str(src.with_name(f"{src.stem}_matched{src.suffix}"))

        df.to_excel(output_path, index=False)
        logger.info("Result saved: %s", output_path)
        return df, stats


if __name__ == "__main__":
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("Set GEMINI_API_KEY environment variable")

    matcher = ReMoMatcher(
        gemini_api_key=api_key,
        db_csv_path=str(get_catalog_csv_path()),
    )

    for query in (
        "Кабель медный cat6",
        "Горизонтальный блок розеток PDU 1U 19\"",
        "Вертикальный блок розеток PDU Zero U",
    ):
        print(query)
        print(matcher.match(query))
