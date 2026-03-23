from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

import pandas as pd

try:
    import duckdb

    MATCHER_DUCKDB_AVAILABLE = True
except ImportError:
    duckdb = None
    MATCHER_DUCKDB_AVAILABLE = False

from catalog_search import (
    DUCKDB_AVAILABLE as SEARCH_DUCKDB_AVAILABLE,
    SEARCH_CATALOG_FILENAME,
    SEARCH_CATALOG_TABLE,
    clean_text_value as shared_clean_text_value,
    classify_item_type as shared_classify_item_type,
    derive_branch_from_text as shared_derive_branch_from_text,
    extract_item_markers as shared_extract_item_markers,
    get_search_catalog_readiness,
    is_search_catalog_path,
    iter_search_catalog_chunks,
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
    normalize_header,
)
from config import (
    get_catalog_csv_path,
    get_matcher_cache_db_path,
    get_matcher_context_chunk_size,
    get_matcher_gemini_chunk_size,
    get_matcher_gemini_max_chunks,
    get_matcher_gemini_shortlist_limit,
    get_matcher_local_confidence_threshold,
    get_matcher_local_recall_pool,
    get_matcher_local_margin_threshold,
    get_matcher_max_context_chunks,
    get_matcher_models,
    get_matcher_parallel_requests,
    get_matcher_retrieval_candidates,
    get_matcher_skip_weak_shortlist,
)
from match_diagnostics import build_match_diagnostics_payload, infer_reason_class
from query_parser import (
    detect_query_row_type as shared_detect_query_row_type,
    extract_query_article_from_text as shared_extract_query_article_from_text,
    parse_query_spec as shared_parse_query_spec,
)
from taxonomy_registry import (
    allowed_cross_family_pairs as registry_allowed_cross_family_pairs,
    audit_family_groups as registry_audit_family_groups,
    audited_families as registry_audited_families,
    classify_entity_type_from_registry,
    clean_registry_text,
    domain_conflict_reason as registry_domain_conflict_reason,
    entity_family_for_type,
    family_default_branches as registry_family_default_branches,
    family_entity_types as registry_family_entity_types,
    family_retrieval_mode as registry_family_retrieval_mode,
    family_secondary_filter_rules as registry_family_secondary_filter_rules,
    family_requires_same_family_gate as registry_family_requires_same_family_gate,
    family_strictness as registry_family_strictness,
    family_weak_match_policy as registry_family_weak_match_policy,
    gemini_policy_value as registry_gemini_policy_value,
    infer_domain_match as registry_infer_domain_match,
    is_whole_category_family as registry_is_whole_category_family,
    load_registry_taxonomy_rules,
    verifier_auto_accept_sources as registry_verifier_auto_accept_sources,
    verifier_compatible_default_decision as registry_verifier_compatible_default_decision,
    verifier_default_review_reason as registry_verifier_default_review_reason,
    verifier_reject_row_types as registry_verifier_reject_row_types,
    verifier_review_sources as registry_verifier_review_sources,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

MISSING_POSITION_TEXT = "Позиция отсутствует"
MATCH_MODE_EXACT = "exact"
MATCH_MODE_ANALOG = "analog"
MATCH_MODE_ASSEMBLY = "assembly"
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
MATCHER_LOAD_CHUNKSIZE = 50000
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

CABLE_DESIGNATION_BASE_STOPWORDS = {
    "силовой",
    "контрольный",
    "монтажный",
    "однопроволочный",
    "многопроволочный",
    "ок",
    "n",
    "pe",
    "тртс",
    "барабан",
}
ARTICLE_SERIES_TOKEN_STOPWORDS = {
    "ls",
    "hf",
    "ip",
    "mm",
    "мм",
    "арт",
    "sku",
    "l",
    "n",
    "pe",
    "ok",
    "trts",
    "тртс",
}

WHOLE_CATEGORY_RETRIEVAL_FAMILIES = {
    "airflow_blanking_panel",
    "ats_sts",
    "bulk_twisted_pair",
    "floor_box",
    "ground_bar",
    "iec_power_cable",
    "keystone",
    "optical_cross",
    "optical_patch_cord",
    "patch_cord",
    "patch_panel",
    "pdu",
    "rack",
    "rack_accessory_strict",
    "rack_rail",
    "rack_shelf",
    "rj45_connector",
    "rj45_outlet",
    "sensor",
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
        "cat 6a": "cat6a",
        "кат 6": "cat6",
        "кат 6a": "cat6a",
        "cat 5e": "cat5e",
        "кат 5e": "cat5e",
    },
    "attribute_patterns": {
        "category": [
            {"regex": r"\b(?:cat|кат|категор(?:ия|ии)?)\s*6(?:a|а)\b", "value": "cat6a"},
            {"regex": r"\b(?:cat|кат|категор(?:ия|ии)?)\s*6\b", "value": "cat6"},
            {"regex": r"\b(?:cat|кат|категор(?:ия|ии)?)\s*5e\b", "value": "cat5e"},
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
        catalog_sample_items: int = 300,
        match_mode: str = MATCH_MODE_EXACT,
        gemini_shortlist_limit: int | None = None,
        gemini_chunk_size: int | None = None,
        gemini_max_chunks: int | None = None,
        local_recall_pool: int | None = None,
        skip_weak_shortlist: bool | None = None,
    ):
        self.api_key = gemini_api_key
        self.db_csv_path = self._resolve_catalog_csv_path(db_csv_path)
        self.cache_db = str(get_matcher_cache_db_path(cache_db))
        self.catalog: pd.DataFrame | None = None
        self.catalog_dict: Dict[str, Dict[str, Any]] = {}
        self.catalog_normalized_dict: Dict[str, Dict[str, Any]] = {}
        self.catalog_article_dict: Dict[str, Dict[str, Any]] = {}
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
        self.catalog_storage_backend = "memory"
        self.retrieval_backend = "memory"
        self.retrieval_mode = "legacy_limited"
        self.catalog_row_count = 0
        self.matcher_init_ms = 0.0
        self._duckdb_path: str | None = None
        self._duckdb_local = threading.local()
        self._match_context_local = threading.local()
        self.client = None
        self.legacy_genai = None
        self.model_name: str | None = None
        self.parallel_requests = min(25, max(1, int(parallel_requests or get_matcher_parallel_requests())))
        self._gemini_request_limit = self.parallel_requests
        self._gemini_request_semaphore = threading.BoundedSemaphore(self._gemini_request_limit)
        self.gemini_chunk_parallelism = max(1, min(4, self.parallel_requests))
        self.catalog_sample_items = max(50, int(catalog_sample_items))
        self.match_mode = self._sanitize_match_mode(match_mode)
        self.gemini_shortlist_limit = self._sanitize_int_setting(
            gemini_shortlist_limit if gemini_shortlist_limit is not None else get_matcher_gemini_shortlist_limit(),
            minimum=24,
            maximum=200,
            fallback=96,
        )
        self.gemini_chunk_size = self._sanitize_int_setting(
            gemini_chunk_size if gemini_chunk_size is not None else get_matcher_gemini_chunk_size(),
            minimum=6,
            maximum=20,
            fallback=12,
        )
        self.gemini_max_chunks = self._sanitize_int_setting(
            gemini_max_chunks if gemini_max_chunks is not None else get_matcher_gemini_max_chunks(),
            minimum=1,
            maximum=12,
            fallback=8,
        )
        self.local_recall_pool = self._sanitize_int_setting(
            local_recall_pool if local_recall_pool is not None else get_matcher_local_recall_pool(),
            minimum=100,
            maximum=1000,
            fallback=300,
        )
        self.skip_weak_shortlist = self._sanitize_bool_setting(
            skip_weak_shortlist if skip_weak_shortlist is not None else get_matcher_skip_weak_shortlist()
        )
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
        init_started_at = time.perf_counter()
        self._load_catalog()
        self.matcher_init_ms = round((time.perf_counter() - init_started_at) * 1000, 2)
        logger.info(
            "ReMoMatcher initialized: init_ms=%s retrieval_backend=%s retrieval_mode=%s",
            self.matcher_init_ms,
            self.retrieval_backend,
            self.retrieval_mode,
        )

    def _resolve_catalog_csv_path(self, db_csv_path: str) -> str:
        source_path = Path(str(db_csv_path))
        search_readiness = get_search_catalog_readiness(source_path)
        if source_path.is_dir() or is_search_catalog_path(source_path):
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
        if mode in {MATCH_MODE_EXACT, MATCH_MODE_ANALOG, MATCH_MODE_ASSEMBLY}:
            return mode
        return MATCH_MODE_EXACT

    @staticmethod
    def _sanitize_int_setting(
        value: Any,
        *,
        minimum: int,
        maximum: int,
        fallback: int,
    ) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = fallback
        return min(maximum, max(minimum, parsed))

    @staticmethod
    def _sanitize_bool_setting(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return False

    def _catalog_load_chunksize(self) -> int:
        raw_value = os.getenv("REMO_MATCHER_LOAD_CHUNKSIZE", str(MATCHER_LOAD_CHUNKSIZE))
        try:
            return max(1000, int(raw_value))
        except (TypeError, ValueError):
            return MATCHER_LOAD_CHUNKSIZE

    def _uses_duckdb_query_backend(self) -> bool:
        source_path = Path(str(getattr(self, "db_csv_path", "")))
        return (
            MATCHER_DUCKDB_AVAILABLE
            and SEARCH_DUCKDB_AVAILABLE
            and source_path.suffix.lower() == ".duckdb"
            and is_search_catalog_path(source_path)
        )

    def _get_duckdb_connection(self):
        if not self._uses_duckdb_query_backend():
            raise RuntimeError("DuckDB retrieval backend is not available")
        connection = getattr(self._duckdb_local, "connection", None)
        if connection is None:
            connection = duckdb.connect(str(self._duckdb_path or self.db_csv_path), read_only=True)
            self._duckdb_local.connection = connection
        return connection

    @staticmethod
    def _quote_sql_identifier(value: str) -> str:
        return '"' + str(value).replace('"', '""') + '"'

    def _stable_row_idx_for_item(self, *, name: str, article: str, branch_path: str) -> int:
        payload = f"{name.lower()}|{article.lower()}|{branch_path.lower()}"
        return int(hashlib.md5(payload.encode("utf-8")).hexdigest()[:12], 16)

    def _catalog_row_to_item(self, row: Dict[str, Any], *, row_idx: int | None = None) -> Dict[str, Any] | None:
        name = self._clean_text_value(row.get(CANONICAL_NAME_COLUMN))
        if not name:
            return None

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
        derived_markers = shared_extract_item_markers(
            combined_text,
            attribute_patterns=getattr(self, "taxonomy_rules", {}).get("attribute_patterns", {}),
            synonyms=getattr(self, "taxonomy_rules", {}).get("synonyms", {}),
        )
        for marker_key, marker_value in derived_markers.items():
            if not self._clean_text_value(item_markers.get(marker_key)):
                item_markers[marker_key] = marker_value

        resolved_row_idx = row_idx
        if resolved_row_idx is None:
            resolved_row_idx = self._stable_row_idx_for_item(name=name, article=article, branch_path=branch_path)

        return {
            "name": name,
            "name_lc": name.lower(),
            "normalized_name": normalized_name,
            "article": article,
            "price": price,
            "row_idx": int(resolved_row_idx),
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

    def _duckdb_fetch_frame(self, sql: str, params: List[Any] | Tuple[Any, ...] | None = None) -> pd.DataFrame:
        frame = self._get_duckdb_connection().execute(sql, list(params or [])).df()
        if frame.empty:
            return frame
        return canonicalize_catalog_columns(frame, create_missing=True)

    def _duckdb_fetch_items(
        self,
        *,
        where_sql: str = "",
        params: List[Any] | Tuple[Any, ...] | None = None,
        order_by_sql: str = "",
        limit: int | None = None,
    ) -> List[Dict[str, Any]]:
        sql = f"SELECT * FROM {SEARCH_CATALOG_TABLE}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        if order_by_sql:
            sql += f" ORDER BY {order_by_sql}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        frame = self._duckdb_fetch_frame(sql, params)
        items: List[Dict[str, Any]] = []
        for row in frame.to_dict(orient="records"):
            item = self._catalog_row_to_item(row)
            if item is not None:
                items.append(item)
        return items

    def _lookup_catalog_item_by_name(self, name: str, *, candidate_pool: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any] | None:
        normalized_name = self._clean_text_value(name).lower()
        if not normalized_name:
            return None
        for item in candidate_pool or []:
            if self._clean_text_value(item.get("name")).lower() == normalized_name:
                return item
        cached = (getattr(self, "catalog_dict", {}) or {}).get(normalized_name)
        if cached is not None:
            return cached
        if not self._uses_duckdb_query_backend():
            return None
        column = self._quote_sql_identifier(CANONICAL_NAME_COLUMN)
        items = self._duckdb_fetch_items(where_sql=f"lower({column}) = ?", params=[normalized_name], limit=1)
        return items[0] if items else None

    def _lookup_catalog_item_by_article(self, article: str) -> Dict[str, Any] | None:
        article_key = self._normalize_article_lookup_value(article)
        if not article_key:
            return None
        cached = (getattr(self, "catalog_article_dict", {}) or {}).get(article_key)
        if cached is not None:
            return cached
        if not self._uses_duckdb_query_backend():
            return None
        column = self._quote_sql_identifier(CANONICAL_ARTICLE_COLUMN)
        items = self._duckdb_fetch_items(
            where_sql=f"regexp_replace(lower(trim({column})), '\\s+', ' ', 'g') = ?",
            params=[article_key],
            limit=2,
        )
        if len(items) == 1:
            return items[0]
        return None

    def _lookup_catalog_item_by_normalized_name(self, normalized_name: str) -> Dict[str, Any] | None:
        cleaned = self._clean_text_value(normalized_name)
        if not cleaned:
            return None
        cached = (getattr(self, "catalog_normalized_dict", {}) or {}).get(cleaned)
        if cached is not None:
            return cached
        if not self._uses_duckdb_query_backend():
            return None
        items = self._duckdb_fetch_items(
            where_sql=f"{self._quote_sql_identifier('search_normalized_name')} = ?",
            params=[cleaned],
            limit=1,
        )
        return items[0] if items else None

    def _direct_name_match_source(self, query_text: str, item: Dict[str, Any] | None) -> str:
        if not isinstance(item, dict):
            return ""
        cleaned_query = self._clean_text_value(query_text)
        candidate_name = self._clean_text_value(item.get("name"))
        if cleaned_query and candidate_name and cleaned_query.lower() == candidate_name.lower():
            return "name_exact"
        normalized_query = self._normalize_text(cleaned_query)
        candidate_normalized = self._clean_text_value(item.get("normalized_name")) or self._normalize_text(candidate_name)
        if normalized_query and candidate_normalized and normalized_query == candidate_normalized:
            return "normalized_name_exact"
        return ""

    def _exact_resolution_source_for_item(
        self,
        query_text: str,
        query_article: str,
        article_source: str,
        item: Dict[str, Any] | None,
    ) -> str:
        if not isinstance(item, dict):
            return ""
        normalized_query_article = self._normalize_article_lookup_value(query_article)
        normalized_item_article = self._normalize_article_lookup_value(item.get("article"))
        if normalized_query_article and normalized_item_article and normalized_query_article == normalized_item_article:
            return "article_extracted_exact" if article_source == "text" else "article_exact"
        return self._direct_name_match_source(query_text, item)

    @staticmethod
    def _exact_resolution_score(source: str) -> float:
        return 0.98 if source == "normalized_name_exact" else 1.0

    @staticmethod
    def _resolver_path_for_source(source: str) -> str:
        normalized = str(source or "").strip()
        if normalized in {
            "article_exact",
            "article_extracted_exact",
            "article_series_local",
        }:
            return "article_resolver"
        if normalized in {
            "article_designation_exact",
            "designation_exact",
        }:
            return "cable_designation_resolver"
        if normalized in {"name_exact", "normalized_name_exact"}:
            return "direct_exact_resolver"
        if normalized in {"local_tree+gemini", "candidate_tiebreaker_gemini"}:
            return "semantic_resolver"
        if normalized.endswith("_fallback") or normalized in {"assembly_possible_local_fallback"}:
            return "fallback_resolver"
        if normalized == "unresolved":
            return "reject_resolver"
        return ""

    @staticmethod
    def _is_reject_result_payload(result: Dict[str, Any]) -> bool:
        resolution_source = str(result.get("resolution_source") or "").strip()
        compatibility_status = str(result.get("compatibility_status") or "").strip()
        return (
            resolution_source == "unresolved"
            or compatibility_status.startswith("unresolved")
            or compatibility_status.startswith("rejected_")
            or not bool(result.get("success", True))
        )

    def _effective_resolver_path_for_result(
        self,
        result: Dict[str, Any],
        query_features: Dict[str, Any] | None = None,
    ) -> str:
        return str(
            result.get("resolver_path")
            or (query_features or {}).get("active_resolver_path")
            or self._resolver_path_for_source(result.get("resolution_source"))
            or ""
        )

    def _verifier_evaluation_for_result(
        self,
        result: Dict[str, Any],
        *,
        resolver_path: str = "",
        query_features: Dict[str, Any] | None = None,
    ) -> Tuple[str, str]:
        if self._is_reject_result_payload(result):
            return "reject", "reject_payload"
        taxonomy_rules = self._runtime_taxonomy_rules()
        row_type = self._clean_text_value((query_features or {}).get("row_type")).lower()
        active_resolver_path = self._clean_text_value(resolver_path)
        reject_row_types = registry_verifier_reject_row_types(
            taxonomy_rules,
            active_resolver_path,
        )
        if row_type and row_type in reject_row_types:
            return "reject", f"reject_row_type:{row_type}"
        compatibility_status = str(result.get("compatibility_status") or "").strip()
        if compatibility_status != "compatible":
            return "review", f"compatibility:{compatibility_status or 'unknown'}"
        requires_review = self._clean_text_value(result.get("requires_review")).lower()
        if requires_review == "да":
            return "review", "requires_review_flag"
        resolution_source = str(result.get("resolution_source") or "").strip()
        auto_accept_sources = registry_verifier_auto_accept_sources(
            taxonomy_rules,
            active_resolver_path,
        )
        if resolution_source in auto_accept_sources:
            return "auto_accept", f"auto_accept_source:{resolution_source}"
        review_sources = registry_verifier_review_sources(
            taxonomy_rules,
            active_resolver_path,
        )
        if resolution_source in review_sources:
            return "review", f"review_only_source:{resolution_source}"
        decision = registry_verifier_compatible_default_decision(
            taxonomy_rules,
            active_resolver_path,
            default="review",
        )
        if decision == "review":
            return decision, self._default_review_reason_for_result(
                result,
                resolver_path=active_resolver_path,
                query_features=query_features,
            )
        return decision, f"default_{decision}"

    def _default_review_reason_for_result(
        self,
        result: Dict[str, Any],
        *,
        resolver_path: str = "",
        query_features: Dict[str, Any] | None = None,
    ) -> str:
        taxonomy_rules = self._runtime_taxonomy_rules()
        normalized_path = self._clean_text_value(resolver_path)
        query_features = query_features or {}
        query_article = self._normalize_article_lookup_value(query_features.get("query_article"))
        found_article = self._normalize_article_lookup_value(result.get("article"))
        if normalized_path == "rack_tray_resolver":
            if query_article and found_article and query_article != found_article:
                return "review_rack_tray_series_match"
            return registry_verifier_default_review_reason(
                taxonomy_rules,
                normalized_path,
                default="review_rack_tray_semantic_match",
            )
        return registry_verifier_default_review_reason(
            taxonomy_rules,
            normalized_path,
            default="default_review",
        )

    def _apply_verifier_decision(
        self,
        result: Dict[str, Any],
        query_features: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        result["resolver_path"] = self._effective_resolver_path_for_result(result, query_features)
        verifier_decision, verifier_reason = self._verifier_evaluation_for_result(
            result,
            resolver_path=str(result.get("resolver_path") or ""),
            query_features=query_features,
        )
        result["verifier_decision"] = verifier_decision
        result["verifier_reason"] = verifier_reason
        result["auto_accept"] = result["verifier_decision"] == "auto_accept"
        return result

    @staticmethod
    def _is_rack_tray_family(entity_family: str) -> bool:
        normalized = str(entity_family or "").strip()
        return normalized in {
            "rack_accessory_strict",
            "rack_shelf",
            "rack_rail",
            "rack_blank_panel",
            "rack_brush_panel",
        }

    def _should_use_rack_tray_resolver(self, query_features: Dict[str, Any]) -> bool:
        if self._clean_text_value(query_features.get("row_type")) != "item":
            return False
        return self._is_rack_tray_family(self._entity_family(query_features.get("entity_type", "")))

    def _is_telecom_family(self, entity_family: str) -> bool:
        normalized_family = self._clean_text_value(entity_family)
        if not normalized_family:
            return False
        default_branches = registry_family_default_branches(
            normalized_family,
            getattr(self, "taxonomy_rules", {}),
        )
        for branch in default_branches:
            normalized_branch = self._normalize_text(self._clean_text_value(branch))
            if normalized_branch.startswith("телеком"):
                return True
        return False

    def _semantic_resolver_path_for_query(self, query_features: Dict[str, Any]) -> str:
        if self._should_use_rack_tray_resolver(query_features):
            return "rack_tray_resolver"
        query_family = self._entity_family(query_features.get("entity_type", ""))
        if self._clean_text_value(query_features.get("row_type")) == "item" and self._is_telecom_family(query_family):
            return "telecom_semantic_resolver"
        return "semantic_resolver"

    def _activate_semantic_resolver_path(self, query_features: Dict[str, Any]) -> str:
        resolver_path = self._semantic_resolver_path_for_query(query_features)
        query_features["active_resolver_path"] = resolver_path
        return resolver_path

    def _fallback_resolver_path_for_query(self, query_features: Dict[str, Any]) -> str:
        query_family = self._entity_family(query_features.get("entity_type", ""))
        taxonomy_rules = self._runtime_taxonomy_rules()
        normalized_query = self._normalize_text(
            query_features.get("original_text")
            or query_features.get("original_query")
            or query_features.get("query_text")
            or ""
        )
        domain_match = registry_infer_domain_match(
            normalized_query,
            entity_family=query_family,
            rules=taxonomy_rules,
        )
        domain_label = self._clean_text_value(domain_match.get("label")).lower()
        domain_confidence = float(domain_match.get("confidence") or 0.0)
        query_article = self._normalize_article_lookup_value(query_features.get("query_article"))
        has_dimensions = bool(
            query_features.get("dimension_pairs")
            or query_features.get("dimension_triples")
            or query_features.get("dimension_lengths")
            or query_features.get("dimension_diameters")
        )
        if query_family == "software" or normalized_query.startswith("по ") or (domain_label == "software" and domain_confidence >= 0.5):
            return "software_review_resolver"
        if query_family == "sensor" or (domain_label == "monitoring_hw" and "датчик" in normalized_query and domain_confidence >= 0.5):
            return "sensor_review_resolver"
        if query_family == "monitoring_hw" or (
            any(token in normalized_query for token in {"арм", "индикац", "контрол"})
            or (
            domain_label in {"monitoring_hw", "monitor_display"} and domain_confidence >= 0.5
            )
        ):
            return "monitoring_review_resolver"
        if (query_article or "артикул" in normalized_query) and has_dimensions and domain_label in {"tray", ""}:
            return "series_review_resolver"
        return "fallback_resolver"

    def _cached_result_resolver_path(self, query_features: Dict[str, Any]) -> str:
        if self._should_use_rack_tray_resolver(query_features):
            return "rack_tray_resolver"
        query_family = self._entity_family(query_features.get("entity_type", ""))
        if query_family in {"other", "sensor", "software", "monitoring_hw"}:
            return self._fallback_resolver_path_for_query(query_features)
        if self._clean_text_value(query_features.get("row_type")) == "item" and self._is_telecom_family(query_family):
            return "telecom_semantic_resolver"
        return "semantic_resolver"

    def _typed_candidate_pool_for_rack_tray(
        self,
        query_text: str,
        query_features: Dict[str, Any],
        limit: int,
    ) -> List[Dict[str, Any]]:
        entity_family = self._entity_family(query_features.get("entity_type", ""))
        typed_limit = min(limit, 300)
        branch_paths = [entry["path"] for entry in query_features.get("ranked_branches", []) if entry.get("path")]
        typed_pool: List[Dict[str, Any]] = []
        seen: set[int] = set()
        supplemented = 0
        query_features["active_resolver_path"] = "rack_tray_resolver"

        def _matches_rack_tray_candidate(item: Dict[str, Any]) -> bool:
            item_family = self._entity_family(item.get("entity_type", ""))
            if item_family != entity_family:
                return False
            return not self._is_hard_incompatible_match(query_features, item)

        def _append_candidates(items: List[Dict[str, Any]], *, stop_after_limit: bool) -> bool:
            nonlocal supplemented
            for item in items:
                if not _matches_rack_tray_candidate(item):
                    continue
                row_idx = int(item.get("row_idx", -1))
                if row_idx in seen:
                    continue
                typed_pool.append(item)
                seen.add(row_idx)
                if stop_after_limit and len(typed_pool) >= typed_limit:
                    return True
            return False

        if self._should_use_whole_category_retrieval(query_features):
            category_key, category_candidates, _elapsed_ms = self._duckdb_category_candidates(query_features)
            query_features["query_category_key"] = category_key
            _append_candidates(category_candidates, stop_after_limit=False)
        else:
            branch_candidates = self._collect_branch_candidates(
                branch_paths,
                limit=max(typed_limit * 2, typed_limit),
                query_features=query_features,
            )
            if _append_candidates(branch_candidates, stop_after_limit=True):
                logger.info(
                    "🧠 Rack/tray typed candidate pool: query=%s family=%s typed_candidates=%s supplemented=%s",
                    query_text[:120],
                    entity_family or "other",
                    len(typed_pool),
                    supplemented,
                )
                return typed_pool

        general_candidates = self._select_candidates(query_text, limit=max(limit * 2, typed_limit))
        for item in general_candidates:
            if not _matches_rack_tray_candidate(item):
                continue
            row_idx = int(item.get("row_idx", -1))
            if row_idx in seen:
                continue
            typed_pool.append(item)
            seen.add(row_idx)
            supplemented += 1
            if len(typed_pool) >= typed_limit:
                break

        logger.info(
            "🧠 Rack/tray typed candidate pool: query=%s family=%s typed_candidates=%s supplemented=%s",
            query_text[:120],
            entity_family or "other",
            len(typed_pool),
            supplemented,
        )
        return typed_pool

    def _resolve_article_stack(
        self,
        query_text: str,
        query_article: str,
        article_source: str,
        article_lookup_conflict: bool,
        query_features: Dict[str, Any],
        trace_steps: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        article_lookup_hit = False
        article_series_candidates: List[Dict[str, Any]] = []

        article_match = self._lookup_catalog_item_by_article(query_article) if query_article else None
        article_sanity_reason = ""
        if query_article:
            article_lookup_hit = article_match is not None
            article_lookup_status = "miss"
            if article_match is not None:
                query_features["article_candidate_text"] = " ".join(
                    filter(
                        None,
                        [
                            self._clean_text_value(article_match.get("name")),
                            self._clean_text_value(article_match.get("normalized_name")),
                            self._clean_text_value(article_match.get("branch_path")),
                        ],
                    )
                )
                query_features["article_candidate_family"] = self._entity_family(article_match.get("entity_type", ""))
                article_sanity_reason = self._article_match_sanity_reason(query_features, article_match)
                article_lookup_status = "rejected" if article_sanity_reason else "hit"
                if article_sanity_reason and self._should_use_article_validator_gemini(query_features, article_sanity_reason):
                    validated_result = self._validate_article_match_with_gemini(query_text, query_features, article_match, query_article)
                    if validated_result is not None:
                        query_features["gemini_validation_used"] = True
                        query_features["article_validation_status"] = "validated_by_gemini"
                        trace_steps.append(
                            {
                                "stage": "article_lookup",
                                "status": "validated",
                                "article_source": article_source,
                                "query_article": query_article,
                                "article_lookup_conflict": article_lookup_conflict,
                                "reason_code": article_sanity_reason,
                                "gemini_validation_used": True,
                            }
                        )
                        validated_result["resolver_path"] = "article_resolver"
                        return {
                            "result": validated_result,
                            "article_lookup_hit": article_lookup_hit,
                            "article_series_candidates": article_series_candidates,
                        }
                    query_features["gemini_validation_used"] = True
                    query_features["article_validation_status"] = "rejected_by_gemini"
                if article_sanity_reason:
                    query_features["article_lookup_rejected_reason"] = article_sanity_reason
                    query_features.setdefault("article_validation_status", "rejected")
            trace_steps.append(
                {
                    "stage": "article_lookup",
                    "status": article_lookup_status,
                    "article_source": article_source,
                    "query_article": query_article,
                    "article_lookup_conflict": article_lookup_conflict,
                    "reason_code": article_sanity_reason,
                }
            )
        if article_match is not None and not article_sanity_reason:
            article_reason = "Exact article match from input column."
            resolution_source = "article_exact"
            if article_source == "text":
                article_reason = "Exact article match extracted from row text."
                resolution_source = "article_extracted_exact"
            elif article_lookup_conflict:
                article_reason = "Exact article match from input column; column article took priority over text."
            result = self._build_result_from_item(
                article_match,
                1.0,
                resolution_source,
                False,
                "",
                article_reason,
            )
            result["resolver_path"] = "article_resolver"
            return {
                "result": result,
                "article_lookup_hit": article_lookup_hit,
                "article_series_candidates": article_series_candidates,
            }

        cable_designation_match = self._lookup_catalog_item_by_cable_designation(query_text, query_article)
        if cable_designation_match is not None:
            trace_steps.append(
                {
                    "stage": "designation_lookup",
                    "status": "hit",
                    "designation_source": article_source if query_article else "query",
                }
            )
            result = self._build_result_from_item(
                cable_designation_match,
                0.995,
                "article_designation_exact" if query_article else "designation_exact",
                False,
                "",
                "Техническое обозначение кабеля из строки точно сопоставлено с номенклатурой каталога.",
            )
            result["resolver_path"] = self._resolver_path_for_source(result.get("resolution_source")) or "cable_designation_resolver"
            return {
                "result": result,
                "article_lookup_hit": article_lookup_hit,
                "article_series_candidates": article_series_candidates,
            }

        if query_article:
            article_series_candidates = self._lookup_catalog_items_by_article_series(query_article, query_features)
            if article_series_candidates:
                trace_steps.append(
                    {
                        "stage": "article_lookup",
                        "status": "series_candidates",
                        "article_source": article_source,
                        "query_article": query_article,
                        "series_candidate_count": len(article_series_candidates),
                    }
                )
                article_series_match = self._best_article_series_match(
                    query_features,
                    article_series_candidates,
                    article=query_article,
                )
                if article_series_match is not None:
                    result = self._build_result_from_item(
                        article_series_match,
                        0.985,
                        "article_series_local",
                        True,
                        "",
                        "Сопоставлено по расширенной серии артикула с проверкой на смысловую и размерную совместимость.",
                    )
                    result["resolver_path"] = "article_resolver"
                    return {
                        "result": result,
                        "article_lookup_hit": article_lookup_hit,
                        "article_series_candidates": article_series_candidates,
                    }

        return {
            "result": None,
            "article_lookup_hit": article_lookup_hit,
            "article_series_candidates": article_series_candidates,
        }

    def _resolve_direct_exact_stack(
        self,
        query_text: str,
        normalized_query: str,
        query_article: str,
        article_source: str,
    ) -> Tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
        exact_match = self._lookup_catalog_item_by_name(query_text)
        if exact_match:
            exact_source = self._exact_resolution_source_for_item(query_text, query_article, article_source, exact_match) or "name_exact"
            exact_score = self._exact_resolution_score(exact_source)
            result = self._build_result_from_item(exact_match, exact_score, exact_source, False, "", "")
            result["resolver_path"] = self._resolver_path_for_source(exact_source) or "direct_exact_resolver"
            return result, {"item": exact_match, "score": exact_score, "lexical_score": exact_score}

        normalized_match = self._lookup_catalog_item_by_normalized_name(normalized_query)
        if normalized_match:
            exact_source = self._exact_resolution_source_for_item(
                query_text,
                query_article,
                article_source,
                normalized_match,
            ) or "normalized_name_exact"
            exact_score = self._exact_resolution_score(exact_source)
            result = self._build_result_from_item(
                normalized_match,
                exact_score,
                exact_source,
                False,
                "",
                "",
            )
            result["resolver_path"] = self._resolver_path_for_source(exact_source) or "direct_exact_resolver"
            return result, {"item": normalized_match, "score": exact_score, "lexical_score": exact_score}

        local_direct = self._try_local_semantic_match(query_text)
        if local_direct:
            matched_item = local_direct.pop("_matched_item", None)
            direct_source = self._exact_resolution_source_for_item(
                query_text,
                query_article,
                article_source,
                matched_item,
            )
            if matched_item and direct_source:
                direct_score = self._exact_resolution_score(direct_source)
                result = self._build_result_from_item(matched_item, direct_score, direct_source, False, "", "")
                result["resolver_path"] = self._resolver_path_for_source(direct_source) or "direct_exact_resolver"
                return result, {"item": matched_item, "score": direct_score, "lexical_score": direct_score}
            result = dict(local_direct)
            result["resolver_path"] = "direct_exact_resolver"
            if matched_item:
                return result, {
                    "item": matched_item,
                    "score": float(local_direct["similarity_score"]),
                    "lexical_score": float(local_direct["similarity_score"]),
                }
            return result, None

        return None, None

    def _entity_types_for_family(self, entity_family: str) -> set[str]:
        return registry_family_entity_types(entity_family, getattr(self, "taxonomy_rules", {}))

    def _default_branch_paths_for_family(self, query_features: Dict[str, Any]) -> List[str]:
        return registry_family_default_branches(
            query_features.get("entity_type", ""),
            getattr(self, "taxonomy_rules", {}),
            branch_hint=self._clean_text_value(query_features.get("branch_hint")),
        )

    def _should_use_whole_category_retrieval(self, query_features: Dict[str, Any]) -> bool:
        if not self._uses_duckdb_query_backend():
            return False
        if self._clean_text_value(query_features.get("row_type")) != "item":
            return False
        family = self._entity_family(query_features.get("entity_type", ""))
        if not registry_is_whole_category_family(family, getattr(self, "taxonomy_rules", {})):
            return False
        return any(self._clean_text_value(path) and self._clean_text_value(path) != "прочее" for path in self._default_branch_paths_for_family(query_features))

    def _whole_category_secondary_filter_groups(self, query_features: Dict[str, Any]) -> List[Tuple[str, ...]]:
        family = self._entity_family(query_features.get("entity_type", ""))
        markers = query_features.get("markers", {}) or {}
        normalized_query = self._normalize_text(self._clean_text_value(query_features.get("original_text")))
        groups: List[Tuple[str, ...]] = []

        if family == "rack" and "органайз" in normalized_query:
            groups.append(("органайз",))
        elif family == "sensor":
            sensor_kind = self._clean_text_value(markers.get("sensor_kind"))
            if sensor_kind == "temperature_humidity":
                groups.append(("датчик",))
                groups.append(("температур", "влажност"))
            elif sensor_kind == "temperature":
                groups.append(("датчик",))
                groups.append(("температур",))
        elif family == "rack_accessory_strict":
            mount_kind = self._clean_text_value(markers.get("mount_kind"))
            if mount_kind == "brush_panel":
                groups.append(("щеточ",))
            elif mount_kind == "blank_panel":
                groups.append(("заглуш",))

        return groups

    def _candidate_secondary_filter_haystack(self, item: Dict[str, Any]) -> str:
        return self._normalize_text(
            " ".join(
                filter(
                    None,
                    [
                        self._clean_text_value(item.get("name")),
                        self._clean_text_value(item.get("normalized_name")),
                    ],
                )
            )
        )

    def _apply_optional_secondary_filter(
        self,
        candidates: List[Dict[str, Any]],
        predicate: Callable[[Dict[str, Any]], bool],
    ) -> List[Dict[str, Any]]:
        if not candidates:
            return candidates
        filtered = [item for item in candidates if predicate(item)]
        return filtered if filtered else candidates

    def _secondary_filter_rule_matches(self, rule: Dict[str, Any], query_features: Dict[str, Any]) -> bool:
        query_markers = query_features.get("markers", {}) or {}
        normalized_query = self._normalize_text(self._clean_text_value(query_features.get("original_text")))
        when_marker_equals = rule.get("when_marker_equals", {}) or {}
        for marker_name, expected_value in when_marker_equals.items():
            if self._clean_text_value(query_markers.get(marker_name)) != self._clean_text_value(expected_value):
                return False
        query_tokens = [self._clean_text_value(token) for token in (rule.get("when_query_contains_any", []) or []) if self._clean_text_value(token)]
        if query_tokens and not any(token in normalized_query for token in query_tokens):
            return False
        return True

    def _query_dimension_tokens(self, query_text: str) -> List[str]:
        normalized = self._normalize_text(query_text)
        tokens: List[str] = []
        tokens.extend(re.findall(r"\b\d{1,4}\s*[xх]\s*\d{1,4}(?:\s*[xх]\s*\d{1,4})?\b", normalized, flags=re.IGNORECASE))
        tokens.extend(re.findall(r"\bl\s*=?\s*\d{1,5}\b", normalized, flags=re.IGNORECASE))
        tokens.extend(re.findall(r"\bd\s*=?\s*\d{1,4}(?:\s*-\s*\d{1,4})?\b", normalized, flags=re.IGNORECASE))
        return [self._normalize_text(token) for token in tokens if self._normalize_text(token)]

    def _candidate_matches_marker_rule(self, item: Dict[str, Any], *, expected_value: str, candidate_marker: str, fallback_patterns: Dict[str, Any] | None = None) -> bool:
        item_marker_value = self._clean_text_value((item.get("item_markers") or {}).get(candidate_marker))
        if item_marker_value:
            return item_marker_value == expected_value
        patterns = fallback_patterns or {}
        haystack = self._candidate_secondary_filter_haystack(item)
        for token in patterns.get(expected_value, []) or []:
            if self._clean_text_value(token) and self._clean_text_value(token) in haystack:
                return True
        return False

    def _apply_secondary_filter_rule(
        self,
        rule: Dict[str, Any],
        query_features: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not candidates or not self._secondary_filter_rule_matches(rule, query_features):
            return candidates
        rule_type = self._clean_text_value(rule.get("type"))
        query_markers = query_features.get("markers", {}) or {}
        query_text = self._clean_text_value(query_features.get("original_text"))

        if rule_type in {"require_marker_equal", "prefer_marker_equal"}:
            marker_name = self._clean_text_value(rule.get("marker"))
            candidate_marker = self._clean_text_value(rule.get("candidate_marker")) or marker_name
            expected_value = self._clean_text_value(query_markers.get(marker_name))
            if not expected_value:
                return candidates
            predicate = lambda item: self._candidate_matches_marker_rule(
                item,
                expected_value=expected_value,
                candidate_marker=candidate_marker,
                fallback_patterns=rule.get("fallback_patterns", {}),
            )
            if rule_type == "require_marker_equal":
                filtered = [item for item in candidates if predicate(item)]
                return filtered if filtered else candidates
            return self._apply_optional_secondary_filter(candidates, predicate)

        if rule_type in {"require_any_token_group", "prefer_any_token_group"}:
            groups = rule.get("groups", []) or []
            if not groups:
                return candidates
            predicate = lambda item: all(
                any(self._clean_text_value(token) and self._clean_text_value(token) in self._candidate_secondary_filter_haystack(item) for token in group)
                for group in groups
            )
            if rule_type == "require_any_token_group":
                filtered = [item for item in candidates if predicate(item)]
                return filtered if filtered else candidates
            return self._apply_optional_secondary_filter(candidates, predicate)

        if rule_type == "prefer_any_tokens":
            required_tokens = [self._clean_text_value(token) for token in (rule.get("tokens", []) or []) if self._clean_text_value(token)]
            if not required_tokens:
                return candidates
            return self._apply_optional_secondary_filter(
                candidates,
                lambda item: any(token in self._candidate_secondary_filter_haystack(item) for token in required_tokens),
            )

        if rule_type == "prefer_dimension_overlap":
            dimension_tokens = self._query_dimension_tokens(query_text)
            if not dimension_tokens:
                return candidates
            return self._apply_optional_secondary_filter(
                candidates,
                lambda item: any(token in self._candidate_secondary_filter_haystack(item) for token in dimension_tokens),
            )

        if rule_type == "prefer_connector_pair":
            connector_pair = self._clean_text_value(query_markers.get("connector_pair"))
            if not connector_pair:
                return candidates
            return self._apply_optional_secondary_filter(
                candidates,
                lambda item: self._clean_text_value((item.get("item_markers") or {}).get("connector_pair")) == connector_pair,
            )

        if rule_type == "prefer_component_kind":
            component_kind = self._clean_text_value(query_markers.get("component_kind"))
            if not component_kind:
                return candidates
            return self._apply_optional_secondary_filter(
                candidates,
                lambda item: self._clean_text_value((item.get("item_markers") or {}).get("component_kind")) == component_kind,
            )

        return candidates

    def _bulk_twisted_pair_secondary_filter(
        self,
        query_features: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        filtered = candidates
        markers = query_features.get("markers", {}) or {}
        normalized_query = self._normalize_text(self._clean_text_value(query_features.get("original_text")))
        query_category = self._clean_text_value(markers.get("category"))
        query_shielding = self._clean_text_value(markers.get("shielding"))
        query_environment = self._clean_text_value(markers.get("cable_environment"))

        if query_category:
            filtered = self._apply_optional_secondary_filter(
                filtered,
                lambda item: (
                    self._clean_text_value((item.get("item_markers") or {}).get("category")) == query_category
                    if self._clean_text_value((item.get("item_markers") or {}).get("category"))
                    else bool(
                        re.search(
                            rf"\b{re.escape(query_category)}\b",
                            self._candidate_secondary_filter_haystack(item),
                            flags=re.IGNORECASE,
                        )
                    )
                ),
            )

        if query_shielding:
            shielding_patterns = {
                "utp": (
                    r"(?<![a-z])u\s*/\s*utp\b",
                    r"(?<![a-z])u\s+utp\b",
                    r"неэкранир",
                    r"(?<![a-z/])utp\b",
                ),
                "ftp": (
                    r"(?<![a-z])f\s*/\s*utp\b",
                    r"(?<![a-z])f\s+utp\b",
                    r"(?<![a-z])ftp\b",
                ),
                "sftp": (
                    r"(?<![a-z])s\s*/\s*ftp\b",
                    r"(?<![a-z])sftp\b",
                    r"(?<![a-z])sf\s*/\s*utp\b",
                    r"(?<![a-z])f\s*/\s*ftp\b",
                ),
                "shielded": (
                    r"(?<![a-z])s\s*/\s*ftp\b",
                    r"(?<![a-z])sftp\b",
                    r"(?<![a-z])sf\s*/\s*utp\b",
                    r"(?<![a-z])f\s*/\s*ftp\b",
                    r"(?<![a-z])f\s*/\s*utp\b",
                    r"(?<![a-z])f\s+utp\b",
                    r"(?<![a-z])ftp\b",
                    r"экранир",
                ),
            }

            def _shielding_matches(item: Dict[str, Any]) -> bool:
                item_shielding = self._clean_text_value((item.get("item_markers") or {}).get("shielding"))
                if query_shielding == "shielded":
                    if item_shielding:
                        return item_shielding in {"ftp", "sftp", "shielded"}
                elif item_shielding:
                    return item_shielding == query_shielding
                haystack = self._candidate_secondary_filter_haystack(item)
                return any(
                    re.search(pattern, haystack, flags=re.IGNORECASE)
                    for pattern in shielding_patterns.get(query_shielding, ())
                )

            filtered = self._apply_optional_secondary_filter(filtered, _shielding_matches)

        if query_environment == "outdoor":
            filtered = self._apply_optional_secondary_filter(
                filtered,
                lambda item: (
                    self._clean_text_value((item.get("item_markers") or {}).get("cable_environment")) == "outdoor"
                    if self._clean_text_value((item.get("item_markers") or {}).get("cable_environment"))
                    else any(
                        token in self._candidate_secondary_filter_haystack(item)
                        for token in ("outdoor", "внешн", "наружн", "улич")
                    )
                ),
            )

        if "lszh" in normalized_query:
            filtered = self._apply_optional_secondary_filter(
                filtered,
                lambda item: "lszh" in self._candidate_secondary_filter_haystack(item),
            )

        return filtered

    def _rack_accessory_secondary_filter(
        self,
        query_features: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        filtered = candidates
        markers = query_features.get("markers", {}) or {}
        normalized_query = self._normalize_text(self._clean_text_value(query_features.get("original_text")))
        query_mount = self._clean_text_value(markers.get("mount_kind"))
        query_rack_unit = self._clean_text_value(markers.get("rack_unit"))

        if query_mount:
            mount_text_tokens = {
                "brush_panel": ("щеточ",),
                "blank_panel": ("заглуш", "blanking", "blank panel"),
                "shelf": ("полк", "shelf"),
                "rail": ("рельс", "rail", "направля"),
            }
            filtered = self._apply_optional_secondary_filter(
                filtered,
                lambda item: (
                    self._clean_text_value((item.get("item_markers") or {}).get("mount_kind")) == query_mount
                    or any(
                        token in self._candidate_secondary_filter_haystack(item)
                        for token in mount_text_tokens.get(query_mount, ())
                    )
                ),
            )

        if query_rack_unit and query_rack_unit != "zero u":
            filtered = self._apply_optional_secondary_filter(
                filtered,
                lambda item: (
                    self._clean_text_value((item.get("item_markers") or {}).get("rack_unit")) == query_rack_unit
                    or any(
                        token in self._candidate_secondary_filter_haystack(item)
                        for token in (f"{query_rack_unit}u", f"{query_rack_unit} u")
                    )
                ),
            )

        if query_mount == "brush_panel" and "ввод" in normalized_query:
            filtered = self._apply_optional_secondary_filter(
                filtered,
                lambda item: any(
                    token in self._candidate_secondary_filter_haystack(item)
                    for token in ("ввод", "ввода", "cable entry", "entry panel")
                ),
            )

        if query_mount == "brush_panel" and "кабел" in normalized_query:
            filtered = self._apply_optional_secondary_filter(
                filtered,
                lambda item: any(
                    token in self._candidate_secondary_filter_haystack(item)
                    for token in ("кабел", "cable")
                ),
            )

        if query_mount == "blank_panel" and ("свободн" in normalized_query or "юнит" in normalized_query):
            filtered = self._apply_optional_secondary_filter(
                filtered,
                lambda item: any(
                    token in self._candidate_secondary_filter_haystack(item)
                    for token in ("свободн", "юнит", "blanking", "blank panel")
                ),
            )

        return filtered

    def _apply_whole_category_secondary_filter(
        self,
        query_features: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        original_count = len(candidates)
        family = self._entity_family(query_features.get("entity_type", ""))
        registry_rules = registry_family_secondary_filter_rules(family, getattr(self, "taxonomy_rules", {}))
        if registry_rules and candidates:
            filtered = candidates
            applied_rule_names: List[str] = []
            for rule in registry_rules:
                next_filtered = self._apply_secondary_filter_rule(rule, query_features, filtered)
                if next_filtered is not filtered:
                    applied_rule_names.append(self._clean_text_value(rule.get("name")) or self._clean_text_value(rule.get("type")))
                filtered = next_filtered
            if applied_rule_names:
                query_features["secondary_filter_rule_set"] = applied_rule_names
                query_features["secondary_filter_before_count"] = original_count
                query_features["secondary_filter_after_count"] = len(filtered)
                if len(filtered) != original_count:
                    logger.info(
                        "🧠 Whole-category secondary filter: query=%s family=%s rules=%s before=%s after=%s",
                        self._clean_text_value(query_features.get("original_text"))[:120],
                        family or "other",
                        ",".join(applied_rule_names),
                        original_count,
                        len(filtered),
                    )
                return filtered
        filtered = candidates
        groups = self._whole_category_secondary_filter_groups(query_features)
        if groups and filtered:
            group_filtered: List[Dict[str, Any]] = []
            for item in filtered:
                haystack = self._candidate_secondary_filter_haystack(item)
                if all(any(term in haystack for term in group) for group in groups):
                    group_filtered.append(item)
            if group_filtered:
                filtered = group_filtered

        if family == "bulk_twisted_pair" and filtered:
            filtered = self._bulk_twisted_pair_secondary_filter(query_features, filtered)
        elif family == "rack_accessory_strict" and filtered:
            filtered = self._rack_accessory_secondary_filter(query_features, filtered)

        if filtered and len(filtered) != original_count:
            logger.info(
                "🧠 Whole-category secondary filter: query=%s family=%s before=%s after=%s",
                self._clean_text_value(query_features.get("original_text"))[:120],
                family or "other",
                original_count,
                len(filtered),
            )
            return filtered
        return filtered

    def _should_query_gemini_without_candidates(self, query_features: Dict[str, Any]) -> bool:
        if self._clean_text_value(query_features.get("row_type")) != "item":
            return False
        if self._uses_duckdb_query_backend() and self._should_use_whole_category_retrieval(query_features):
            return False
        return True

    def _should_accept_weak_gemini_result(
        self,
        gemini_result: Dict[str, Any],
        compatible_entries: List[Dict[str, Any]],
        query_features: Dict[str, Any],
        retrieval_mode: str,
    ) -> bool:
        compatibility = self._clean_text_value(gemini_result.get("compatibility_status"))
        if compatibility != "weakly_compatible":
            return True
        if self._should_reject_weak_resolution_in_exact_mode(query_features):
            return False
        if retrieval_mode == "whole_category" and compatible_entries:
            return False
        return True

    def _should_reject_weak_resolution_in_exact_mode(self, query_features: Dict[str, Any]) -> bool:
        if getattr(self, "match_mode", MATCH_MODE_EXACT) != MATCH_MODE_EXACT:
            return False
        if self._clean_text_value(query_features.get("article_lookup_rejected_reason")):
            return True
        query_family = self._entity_family(query_features.get("entity_type", ""))
        return registry_family_weak_match_policy(query_family, getattr(self, "taxonomy_rules", {})) == "reject_in_exact"

    def _duckdb_category_candidates(self, query_features: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], float]:
        branch_paths = [path for path in self._default_branch_paths_for_family(query_features) if path and path != "прочее"]
        if not branch_paths:
            return "", [], 0.0

        started_at = time.perf_counter()
        branch_clauses: List[str] = []
        params: List[Any] = []
        branch_column = self._quote_sql_identifier("search_branch_path")
        for path in branch_paths:
            branch_clauses.append(f"({branch_column} = ? OR {branch_column} LIKE ?)")
            params.extend([path, f"{path}{BRANCH_PATH_SEPARATOR}%"])

        query_family = self._entity_family(query_features.get("entity_type", ""))
        family_types = sorted(self._entity_types_for_family(query_features.get("entity_type", "")))
        filters = ["(" + " OR ".join(branch_clauses) + ")"]
        if family_types and query_family not in {"", "other"}:
            entity_column = self._quote_sql_identifier("search_entity_type")
            placeholders = ", ".join("?" for _ in family_types)
            filters.append(f"{entity_column} IN ({placeholders})")
            params.extend(family_types)

        exact_branch = branch_paths[0]
        items = self._duckdb_fetch_items(
            where_sql=" AND ".join(filters),
            params=params,
            limit=None,
        )
        items.sort(
            key=lambda item: (
                0 if self._clean_text_value(item.get("branch_path")) == exact_branch else 1,
                self._clean_text_value(item.get("branch_path")),
                self._clean_text_value(item.get("name")),
            )
        )
        items = self._apply_whole_category_secondary_filter(query_features, items)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        return exact_branch, items, elapsed_ms

    def _duckdb_heuristic_candidates(
        self,
        query: str,
        query_features: Dict[str, Any] | None = None,
        *,
        limit: int,
    ) -> Tuple[List[Dict[str, Any]], float]:
        started_at = time.perf_counter()
        features = query_features or self._extract_query_features(query)
        tokens = [token for token in features.get("tokens", []) if len(token) >= 3][:6]
        branch_paths = [path for path in self._default_branch_paths_for_family(features) if path and path != "прочее"][:2]

        filters: List[str] = []
        params: List[Any] = []
        if branch_paths:
            branch_column = self._quote_sql_identifier("search_branch_path")
            branch_clauses: List[str] = []
            for path in branch_paths:
                branch_clauses.append(f"({branch_column} = ? OR {branch_column} LIKE ?)")
                params.extend([path, f"{path}{BRANCH_PATH_SEPARATOR}%"])
            filters.append("(" + " OR ".join(branch_clauses) + ")")

        query_family = self._entity_family(features.get("entity_type", ""))
        family_types = sorted(self._entity_types_for_family(features.get("entity_type", "")))
        if family_types and query_family not in {"", "other"}:
            entity_column = self._quote_sql_identifier("search_entity_type")
            placeholders = ", ".join("?" for _ in family_types)
            filters.append(f"{entity_column} IN ({placeholders})")
            params.extend(family_types)

        text_clauses: List[str] = []
        for token in tokens:
            token_like = f"%{token}%"
            text_clauses.append(f"{self._quote_sql_identifier('search_normalized_name')} LIKE ?")
            params.append(token_like)
        if text_clauses:
            filters.append("(" + " OR ".join(text_clauses) + ")")

        items = self._duckdb_fetch_items(
            where_sql=" AND ".join(filters) if filters else "",
            params=params,
            limit=max(1, int(limit)),
        )
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        return items, elapsed_ms

    def _should_load_catalog_column(self, column_name: str) -> bool:
        header = normalize_header(column_name)
        normalized = header.lower().replace("ё", "е")
        explicit_columns = {
            CANONICAL_NAME_COLUMN,
            CANONICAL_ARTICLE_COLUMN,
            CANONICAL_PRICE_COLUMN,
            "Название класса",
            "Код класса",
            "Тип изделия",
            "Тип исполнения кабельного изделия",
            "Производитель",
            "search_branch_path",
            "search_branch_leaf",
            "search_normalized_name",
            "search_tokens_json",
            "search_entity_type",
            "search_item_markers_json",
        }
        if header in explicit_columns:
            return True
        if "наименован" in normalized or "номенклатур" in normalized or normalized in {"товар", "product name", "name"}:
            return True
        if ("цена" in normalized and "закуп" not in normalized and "опт" not in normalized) or normalized in {"retail price", "price"}:
            return True
        if any(marker in normalized for marker in ("артикул", "sku", "партномер", "part number", "partnumber", "vendor code")):
            return True
        if normalized in {"код", "код товара", "код номенклатуры", "item code", "product code"}:
            return True
        return False

    def _load_taxonomy_rules(self) -> Dict[str, Any]:
        path_raw = os.getenv("REMO_TAXONOMY_RULES_PATH")
        path = Path(path_raw) if path_raw else DEFAULT_TAXONOMY_RULES_PATH
        try:
            return load_registry_taxonomy_rules(base_rules=DEFAULT_TAXONOMY_RULES, path=path)
        except Exception as exc:
            logger.warning("Failed to load taxonomy rules from %s: %s", path, exc)
            return load_registry_taxonomy_rules(base_rules=DEFAULT_TAXONOMY_RULES)

    def _runtime_taxonomy_rules(self) -> Dict[str, Any]:
        rules = getattr(self, "taxonomy_rules", None)
        if isinstance(rules, dict) and rules:
            return rules
        loaded = self._load_taxonomy_rules()
        self.taxonomy_rules = loaded
        return loaded

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

    def _normalize_article_lookup_value(self, value: object) -> str:
        cleaned = self._clean_text_value(value)
        if not cleaned:
            return ""
        return re.sub(r"\s+", " ", cleaned).strip().lower()

    def _compact_article_series_key(self, value: object) -> str:
        normalized = self._normalize_article_lookup_value(value)
        if not normalized:
            return ""
        return re.sub(r"[^0-9a-zа-я]+", "", normalized, flags=re.IGNORECASE)

    def _extract_query_article_from_text(self, query: str) -> str:
        cleaned_query = self._clean_text_value(query)
        if not cleaned_query:
            return ""
        collapsed = re.sub(r"\s+", " ", cleaned_query).strip()
        patterns = (
            r"(?:^|[\s,;/\(\)])(?:артикул|арт\.?|sku|part\s*number|partnumber|vendor\s*code)\s*[:№#-]?\s*(.+?)\s*$",
        )
        for pattern in patterns:
            match = re.search(pattern, collapsed, flags=re.IGNORECASE)
            if not match:
                continue
            article = re.sub(r"\s+", " ", match.group(1)).strip(" \t\r\n,;:.")
            if article:
                return article
        return ""

    def _extract_cable_designation_signature(self, text: str) -> Dict[str, str]:
        cleaned_text = self._clean_text_value(text)
        if not cleaned_text:
            return {}
        normalized = cleaned_text.lower().replace("ё", "е")
        normalized = re.sub(
            r"\b(?:кабель|провод|артикул|арт\.?|sku|part\s*number|partnumber|vendor\s*code)\b",
            " ",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(r"\s+", " ", normalized).strip(" \t\r\n,;:/-")
        if not normalized:
            return {}
        dimension_match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*[xх×*/]\s*(\d+(?:[.,]\d+)?)(?:\s*[xх×*/]\s*(\d+(?:[.,]\d+)?))?",
            normalized,
            flags=re.IGNORECASE,
        )
        if not dimension_match:
            return {}
        values = tuple(group for group in dimension_match.groups() if group)
        dimension_signature = ""
        if len(values) == 2:
            dimension_signature = self._canonical_cable_designation_dimension(values)
        elif len(values) == 3:
            dimension_signature = self._canonical_cable_designation_dimension(values)
        if not dimension_signature:
            return {}
        base_part = normalized[: dimension_match.start()]
        base_part = re.sub(r"[\(\)\[\],;:]+", " ", base_part)
        base_normalized = self._normalize_text(base_part)
        base_tokens = [
            token
            for token in self._tokenize(base_normalized)
            if token not in {"кабель", "провод", "артикул", "арт", "sku"}
        ]
        if not base_tokens:
            return {}
        base_signature = " ".join(base_tokens)
        return {
            "base": base_signature,
            "dimension": dimension_signature,
            "signature": f"{base_signature}|{dimension_signature}",
            "base_tokens": base_tokens,
        }

    def _canonical_cable_designation_dimension(self, values: Tuple[str, ...]) -> str:
        normalized_values = [
            self._normalize_dimension_value(value) for value in values if self._normalize_dimension_value(value)
        ]
        return "x".join(normalized_values)

    def _is_likely_cable_designation(self, value: object) -> bool:
        signature = self._extract_cable_designation_signature(self._clean_text_value(value))
        return bool(signature)

    def _cable_designation_base_tokens(self, signature: Dict[str, Any]) -> Tuple[str, ...]:
        if not signature:
            return ()
        raw_tokens = signature.get("base_tokens")
        if isinstance(raw_tokens, (list, tuple, set)):
            tokens = [self._clean_text_value(token).lower() for token in raw_tokens if self._clean_text_value(token)]
        else:
            tokens = [
                token
                for token in self._tokenize(self._clean_text_value(signature.get("base")))
                if token and token not in CABLE_DESIGNATION_BASE_STOPWORDS
            ]
        return tuple(tokens)

    def _cable_designation_base_tokens_match(
        self,
        query_tokens: Tuple[str, ...],
        item_tokens: Tuple[str, ...],
    ) -> bool:
        if not query_tokens or not item_tokens:
            return False
        item_token_set = set(item_tokens)
        for query_token in query_tokens:
            if query_token in item_token_set:
                continue
            if len(query_token) >= 4 and any(
                len(item_token) >= 4 and (item_token.endswith(query_token) or query_token.endswith(item_token))
                for item_token in item_tokens
            ):
                continue
            return False
        return True

    def _cable_designation_signatures_match(
        self,
        query_signature: Dict[str, Any],
        item_signature: Dict[str, Any],
    ) -> bool:
        if not query_signature or not item_signature:
            return False
        if query_signature.get("dimension") != item_signature.get("dimension"):
            return False
        query_tokens = self._cable_designation_base_tokens(query_signature)
        item_tokens = self._cable_designation_base_tokens(item_signature)
        if query_tokens and item_tokens:
            return self._cable_designation_base_tokens_match(query_tokens, item_tokens)
        return query_signature.get("signature") == item_signature.get("signature")

    def _duckdb_cable_designation_candidates(self, signature: Dict[str, Any], *, limit: int = 160) -> List[Dict[str, Any]]:
        if not signature or not self._uses_duckdb_query_backend():
            return []
        normalized_column = self._quote_sql_identifier("search_normalized_name")
        entity_column = self._quote_sql_identifier("search_entity_type")
        branch_column = self._quote_sql_identifier("search_branch_path")
        where_parts = [
            f"({entity_column} IN (?, ?) OR {branch_column} = ? OR {branch_column} LIKE ? OR {branch_column} = ? OR {branch_column} LIKE ?)"
        ]
        params: List[Any] = [
            "cable",
            "wire",
            "электрика > кабели",
            f"электрика > кабели{BRANCH_PATH_SEPARATOR}%",
            "электрика > провода",
            f"электрика > провода{BRANCH_PATH_SEPARATOR}%",
        ]
        for token in self._cable_designation_base_tokens(signature):
            where_parts.append(f"lower({normalized_column}) LIKE ?")
            params.append(f"%{token}%")
        for part in sorted({part.strip() for part in str(signature.get('dimension') or '').split('x') if part.strip()}):
            where_parts.append(f"lower({normalized_column}) LIKE ?")
            params.append(f"%{part.lower()}%")
        return self._duckdb_fetch_items(
            where_sql=" AND ".join(where_parts),
            params=params,
            limit=max(80, min(int(limit), 1600)),
        )

    def _lookup_catalog_item_by_cable_designation(self, query_text: str, query_article: str = "") -> Dict[str, Any] | None:
        designation_source = self._clean_text_value(query_article) or self._clean_text_value(query_text)
        signature = self._extract_cable_designation_signature(designation_source)
        if not signature:
            return None
        lookup_query = f"кабель {designation_source}".strip()
        lookup_features = self._extract_query_features(lookup_query)
        lookup_features["original_text"] = lookup_query
        lookup_features["normalized_text"] = self._normalize_text(lookup_query)
        lookup_features["ranked_branches"] = self._rank_branches(lookup_features)

        branch_paths = [entry["path"] for entry in lookup_features.get("ranked_branches", []) if entry.get("path")]
        candidate_pool = self._duckdb_cable_designation_candidates(signature, limit=640)
        supplemental_pool = self._typed_candidate_pool(lookup_query, lookup_features, limit=320)
        if supplemental_pool:
            merged_pool: List[Dict[str, Any]] = []
            seen_row_idx: set[int] = set()
            for item in candidate_pool + supplemental_pool:
                row_idx = int(item.get("row_idx", -1))
                if row_idx in seen_row_idx:
                    continue
                seen_row_idx.add(row_idx)
                merged_pool.append(item)
            candidate_pool = merged_pool
        if not candidate_pool:
            candidate_pool = self._collect_branch_candidates(branch_paths, limit=320, query_features=lookup_features)
        if not candidate_pool and self._uses_duckdb_query_backend():
            candidate_pool, _ = self._duckdb_heuristic_candidates(lookup_query, lookup_features, limit=320)
        if not candidate_pool:
            candidate_pool = self._select_candidates(lookup_query, limit=320)
        if not candidate_pool:
            return None

        direct_candidates: List[Dict[str, Any]] = []
        query_dimension = self._clean_text_value(signature.get("dimension")).lower()
        query_dimension_variants = {
            query_dimension,
            query_dimension.replace("x", "х"),
        }
        query_base_tokens = [token for token in self._cable_designation_base_tokens(signature) if token]
        seen_row_idx: set[int] = set()
        for item in candidate_pool:
            row_idx = int(item.get("row_idx", -1))
            if row_idx in seen_row_idx:
                continue
            item_name = self._clean_text_value(item.get("name"))
            item_normalized_name = self._clean_text_value(item.get("normalized_name"))
            item_haystack = f"{item_name} {item_normalized_name}".lower().replace("ё", "е")
            if query_dimension and not any(variant and variant in item_haystack for variant in query_dimension_variants):
                continue
            item_tokens = {
                self._clean_text_value(token).lower()
                for token in (item.get("tokens") or [])
                if self._clean_text_value(token)
            }
            if query_base_tokens and not all(token in item_tokens or token in item_haystack for token in query_base_tokens):
                continue
            if self._compatibility_label(lookup_features, item) != "compatible":
                continue
            seen_row_idx.add(row_idx)
            direct_candidates.append(item)

        if direct_candidates:
            scored_entries = self._score_candidates_locally(lookup_features, direct_candidates)
            if scored_entries:
                best_entry = scored_entries[0]
                if len(scored_entries) == 1:
                    return best_entry["item"]
                second_score = float(scored_entries[1]["score"])
                best_score = float(best_entry["score"])
                if len(direct_candidates) <= 2 and best_score >= 0.5 and best_score - second_score < 0.04:
                    return best_entry["item"]

        signature_candidates: List[Dict[str, Any]] = []
        seen_row_idx: set[int] = set()
        for item in candidate_pool:
            item_name = self._clean_text_value(item.get("name"))
            item_normalized_name = self._clean_text_value(item.get("normalized_name"))
            item_signature = self._extract_cable_designation_signature(item_name or item_normalized_name)
            if item_normalized_name and item_normalized_name != item_name:
                normalized_signature = self._extract_cable_designation_signature(item_normalized_name)
                if normalized_signature and (
                    not item_signature or self._cable_designation_signatures_match(signature, normalized_signature)
                ):
                    item_signature = normalized_signature
            if not self._cable_designation_signatures_match(signature, item_signature):
                continue
            row_idx = int(item.get("row_idx", -1))
            if row_idx in seen_row_idx:
                continue
            seen_row_idx.add(row_idx)
            if self._compatibility_label(lookup_features, item) != "compatible":
                continue
            signature_candidates.append(item)

        designation_fallback_used = False
        if not signature_candidates:
            weak_signature_base = not any(
                len(token) >= 3 and token not in {"ls", "hf", "ng"}
                for token in self._cable_designation_base_tokens(signature)
            )
            fallback_source = re.sub(
                r"\b(?:кабель|провод|артикул|арт\.?|sku|part\s*number|partnumber|vendor\s*code)\b",
                " ",
                designation_source.lower().replace("ё", "е"),
                flags=re.IGNORECASE,
            )
            fallback_base = fallback_source.split(str(signature.get("dimension") or ""), 1)[0]
            fallback_tokens = [
                token
                for token in re.findall(r"[a-zа-я0-9]+", fallback_base, flags=re.IGNORECASE)
                if len(token) >= 3
                and token not in CABLE_DESIGNATION_BASE_STOPWORDS
                and token not in {"кабель", "провод", "артикул", "sku"}
            ]
            if weak_signature_base:
                fallback_tokens = []
            if not fallback_tokens:
                fallback_tokens = [
                    token
                    for token in (lookup_features.get("tokens", []) or [])
                    if len(token) >= 3
                    and token not in GROUP_TOKEN_STOPWORDS
                    and token not in CABLE_DESIGNATION_BASE_STOPWORDS
                    and token not in {"кабель", "провод", "артикул", "sku", "ls", "hf"}
                ]
            query_dimensions = self._extract_dimension_signatures(designation_source)
            if fallback_tokens or any(query_dimensions.values()):
                seen_row_idx.clear()
                for item in candidate_pool:
                    item_name = self._clean_text_value(item.get("name"))
                    item_normalized_name = self._clean_text_value(item.get("normalized_name"))
                    item_text = f"{item_name} {item_normalized_name}".strip()
                    item_haystack = re.sub(r"[^a-zа-я0-9]+", " ", item_text.lower().replace("ё", "е"), flags=re.IGNORECASE)
                    raw_dimension_hint = self._clean_text_value(signature.get("dimension"))
                    has_raw_dimension_hint = bool(
                        raw_dimension_hint
                        and (
                            raw_dimension_hint in item_text.lower().replace("ё", "е")
                            or raw_dimension_hint.replace("x", "х") in item_text.lower().replace("ё", "е")
                        )
                    )
                    if fallback_tokens and not all(token in item_haystack for token in fallback_tokens):
                        continue
                    item_dimensions = self._extract_dimension_signatures(item_text)
                    if query_dimensions["triples"] and item_dimensions["triples"]:
                        if not (query_dimensions["triples"] & item_dimensions["triples"]):
                            continue
                    if query_dimensions["pairs"] and item_dimensions["pairs"]:
                        if not (query_dimensions["pairs"] & item_dimensions["pairs"]) and not has_raw_dimension_hint:
                            continue
                    if query_dimensions["lengths"] and item_dimensions["lengths"]:
                        if not (query_dimensions["lengths"] & item_dimensions["lengths"]):
                            continue
                    row_idx = int(item.get("row_idx", -1))
                    if row_idx in seen_row_idx:
                        continue
                    seen_row_idx.add(row_idx)
                    if self._compatibility_label(lookup_features, item) != "compatible":
                        continue
                    signature_candidates.append(item)
                    designation_fallback_used = True

        if not signature_candidates and candidate_pool and len(candidate_pool) <= 12:
            query_dimensions = self._extract_dimension_signatures(designation_source)
            seen_row_idx.clear()
            for item in candidate_pool:
                item_name = self._clean_text_value(item.get("name"))
                item_normalized_name = self._clean_text_value(item.get("normalized_name"))
                item_text = f"{item_name} {item_normalized_name}".strip()
                item_dimensions = self._extract_dimension_signatures(item_text)
                raw_dimension_hint = self._clean_text_value(signature.get("dimension"))
                has_raw_dimension_hint = bool(
                    raw_dimension_hint
                    and (
                        raw_dimension_hint in item_text.lower().replace("ё", "е")
                        or raw_dimension_hint.replace("x", "х") in item_text.lower().replace("ё", "е")
                    )
                )
                if query_dimensions["triples"] and item_dimensions["triples"]:
                    if not (query_dimensions["triples"] & item_dimensions["triples"]):
                        continue
                if query_dimensions["pairs"] and item_dimensions["pairs"]:
                    if not (query_dimensions["pairs"] & item_dimensions["pairs"]) and not has_raw_dimension_hint:
                        continue
                if query_dimensions["lengths"] and item_dimensions["lengths"]:
                    if not (query_dimensions["lengths"] & item_dimensions["lengths"]):
                        continue
                row_idx = int(item.get("row_idx", -1))
                if row_idx in seen_row_idx:
                    continue
                seen_row_idx.add(row_idx)
                if self._compatibility_label(lookup_features, item) != "compatible":
                    continue
                signature_candidates.append(item)
                designation_fallback_used = True

        if not signature_candidates:
            return None

        scored_entries = self._score_candidates_locally(lookup_features, signature_candidates)
        if not scored_entries:
            return None

        best_entry = scored_entries[0]
        if len(scored_entries) == 1:
            return best_entry["item"]

        second_score = float(scored_entries[1]["score"])
        best_score = float(best_entry["score"])
        if best_score - second_score < 0.04:
            if len(signature_candidates) <= 2 and best_score >= 0.5:
                return best_entry["item"]
            threshold = 0.52 if designation_fallback_used else 0.58
            if best_score < threshold:
                return None
        return best_entry["item"]

    def _lookup_catalog_items_by_article_series(self, article: str, query_features: Dict[str, Any]) -> List[Dict[str, Any]]:
        article_compact = self._compact_article_series_key(article)
        if len(article_compact) < 5 or self._is_likely_cable_designation(article):
            return []

        candidates: List[Dict[str, Any]] = []
        if self._uses_duckdb_query_backend():
            column = self._quote_sql_identifier(CANONICAL_ARTICLE_COLUMN)
            compact_expr = f"regexp_replace(lower(trim({column})), '[^0-9a-zа-я]+', '', 'g')"
            candidates = self._duckdb_fetch_items(
                where_sql=f"{compact_expr} LIKE ? AND length({compact_expr}) > ?",
                params=[f"{article_compact}%", len(article_compact)],
                limit=40,
            )
        else:
            for item in getattr(self, "catalog_items", []) or []:
                item_compact = self._compact_article_series_key(item.get("article"))
                if item_compact.startswith(article_compact) and len(item_compact) > len(article_compact):
                    candidates.append(item)

        filtered: List[Dict[str, Any]] = []
        seen_row_idx: set[int] = set()
        for item in candidates:
            row_idx = int(item.get("row_idx", -1))
            if row_idx in seen_row_idx:
                continue
            seen_row_idx.add(row_idx)
            if self._article_match_sanity_reason(query_features, item):
                continue
            filtered.append(item)
        return filtered

    def _extract_article_series_thickness_value(self, text: str) -> str:
        cleaned_text = self._clean_text_value(text).lower().replace("ё", "е")
        if not cleaned_text or "толщ" not in cleaned_text:
            return ""
        match = re.search(r"толщ(?:ина|\.?)?\s*(\d+(?:[.,]\d+)?)", cleaned_text, flags=re.IGNORECASE)
        if not match:
            return ""
        return self._normalize_dimension_value(match.group(1))

    def _article_series_match_bonus(
        self,
        query_features: Dict[str, Any],
        item: Dict[str, Any],
        article: str = "",
    ) -> float:
        query_raw_text = self._clean_text_value(query_features.get("original_text"))
        candidate_raw_text = " ".join(
            filter(
                None,
                [
                    self._clean_text_value(item.get("name")),
                    self._clean_text_value(item.get("branch_path")),
                ],
            )
        )
        query_text = re.sub(r"\s+", " ", query_raw_text.lower().replace("ё", "е")).strip()
        candidate_text = re.sub(r"\s+", " ", candidate_raw_text.lower().replace("ё", "е")).strip()
        if not query_text or not candidate_text:
            return 0.0

        bonus = 0.0
        query_dimensions = self._extract_dimension_signatures(query_raw_text)
        candidate_dimensions = self._extract_dimension_signatures(candidate_raw_text)
        if query_dimensions["triples"] and candidate_dimensions["triples"]:
            if query_dimensions["triples"] & candidate_dimensions["triples"]:
                bonus += 0.14
        elif query_dimensions["pairs"] and candidate_dimensions["pairs"]:
            if query_dimensions["pairs"] & candidate_dimensions["pairs"]:
                bonus += 0.1

        query_thickness = self._extract_article_series_thickness_value(query_raw_text)
        candidate_thickness = self._extract_article_series_thickness_value(candidate_raw_text)
        if query_thickness and candidate_thickness:
            if query_thickness == candidate_thickness:
                bonus += 0.12
            else:
                bonus -= 0.06

        technical_tokens = [
            token
            for token in re.findall(r"[a-z]{2,8}", query_text)
            if token not in ARTICLE_SERIES_TOKEN_STOPWORDS
        ]
        for token in technical_tokens[:4]:
            if token in candidate_text:
                bonus += 0.08

        query_article_compact = self._compact_article_series_key(article)
        item_article_compact = self._compact_article_series_key(item.get("article"))
        if query_article_compact and item_article_compact.startswith(query_article_compact):
            suffix = item_article_compact[len(query_article_compact) :]
            if suffix:
                if suffix.isdigit():
                    bonus += 0.18
                elif any(ch.isalpha() for ch in suffix):
                    bonus -= 0.04

        return max(-0.2, min(0.45, bonus))

    def _best_article_series_match(
        self,
        query_features: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        article: str = "",
    ) -> Dict[str, Any] | None:
        if not candidates:
            return None
        scored_entries = self._score_candidates_locally(query_features, candidates)
        if not scored_entries:
            return None
        rescored_entries: List[Dict[str, Any]] = []
        for entry in scored_entries:
            bonus = self._article_series_match_bonus(query_features, entry["item"], article=article)
            rescored_entries.append(
                {
                    **entry,
                    "article_series_bonus": float(bonus),
                    "score": max(0.0, min(0.999, float(entry["score"]) + float(bonus))),
                }
            )
        rescored_entries.sort(
            key=lambda entry: (entry["score"], entry["lexical_score"], -int(entry["item"].get("row_idx", 0))),
            reverse=True,
        )

        best_entry = self._best_compatible_local_entry(query_features, rescored_entries, allow_weak=False)
        if best_entry is None:
            return None
        compatible_scores = [
            float(entry["score"])
            for entry in rescored_entries
            if self._compatibility_label(query_features, entry["item"]) == "compatible"
        ]
        best_score = float(best_entry["score"])
        best_bonus = float(best_entry.get("article_series_bonus") or 0.0)
        second_score = compatible_scores[1] if len(compatible_scores) > 1 else 0.0
        if best_score < 0.58:
            if len(compatible_scores) == 1:
                if best_score < 0.42 and best_bonus < 0.08:
                    return None
            elif best_score < 0.32 or best_bonus < 0.12:
                return None
        if len(compatible_scores) > 1 and best_score - second_score < 0.03 and best_score < 0.82 and best_bonus < 0.12:
            return None
        return best_entry["item"]

    def _lookup_catalog_item_by_article_series_match(
        self,
        article: str,
        query_features: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        return self._best_article_series_match(
            query_features,
            self._lookup_catalog_items_by_article_series(article, query_features),
            article=article,
        )

    @staticmethod
    def _is_placeholder_input_column_name(column_name: object) -> bool:
        cleaned = str(column_name or "").strip().lower()
        return cleaned.startswith("unnamed:")

    def _looks_like_embedded_header_row(self, row_values: List[object]) -> bool:
        normalized_values = [normalize_header(value).lower() for value in row_values if self._clean_text_value(value)]
        if not normalized_values:
            return False

        query_hits = sum(
            1
            for value in normalized_values
            if (
                "наименован" in value
                or "номенклатур" in value
                or value in {"name", "product name"}
            )
        )
        article_hits = sum(
            1
            for value in normalized_values
            if any(marker in value for marker in ("артикул", "sku", "партномер", "vendor code", "part number"))
        )
        supporting_hits = sum(
            1
            for value in normalized_values
            if (
                "колич" in value
                or "ед." in value
                or "ед изм" in value
                or "стоимость" in value
                or value in {"№", "no", "n"}
            )
        )
        return query_hits > 0 and (article_hits > 0 or supporting_hits >= 2)

    def _promote_embedded_header_row(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        placeholder_columns = [self._is_placeholder_input_column_name(column) for column in df.columns]
        if not placeholder_columns or sum(placeholder_columns) < max(2, len(df.columns) // 2):
            return df

        first_row = df.iloc[0].tolist()
        if not self._looks_like_embedded_header_row(first_row):
            return df

        promoted_headers: List[object] = []
        for index, value in enumerate(first_row):
            header_value = self._clean_text_value(value)
            promoted_headers.append(header_value or df.columns[index])

        promoted = df.iloc[1:].copy()
        promoted.columns = promoted_headers
        promoted.reset_index(drop=True, inplace=True)
        return promoted

    def _score_query_column(self, column_name: object) -> int:
        normalized = normalize_header(column_name).lower()
        if not normalized:
            return 0
        if normalized == "наименование оборудования, материалов и кабелей":
            return 100
        if normalized in {"наименование", "номенклатура", "product name", "name"}:
            return 90
        score = 0
        if "наименован" in normalized:
            score += 60
        if "номенклатур" in normalized:
            score += 55
        if any(marker in normalized for marker in ("оборудован", "материал", "кабел")):
            score += 20
        if "найден" in normalized:
            score -= 100
        return score

    def _score_article_column(self, column_name: object) -> int:
        normalized = normalize_header(column_name).lower()
        if not normalized:
            return 0
        if normalized in {"артикул", "sku", "партномер", "vendor code", "part number"}:
            return 100
        score = 0
        if "артикул" in normalized:
            score += 80
        if "sku" in normalized:
            score += 80
        if "партномер" in normalized or "vendor code" in normalized or "part number" in normalized:
            score += 70
        if "найден" in normalized:
            score -= 100
        return score

    def _resolve_input_columns(self, df: pd.DataFrame) -> Tuple[str, str | None]:
        if df.empty:
            raise ValueError("Input dataframe is empty")

        best_query_column = ""
        best_query_score = -1
        best_article_column = ""
        best_article_score = -1

        for column in df.columns:
            query_score = self._score_query_column(column)
            if query_score > best_query_score:
                best_query_score = query_score
                best_query_column = str(column)

            article_score = self._score_article_column(column)
            if article_score > best_article_score:
                best_article_score = article_score
                best_article_column = str(column)

        if best_query_score <= 0:
            if len(df.columns) > 1:
                best_query_column = str(df.columns[1])
            elif len(df.columns) == 1:
                best_query_column = str(df.columns[0])
            else:
                raise ValueError("Required nomenclature column not found")

        article_column: str | None = None
        if best_article_score > 0 and best_article_column != best_query_column:
            article_column = best_article_column
        elif len(df.columns) > 2:
            candidate = str(df.columns[2])
            if candidate != best_query_column:
                article_column = candidate

        return best_query_column, article_column

    def _current_match_input_context(self) -> Dict[str, Any]:
        local_context = getattr(self, "_match_context_local", None)
        if local_context is None:
            return {}
        payload = getattr(local_context, "payload", None)
        return dict(payload) if isinstance(payload, dict) else {}

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
        return shared_classify_item_type(
            text,
            synonyms=getattr(self, "taxonomy_rules", {}).get("synonyms", {}),
            taxonomy_rules=getattr(self, "taxonomy_rules", {}),
        )

    def _is_disallowed_category_substitution(self, query: str, candidate_name: str) -> bool:
        query_type = self._entity_family(self._classify_item_type(query))
        candidate_type = self._entity_family(self._classify_item_type(candidate_name))
        allowed_cross_family = registry_allowed_cross_family_pairs(getattr(self, "taxonomy_rules", {}))
        if query_type == "patch_cord" and candidate_type == "bulk_twisted_pair":
            return True
        if getattr(self, "match_mode", MATCH_MODE_EXACT) == MATCH_MODE_EXACT:
            if (
                query_type != "other"
                and candidate_type != "other"
                and query_type != candidate_type
                and (query_type, candidate_type) not in allowed_cross_family
            ):
                return True
        return False

    def _entity_family(self, entity_type: str) -> str:
        return entity_family_for_type(entity_type, getattr(self, "taxonomy_rules", {}))

    def _match_strictness_for_query(self, query_features: Dict[str, Any]) -> str:
        return registry_family_strictness(
            query_features.get("entity_type", ""),
            getattr(self, "taxonomy_rules", {}),
            markers=query_features.get("markers", {}) or {},
        )

    def _hard_incompatibility_reason(self, query_features: Dict[str, Any], item: Dict[str, Any]) -> str:
        query_text = self._clean_text_value(query_features.get("original_text"))
        normalized_query = self._normalize_text(query_text)
        candidate_name = self._clean_text_value(item.get("name"))
        candidate_normalized = self._clean_text_value(item.get("normalized_name")) or self._normalize_text(candidate_name)
        candidate_branch = self._normalize_text(self._clean_text_value(item.get("branch_path")))
        query_type = self._entity_family(
            self._clean_text_value(query_features.get("entity_type")) or self._classify_item_type(query_text)
        )
        candidate_type = self._entity_family(
            self._clean_text_value(item.get("entity_type")) or self._classify_item_type(candidate_name)
        )
        query_markers = query_features.get("markers", {}) or {}
        item_markers = dict(item.get("item_markers", {}) or {})
        if candidate_name:
            derived_item_markers = shared_extract_item_markers(
                candidate_name,
                attribute_patterns=getattr(self, "taxonomy_rules", {}).get("attribute_patterns", {}),
                synonyms=getattr(self, "taxonomy_rules", {}).get("synonyms", {}),
            )
            for marker_key, marker_value in derived_item_markers.items():
                if not self._clean_text_value(item_markers.get(marker_key)):
                    item_markers[marker_key] = marker_value

        strong_family_mismatch = {
            "pdu",
            "patch_panel",
            "patch_cord",
            "bulk_twisted_pair",
            "coax",
            "breaker",
            "socket",
            "ats_sts",
            "keystone",
            "rj45_connector",
            "rj45_outlet",
            "floor_box",
            "airflow_blanking_panel",
            "rack_shelf",
            "rack_rail",
            "ground_bar",
            "optical_patch_cord",
            "optical_cross",
            "iec_power_cable",
        }
        allowed_strict_pairs = {
            ("keystone", "rj45_outlet"),
            ("rj45_outlet", "keystone"),
            ("rack_shelf", "rack_rail"),
            ("rack_rail", "rack_shelf"),
        }
        if query_type == "patch_panel" and candidate_type != "patch_panel":
            return "patch_panel_family_mismatch"
        if query_type == "optical_cross":
            if candidate_type != "optical_cross":
                return "optical_cross_family_mismatch"
            optical_markers = ("оптическ", "кросс", "волокон", "odf", "fiber")
            optical_haystack = f"{candidate_normalized} {candidate_branch}".strip()
            if not any(marker in optical_haystack for marker in optical_markers):
                return "optical_cross_family_mismatch"
        if query_type == "ats_sts" and candidate_type == "soft_starter":
            return "ats_sts_vs_soft_starter"
        if query_type == "airflow_blanking_panel":
            if candidate_type != "airflow_blanking_panel":
                return "airflow_blanking_family_mismatch"
            if self._clean_text_value(item_markers.get("airflow")) != "yes":
                return "airflow_blanking_family_mismatch"
        if query_type in strong_family_mismatch and candidate_type and candidate_type != query_type:
            if not (query_type == "sensor" and candidate_type == "sensor") and (
                query_type,
                candidate_type,
            ) not in allowed_strict_pairs:
                return "entity_family_mismatch"

        query_connector = self._clean_text_value(query_markers.get("connector_pair"))
        item_connector = self._clean_text_value(item_markers.get("connector_pair"))
        if query_type == "iec_power_cable":
            if candidate_type != "iec_power_cable":
                return "iec_power_cable_family_mismatch"
            if query_connector and item_connector and query_connector != item_connector:
                return "connector_mismatch"
            if query_connector and not item_connector:
                return "connector_mismatch"
            if any(marker in candidate_normalized for marker in ("pdu", "байпас", "блок розеток")):
                return "iec_vs_power_distribution"

        query_category = self._clean_text_value(query_markers.get("category"))
        item_category = self._clean_text_value(item_markers.get("category"))
        if query_type in {"bulk_twisted_pair", "patch_cord"} and query_category and item_category != query_category:
            return "category_mismatch"
        if query_type in {"patch_panel", "keystone", "rj45_connector"} and query_category:
            if item_category and item_category != query_category:
                return "category_mismatch"
            if not item_category:
                return "category_mismatch"

        query_shielding = self._clean_text_value(query_markers.get("shielding"))
        item_shielding = self._clean_text_value(item_markers.get("shielding"))
        if query_type == "bulk_twisted_pair" and query_shielding:
            if query_shielding == "shielded":
                if item_shielding in {"", "utp"}:
                    return "shielding_mismatch"
            elif item_shielding and item_shielding != query_shielding:
                return "shielding_mismatch"
            if not item_shielding and query_shielding in {"ftp", "sftp", "shielded"}:
                return "shielding_mismatch"
        if query_type in {"patch_panel", "keystone", "rj45_connector"} and query_shielding:
            if item_shielding and item_shielding != query_shielding:
                return "shielding_mismatch"
            if not item_shielding and query_shielding in {"ftp", "sftp", "shielded", "utp"}:
                return "shielding_mismatch"

        query_port_count = self._clean_text_value(query_markers.get("port_count"))
        item_port_count = self._clean_text_value(item_markers.get("port_count"))
        if query_type == "patch_panel" and query_port_count:
            if item_port_count and item_port_count != query_port_count:
                return "port_count_mismatch"
            if not item_port_count:
                return "port_count_mismatch"

        query_cable_environment = self._clean_text_value(query_markers.get("cable_environment"))
        item_cable_environment = self._clean_text_value(item_markers.get("cable_environment"))
        if query_type == "bulk_twisted_pair" and query_cable_environment == "outdoor":
            if item_cable_environment != "outdoor":
                return "cable_environment_mismatch"

        query_designation = self._clean_text_value(query_markers.get("designation_family"))
        item_designation = self._clean_text_value(item_markers.get("designation_family"))
        if query_type in {"bulk_twisted_pair", "cable", "wire"} and query_designation and item_designation:
            if query_designation != item_designation:
                return "designation_family_mismatch"
        if query_type in {"bulk_twisted_pair", "cable", "wire"}:
            query_signature = self._extract_cable_designation_signature(query_text)
            if query_signature:
                candidate_signature = self._extract_cable_designation_signature(candidate_name or candidate_normalized)
                if candidate_signature and not self._cable_designation_signatures_match(query_signature, candidate_signature):
                    return "designation_signature_mismatch"

        if query_type == "ats_sts":
            if not any(
                marker in candidate_normalized
                for marker in (
                    "переключател",
                    "transfer switch",
                    "automatic transfer",
                    "static transfer",
                    "статическ",
                )
            ) and not ("ats" in candidate_normalized and "sts" in candidate_normalized):
                return "ats_sts_mismatch"

        query_sensor = self._clean_text_value(query_markers.get("sensor_kind"))
        item_sensor = self._clean_text_value(item_markers.get("sensor_kind"))
        if query_type == "sensor":
            if query_sensor and item_sensor and query_sensor != item_sensor:
                return "sensor_type_mismatch"
            if query_sensor and not item_sensor:
                return "sensor_type_mismatch"
            if query_sensor in {"temperature", "temperature_humidity"} and any(
                marker in candidate_normalized for marker in ("геркон", "магнитоконтакт")
            ):
                return "sensor_type_mismatch"

        if query_type == "rack_shelf" and self._clean_text_value(item_markers.get("mount_kind")) != "shelf":
            return "rack_accessory_type_mismatch"
        if query_type == "rack_rail" and self._clean_text_value(item_markers.get("mount_kind")) != "rail":
            return "rack_accessory_type_mismatch"
        if query_type == "rack_accessory_strict":
            query_mount = self._clean_text_value(query_markers.get("mount_kind"))
            item_mount = self._clean_text_value(item_markers.get("mount_kind"))
            if query_mount and item_mount and query_mount != item_mount:
                return "rack_accessory_type_mismatch"
            if query_mount and not item_mount:
                return "rack_accessory_type_mismatch"
            query_accessory = self._clean_text_value(query_markers.get("accessory_kind"))
            item_accessory = self._clean_text_value(item_markers.get("accessory_kind"))
            if query_accessory and item_accessory and query_accessory != item_accessory:
                return "rack_accessory_type_mismatch"
            if query_accessory and not item_accessory:
                return "rack_accessory_type_mismatch"
            query_orientation = self._clean_text_value(query_markers.get("orientation_kind"))
            item_orientation = self._clean_text_value(item_markers.get("orientation_kind"))
            if query_orientation and item_orientation and query_orientation != item_orientation:
                return "rack_accessory_orientation_mismatch"
            query_position = self._clean_text_value(query_markers.get("position_kind"))
            item_position = self._clean_text_value(item_markers.get("position_kind"))
            if query_position and item_position and query_position != item_position:
                return "rack_accessory_position_mismatch"
            dimension_mismatch = self._article_dimension_mismatch_reason(query_text, candidate_name or candidate_normalized)
            if dimension_mismatch:
                return dimension_mismatch

        if query_type == "keystone" and candidate_type not in {"keystone", "rj45_outlet"}:
            return "rj45_family_mismatch"
        if query_type == "rj45_connector" and candidate_type != "rj45_connector":
            return "rj45_family_mismatch"
        if query_type == "rj45_outlet" and candidate_type not in {"rj45_outlet", "keystone"}:
            return "rj45_family_mismatch"

        query_component = self._clean_text_value(query_markers.get("component_kind"))
        item_component = self._clean_text_value(item_markers.get("component_kind"))
        if query_type == "keystone":
            if item_component in {"adapter", "faceplate", "outlet", "connector"}:
                return "rj45_component_mismatch"
        if query_type == "rj45_connector":
            if item_component and item_component != "connector":
                return "rj45_component_mismatch"
        if query_type == "rj45_outlet":
            if item_component in {"adapter", "faceplate", "connector"}:
                return "rj45_component_mismatch"
            if query_component == "assembly" and item_component and item_component != "assembly":
                return "rj45_component_mismatch"

        query_installation = self._clean_text_value(query_markers.get("installation_kind"))
        item_installation = self._clean_text_value(item_markers.get("installation_kind"))
        if query_type == "rj45_outlet" and query_installation in {"floor_box", "cable_channel"}:
            if item_installation != query_installation:
                return "rj45_installation_mismatch"

        if query_type == "rj45_outlet":
            query_port_count = self._clean_text_value(query_markers.get("port_count"))
            item_port_count = self._clean_text_value(item_markers.get("port_count"))
            if query_port_count and item_port_count and query_port_count != item_port_count:
                return "port_count_mismatch"

        if query_type == "floor_box":
            if self._clean_text_value(item_markers.get("installation_kind")) != "floor_box":
                return "floor_box_vs_power_item"
            if candidate_type in {"cable", "wire", "iec_power_cable", "pdu"}:
                return "floor_box_vs_power_item"

        if query_type == "ground_bar":
            if "заземл" not in candidate_normalized and "шин" not in candidate_normalized:
                return "grounding_mismatch"

        query_fiber = self._clean_text_value(query_markers.get("fiber_mode"))
        item_fiber = self._clean_text_value(item_markers.get("fiber_mode"))
        if query_type == "optical_patch_cord":
            if candidate_type != "optical_patch_cord":
                return "optical_marker_mismatch"
            if query_connector and item_connector and query_connector != item_connector:
                return "connector_mismatch"
            if query_connector and not item_connector:
                return "connector_mismatch"

        if "zero u" in normalized_query and "zero u" not in candidate_normalized and "zero u" not in candidate_branch:
            return "form_factor_mismatch"

        if self._is_disallowed_category_substitution(query_text, candidate_name):
            return "category_substitution"

        return ""

    def _is_hard_incompatible_match(self, query_features: Dict[str, Any], item: Dict[str, Any]) -> bool:
        return bool(self._hard_incompatibility_reason(query_features, item))

    def _article_match_sanity_reason(self, query_features: Dict[str, Any], item: Dict[str, Any]) -> str:
        hard_reason = self._hard_incompatibility_reason(query_features, item)
        if hard_reason:
            return hard_reason

        query_raw_text = self._clean_text_value(query_features.get("original_text"))
        candidate_raw_text = " ".join(
            filter(
                None,
                [
                    self._clean_text_value(item.get("name")),
                    self._clean_text_value(item.get("normalized_name")),
                    self._clean_text_value(item.get("branch_path")),
                ],
            )
        )
        query_text = self._normalize_text(query_raw_text)
        candidate_text = self._normalize_text(candidate_raw_text)
        if not query_text or not candidate_text:
            return ""

        registry_reason = registry_domain_conflict_reason(
            query_raw_text,
            candidate_raw_text,
            query_family=self._entity_family(query_features.get("entity_type", "")),
            candidate_family=self._entity_family(item.get("entity_type", "")),
            rules=getattr(self, "taxonomy_rules", {}),
        )
        if registry_reason:
            return registry_reason

        lexical_mismatch_rules = (
            (
                "article_query_candidate_domain_mismatch",
                ("лоток", "крышк", "перегород", "пластин", "ответвител", "угол", "кабельн", "gto", "ptce", "sep"),
                ("светильник", "светодиод", "треков", "дсо", "дсп", "дпо", "дку", "свет >"),
            ),
            (
                "article_query_candidate_domain_mismatch",
                ("светильник", "светодиод", "треков", "дсо", "дсп", "дпо", "дку"),
                ("лоток", "крышк", "перегород", "пластин", "ответвител", "угол", "кабельн"),
            ),
            (
                "article_query_candidate_domain_mismatch",
                ("программ", "лиценз", "monitoring", "software"),
                ("камер", "видеокамер", "извещател", "светильник", "шкаф", "кабель", "датчик"),
            ),
            (
                "article_query_candidate_domain_mismatch",
                ("монитор", "display"),
                ("ключ", "dongle", "камера", "извещател", "кабель", "датчик"),
            ),
            (
                "article_query_candidate_domain_mismatch",
                ("держател", "хомут", "скоб"),
                ("колес", "ролик"),
            ),
            (
                "article_query_candidate_domain_mismatch",
                ("лоток", "крышк", "перегород", "ответвител", "пластин", "угол"),
                ("выключател", "автоматическ", "автомат", "optidin", "bm63"),
            ),
            (
                "article_query_candidate_domain_mismatch",
                ("колес", "ролик"),
                ("держател", "хомут", "скоб"),
            ),
        )

        if (query_text.startswith("по ") or " по " in f" {query_text} ") and any(
            token in candidate_text for token in ("камер", "видеокамер", "извещател", "светильник", "шкаф", "кабель")
        ):
            return "article_query_candidate_domain_mismatch"

        for reason, query_tokens, candidate_tokens in lexical_mismatch_rules:
            if any(token in query_text for token in query_tokens) and any(token in candidate_text for token in candidate_tokens):
                return reason

        dimension_reason = self._article_dimension_mismatch_reason(query_raw_text, candidate_raw_text)
        if dimension_reason:
            return dimension_reason

        return ""

    def _normalize_dimension_value(self, value: str) -> str:
        cleaned = self._clean_text_value(value).replace(",", ".")
        if not cleaned:
            return ""
        try:
            numeric = float(cleaned)
        except ValueError:
            return cleaned
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.3f}".rstrip("0").rstrip(".")

    def _canonical_dimension_signature(self, values: Tuple[str, ...]) -> str:
        normalized_values = [self._normalize_dimension_value(value) for value in values if self._normalize_dimension_value(value)]
        if len(normalized_values) == 2:
            return "x".join(sorted(normalized_values, key=lambda item: float(item)))
        if len(normalized_values) == 3:
            numeric_values = [float(item) for item in normalized_values]
            max_index = max(range(len(numeric_values)), key=numeric_values.__getitem__)
            length_value = normalized_values[max_index]
            pair_values = [normalized_values[index] for index in range(3) if index != max_index]
            return "x".join(sorted(pair_values, key=lambda item: float(item)) + [length_value])
        return "x".join(normalized_values)

    def _extract_dimension_signatures(self, text: str) -> Dict[str, set[str]]:
        normalized = self._clean_text_value(text).lower().replace("ё", "е")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        signatures: Dict[str, set[str]] = {
            "pairs": set(),
            "triples": set(),
            "lengths": set(),
            "diameters": set(),
        }
        if not normalized:
            return signatures

        for match in re.finditer(
            r"(\d+(?:[.,]\d+)?)\s*[xх×*/]\s*(\d+(?:[.,]\d+)?)(?:\s*[xх×*/]\s*(\d+(?:[.,]\d+)?))?",
            normalized,
            flags=re.IGNORECASE,
        ):
            values = tuple(group for group in match.groups() if group)
            if len(values) == 2:
                signatures["pairs"].add(self._canonical_dimension_signature(values))
            elif len(values) == 3:
                signatures["triples"].add(self._canonical_dimension_signature(values))

        for match in re.finditer(r"\bl\s*=?\s*(\d+(?:[.,]\d+)?)\b", normalized, flags=re.IGNORECASE):
            signatures["lengths"].add(self._normalize_dimension_value(match.group(1)))
        for match in re.finditer(r"\b(\d+(?:[.,]\d+)?)\s*(?:мм|mm)\b", normalized, flags=re.IGNORECASE):
            signatures["lengths"].add(self._normalize_dimension_value(match.group(1)))
        for match in re.finditer(
            r"\b(?:d|dn|ø)\s*=?\s*(\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?)\b",
            normalized,
            flags=re.IGNORECASE,
        ):
            diameter_value = re.sub(r"\s+", "", match.group(1)).replace(",", ".").replace("–", "-")
            if diameter_value:
                signatures["diameters"].add(diameter_value)

        return signatures

    def _article_dimension_mismatch_reason(self, query_text: str, candidate_text: str) -> str:
        query_signatures = self._extract_dimension_signatures(query_text)
        candidate_signatures = self._extract_dimension_signatures(candidate_text)

        if query_signatures["triples"] and candidate_signatures["triples"]:
            if not (query_signatures["triples"] & candidate_signatures["triples"]):
                return "article_query_candidate_dimension_mismatch"

        if query_signatures["pairs"] and candidate_signatures["pairs"]:
            if not (query_signatures["pairs"] & candidate_signatures["pairs"]):
                return "article_query_candidate_dimension_mismatch"

        if query_signatures["lengths"] and candidate_signatures["lengths"]:
            if not (query_signatures["lengths"] & candidate_signatures["lengths"]):
                return "article_query_candidate_dimension_mismatch"

        if query_signatures["diameters"] and candidate_signatures["diameters"]:
            if not (query_signatures["diameters"] & candidate_signatures["diameters"]):
                return "article_query_candidate_dimension_mismatch"

        return ""

    def _compatibility_penalty(self, query_features: Dict[str, Any], item: Dict[str, Any]) -> float:
        if self._is_hard_incompatible_match(query_features, item):
            return 0.6

        penalty = 0.0
        query_markers = query_features.get("markers", {}) or {}
        item_markers = item.get("item_markers", {}) or {}

        key_pairs = (
            ("connector_pair", 0.28),
            ("sensor_kind", 0.28),
            ("mount_kind", 0.22),
            ("accessory_kind", 0.26),
            ("orientation_kind", 0.18),
            ("position_kind", 0.18),
            ("installation_kind", 0.22),
            ("shielding", 0.24),
            ("cable_environment", 0.24),
            ("fiber_mode", 0.22),
            ("duplex", 0.12),
            ("category", 0.18),
            ("designation_family", 0.3),
        )
        for key, weight in key_pairs:
            query_value = self._clean_text_value(query_markers.get(key))
            item_value = self._clean_text_value(item_markers.get(key))
            if query_value and item_value and query_value != item_value:
                penalty += weight

        query_length = self._clean_text_value(query_markers.get("length_m"))
        item_length = self._clean_text_value(item_markers.get("length_m"))
        if query_length and item_length and query_length != item_length:
            penalty += 0.08

        query_rack = self._clean_text_value(query_markers.get("rack_unit"))
        item_rack = self._clean_text_value(item_markers.get("rack_unit"))
        if query_rack and item_rack and query_rack != item_rack:
            penalty += 0.12

        return penalty

    def _compatibility_label(self, query_features: Dict[str, Any], item: Dict[str, Any]) -> str:
        if self._is_hard_incompatible_match(query_features, item):
            return "incompatible"
        if self._compatibility_penalty(query_features, item) >= 0.2:
            return "weakly_compatible"
        return "compatible"

    def _explain_incompatibility(self, query_features: Dict[str, Any], item: Dict[str, Any]) -> str:
        reason = self._hard_incompatibility_reason(query_features, item)
        if reason:
            return reason
        if self._compatibility_penalty(query_features, item) >= 0.2:
            return "weak_marker_match"
        return ""

    def _has_any_compatible_candidates(self, query_features: Dict[str, Any], scored_entries: List[Dict[str, Any]]) -> bool:
        return any(not self._is_hard_incompatible_match(query_features, entry["item"]) for entry in scored_entries)

    def _best_compatible_local_entry(
        self,
        query_features: Dict[str, Any],
        scored_entries: List[Dict[str, Any]],
        allow_weak: bool = False,
    ) -> Dict[str, Any] | None:
        for entry in scored_entries:
            label = self._compatibility_label(query_features, entry["item"])
            if label == "compatible":
                return entry
            if allow_weak and label == "weakly_compatible":
                return entry
        return None

    def _is_strict_fallback_allowed(self, query_features: Dict[str, Any], item: Dict[str, Any]) -> bool:
        if self._compatibility_label(query_features, item) != "compatible":
            return False

        strictness = self._match_strictness_for_query(query_features)
        if strictness != "strict":
            return True

        query_family = self._entity_family(query_features.get("entity_type", ""))
        candidate_family = self._entity_family(item.get("entity_type", ""))
        allowed_pairs = registry_allowed_cross_family_pairs(getattr(self, "taxonomy_rules", {}))
        if registry_family_requires_same_family_gate(query_family, getattr(self, "taxonomy_rules", {})):
            return candidate_family == query_family
        if candidate_family == query_family:
            return True
        return (query_family, candidate_family) in allowed_pairs

    def _is_gemini_result_family_valid(self, query_features: Dict[str, Any], item: Dict[str, Any]) -> bool:
        query_family = self._entity_family(query_features.get("entity_type", ""))
        candidate_family = self._entity_family(item.get("entity_type", ""))
        allowed_pairs = registry_allowed_cross_family_pairs(getattr(self, "taxonomy_rules", {}))
        if registry_family_requires_same_family_gate(query_family, getattr(self, "taxonomy_rules", {})):
            return candidate_family == query_family
        if (query_family, candidate_family) in allowed_pairs:
            return True
        return not self._is_hard_incompatible_match(query_features, item)

    def _typed_candidate_pool(self, query_text: str, query_features: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        strictness = self._match_strictness_for_query(query_features)
        if strictness == "generic":
            return []

        entity_family = self._entity_family(query_features.get("entity_type", ""))
        if self._should_use_rack_tray_resolver(query_features):
            return self._typed_candidate_pool_for_rack_tray(query_text, query_features, limit)
        typed_limit = min(limit, 300)
        branch_paths = [entry["path"] for entry in query_features.get("ranked_branches", []) if entry.get("path")]
        typed_pool = []
        seen: set[int] = set()
        supplemented = 0

        def _matches_typed_family(item: Dict[str, Any]) -> bool:
            item_family = self._entity_family(item.get("entity_type", ""))
            if entity_family == "patch_panel":
                if item_family == "patch_panel":
                    return True
                search_text = self._normalize_text(
                    f"{self._clean_text_value(item.get('name'))} {self._clean_text_value(item.get('branch_path'))}"
                )
                return any(token in search_text for token in ("патч", "коммутац", "панел"))
            if entity_family == "optical_cross":
                if item_family == "optical_cross":
                    return True
                search_text = self._normalize_text(
                    f"{self._clean_text_value(item.get('name'))} {self._clean_text_value(item.get('branch_path'))}"
                )
                return any(token in search_text for token in ("оптическ", "кросс", "волокон", "fiber", "odf"))
            if entity_family == "ats_sts":
                if item_family == "ats_sts":
                    return True
                search_text = self._normalize_text(
                    f"{self._clean_text_value(item.get('name'))} {self._clean_text_value(item.get('branch_path'))}"
                )
                if "soft starter" in search_text or ("плавн" in search_text and "пуск" in search_text):
                    return False
                return (
                    any(token in search_text for token in ("переключател", "transfer switch", "automatic transfer"))
                    or ("статическ" in search_text and "переключател" in search_text)
                    or ("ats" in search_text and "sts" in search_text)
                )
            if entity_family == "airflow_blanking_panel":
                if item_family == "airflow_blanking_panel":
                    return True
                search_text = self._normalize_text(
                    f"{self._clean_text_value(item.get('name'))} {self._clean_text_value(item.get('branch_path'))}"
                )
                return (
                    "заглуш" in search_text
                    and (
                        ("поток" in search_text and "воздух" in search_text)
                        or any(token in search_text for token in ("airflow", "blanking panel", "свободных юнит"))
                    )
                    and "модул" not in search_text
                    and "щитк" not in search_text
                )
            if entity_family == "bulk_twisted_pair":
                if item_family != "bulk_twisted_pair":
                    return False
                query_markers = query_features.get("markers", {}) or {}
                item_markers = item.get("item_markers", {}) or {}
                query_category = self._clean_text_value(query_markers.get("category"))
                item_category = self._clean_text_value(item_markers.get("category"))
                if query_category and item_category and item_category != query_category:
                    return False
                query_shielding = self._clean_text_value(query_markers.get("shielding"))
                item_shielding = self._clean_text_value(item_markers.get("shielding"))
                if query_shielding and item_shielding and item_shielding != query_shielding:
                    return False
                query_environment = self._clean_text_value(query_markers.get("cable_environment"))
                item_environment = self._clean_text_value(item_markers.get("cable_environment"))
                if query_environment == "outdoor" and item_environment and item_environment != "outdoor":
                    return False
                return True
            if entity_family == "rack_accessory_strict":
                if item_family != "rack_accessory_strict":
                    return False
                return not self._is_hard_incompatible_match(query_features, item)
            if entity_family and item_family and item_family != entity_family:
                return False
            return True

        def _log_and_return() -> List[Dict[str, Any]]:
            logger.info(
                "🧠 Typed candidate pool: query=%s family=%s typed_candidates=%s supplemented=%s",
                query_text[:120],
                entity_family or "other",
                len(typed_pool),
                supplemented,
            )
            return typed_pool

        if self._should_use_whole_category_retrieval(query_features):
            category_key, category_candidates, _elapsed_ms = self._duckdb_category_candidates(query_features)
            query_features["query_category_key"] = category_key
            for item in category_candidates:
                if not _matches_typed_family(item):
                    continue
                row_idx = int(item.get("row_idx", -1))
                if row_idx in seen:
                    continue
                typed_pool.append(item)
                seen.add(row_idx)
            return _log_and_return()

        for item in self._collect_branch_candidates(
            branch_paths,
            limit=max(typed_limit * 2, typed_limit),
            query_features=query_features,
        ):
            if not _matches_typed_family(item):
                continue
            row_idx = int(item.get("row_idx", -1))
            if row_idx in seen:
                continue
            typed_pool.append(item)
            seen.add(row_idx)
            if len(typed_pool) >= typed_limit:
                return _log_and_return()

        general_candidates = self._select_candidates(query_text, limit=max(limit * 2, typed_limit))
        for item in general_candidates:
            if not _matches_typed_family(item):
                continue
            row_idx = int(item.get("row_idx", -1))
            if row_idx in seen:
                continue
            typed_pool.append(item)
            seen.add(row_idx)
            supplemented += 1
            if len(typed_pool) >= typed_limit:
                break
        return _log_and_return()

    def _is_assembly_mode_enabled(self) -> bool:
        return getattr(self, "match_mode", MATCH_MODE_EXACT) == MATCH_MODE_ASSEMBLY

    def _supports_assembly_fallback(self, query_features: Dict[str, Any]) -> bool:
        return (
            self._is_assembly_mode_enabled()
            and self._clean_text_value(query_features.get("row_type")) == "item"
            and self._entity_family(query_features.get("entity_type", "")) == "patch_cord"
        )

    def _is_patch_cord_assembly_candidate(self, query_features: Dict[str, Any], item: Dict[str, Any]) -> bool:
        item_family = self._entity_family(item.get("entity_type", ""))
        if item_family not in {"bulk_twisted_pair", "cable"}:
            return False

        haystack = self._candidate_secondary_filter_haystack(item)
        if not any(token in haystack for token in ("patch", "патч")):
            return False
        if any(token in haystack for token in ("оптическ", "fiber", "волокон", "коакси", "rg-")):
            return False

        query_markers = query_features.get("markers", {}) or {}
        item_markers = item.get("item_markers", {}) or {}

        query_category = self._clean_text_value(query_markers.get("category"))
        item_category = self._clean_text_value(item_markers.get("category"))
        if query_category:
            if item_category and item_category != query_category:
                return False
            if not item_category and not re.search(rf"\b{re.escape(query_category)}\b", haystack, flags=re.IGNORECASE):
                return False

        query_shielding = self._clean_text_value(query_markers.get("shielding"))
        item_shielding = self._clean_text_value(item_markers.get("shielding"))
        shielding_patterns = {
            "utp": (
                r"(?<![a-z])u\s*/\s*utp\b",
                r"(?<![a-z])u\s+utp\b",
                r"неэкранир",
                r"(?<![a-z/])utp\b",
            ),
            "ftp": (
                r"(?<![a-z])f\s*/\s*utp\b",
                r"(?<![a-z])f\s+utp\b",
                r"(?<![a-z])ftp\b",
            ),
            "sftp": (
                r"(?<![a-z])s\s*/\s*ftp\b",
                r"(?<![a-z])sftp\b",
                r"(?<![a-z])sf\s*/\s*utp\b",
                r"(?<![a-z])f\s*/\s*ftp\b",
            ),
            "shielded": (
                r"(?<![a-z])s\s*/\s*ftp\b",
                r"(?<![a-z])sftp\b",
                r"(?<![a-z])sf\s*/\s*utp\b",
                r"(?<![a-z])f\s*/\s*ftp\b",
                r"(?<![a-z])f\s+utp\b",
                r"(?<![a-z])ftp\b",
                r"экранир",
            ),
        }
        if query_shielding:
            if query_shielding == "shielded":
                if item_shielding:
                    if item_shielding not in {"ftp", "sftp", "shielded"}:
                        return False
                elif not any(re.search(pattern, haystack, flags=re.IGNORECASE) for pattern in shielding_patterns["shielded"]):
                    return False
            elif item_shielding:
                if item_shielding != query_shielding:
                    return False
            elif not any(
                re.search(pattern, haystack, flags=re.IGNORECASE)
                for pattern in shielding_patterns.get(query_shielding, ())
            ):
                return False

        return True

    def _assembly_candidate_pool(self, query_features: Dict[str, Any], *, limit: int = 160) -> List[Dict[str, Any]]:
        if not self._supports_assembly_fallback(query_features):
            return []

        query_markers = query_features.get("markers", {}) or {}
        limit = max(20, min(int(limit), 400))
        candidates: List[Dict[str, Any]]

        if self._uses_duckdb_query_backend():
            branch_column = self._quote_sql_identifier("search_branch_path")
            entity_column = self._quote_sql_identifier("search_entity_type")
            name_column = self._quote_sql_identifier("search_normalized_name")
            filters = [
                f"({branch_column} = ? OR {branch_column} LIKE ?)",
                f"{entity_column} IN (?, ?)",
                f"({name_column} LIKE ? OR {name_column} LIKE ?)",
            ]
            params: List[Any] = [
                "электрика > кабели",
                f"электрика > кабели{BRANCH_PATH_SEPARATOR}%",
                "bulk_twisted_pair",
                "cable",
                "%patch%",
                "%патч%",
            ]
            query_category = self._clean_text_value(query_markers.get("category"))
            if query_category:
                filters.append(f"{name_column} LIKE ?")
                params.append(f"%{query_category}%")
            candidates = self._duckdb_fetch_items(
                where_sql=" AND ".join(filters),
                params=params,
                limit=max(limit * 3, 120),
            )
        else:
            candidates = self._collect_branch_candidates(["электрика > кабели"], limit=max(limit * 3, 120))

        filtered: List[Dict[str, Any]] = []
        seen: set[int] = set()
        for item in candidates:
            if not self._is_patch_cord_assembly_candidate(query_features, item):
                continue
            row_idx = int(item.get("row_idx", -1))
            if row_idx in seen:
                continue
            filtered.append(item)
            seen.add(row_idx)
            if len(filtered) >= limit:
                break
        return filtered

    def _assembly_scored_entries(self, query_features: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self._supports_assembly_fallback(query_features):
            return []
        candidates = self._assembly_candidate_pool(
            query_features,
            limit=max(int(getattr(self, "gemini_shortlist_limit", 96)) * 2, 120),
        )
        return self._score_candidates_locally(query_features, candidates)

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
            taxonomy_rules=getattr(self, "taxonomy_rules", {}),
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
        self.catalog = None
        self.catalog_dict = {}
        self.catalog_normalized_dict = {}
        self.catalog_article_dict = {}
        self.catalog_items = []
        self.token_index = {}
        self.group_index = {}
        self.token_idf = {}
        self.branch_index = {}
        self.branch_prefix_index = {}
        self.branch_token_index = {}
        self.catalog_row_count = 0
        token_to_items: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        token_doc_frequency: Counter[str] = Counter()
        sample_lines: List[str] = []
        saw_name_column = False
        saw_name_value = False
        row_idx = 0
        chunksize = self._catalog_load_chunksize()
        logger.info("Matcher catalog load config: chunksize=%s selective_columns=yes", chunksize)

        source_path = Path(self.db_csv_path)
        if self._uses_duckdb_query_backend():
            self.catalog_storage_backend = "duckdb"
            self.retrieval_backend = "duckdb"
            self.retrieval_mode = "whole_category"
            self._duckdb_path = str(source_path)
            frame = self._duckdb_fetch_frame(f"SELECT * FROM {SEARCH_CATALOG_TABLE} LIMIT 300")
            for row in frame.to_dict(orient="records"):
                item = self._catalog_row_to_item(row)
                if item is None:
                    continue
                sample_lines.append(
                    f"• {item['name']} | Артикул: {item['article'] or 'N/A'} | "
                    f"Цена: {item['price'] if item['price'] is not None else 'N/A'}"
                )
            count_frame = self._duckdb_fetch_frame(f"SELECT COUNT(*) AS rows_total FROM {SEARCH_CATALOG_TABLE}")
            if not count_frame.empty:
                self.catalog_row_count = int(count_frame.iloc[0].get("rows_total", 0))
            self.catalog_text = "\n".join(sample_lines[:300])
            logger.info(
                "Loaded catalog metadata via DuckDB: rows=%s retrieval_backend=%s retrieval_mode=%s",
                self.catalog_row_count,
                self.retrieval_backend,
                self.retrieval_mode,
            )
            return
        if is_search_catalog_path(source_path):
            chunk_iter = iter_search_catalog_chunks(source_path, chunksize=chunksize)
        else:
            chunk_iter = pd.read_csv(
                self.db_csv_path,
                sep=";",
                encoding="utf-8",
                low_memory=False,
                chunksize=chunksize,
                usecols=self._should_load_catalog_column,
            )

        for chunk in chunk_iter:
            chunk = canonicalize_catalog_columns(chunk, create_missing=True)
            if CANONICAL_NAME_COLUMN in chunk.columns:
                saw_name_column = True

            for _, row in chunk.iterrows():
                item = self._catalog_row_to_item(row.to_dict(), row_idx=row_idx)
                if item is None:
                    continue
                saw_name_value = True
                self.catalog_dict.setdefault(item["name_lc"], item)
                if item["normalized_name"] and item["normalized_name"] not in self.catalog_normalized_dict:
                    self.catalog_normalized_dict[item["normalized_name"]] = item
                article_key = self._normalize_article_lookup_value(item["article"])
                if article_key and article_key not in self.catalog_article_dict:
                    self.catalog_article_dict[article_key] = item

                self.catalog_items.append(item)
                for token in item["tokens"]:
                    token_to_items[token].append(item)
                for token in set(item["tokens"]):
                    token_doc_frequency[token] += 1
                if len(sample_lines) < max(300, int(getattr(self, "catalog_sample_items", 500))):
                    sample_lines.append(
                        f"• {item['name']} | Артикул: {item['article'] or 'N/A'} | "
                        f"Цена: {item['price'] if item['price'] is not None else 'N/A'}"
                    )
                row_idx += 1
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
                    item_markers = {}
                derived_markers = shared_extract_item_markers(
                    combined_text,
                    attribute_patterns=getattr(self, "taxonomy_rules", {}).get("attribute_patterns", {}),
                    synonyms=getattr(self, "taxonomy_rules", {}).get("synonyms", {}),
                )
                for marker_key, marker_value in derived_markers.items():
                    if not self._clean_text_value(item_markers.get(marker_key)):
                        item_markers[marker_key] = marker_value

                item = {
                    "name": name,
                    "name_lc": name.lower(),
                    "normalized_name": normalized_name,
                    "article": article,
                    "price": price,
                    "row_idx": row_idx,
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
                if len(sample_lines) < max(300, int(getattr(self, "catalog_sample_items", 500))):
                    sample_lines.append(
                        f"• {name} | Артикул: {article or 'N/A'} | Цена: {price if price is not None else 'N/A'}"
                    )
                row_idx += 1

        if not saw_name_column or not saw_name_value:
            raise ValueError("Catalog name column cannot be resolved")

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
        self.catalog_text = "\n".join(sample_lines[:300])
        self.catalog_row_count = len(self.catalog_items)
        self.catalog_storage_backend = "memory"
        self.retrieval_backend = "memory"
        self.retrieval_mode = "legacy_limited"
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
        if self._uses_duckdb_query_backend():
            candidates, _elapsed_ms = self._duckdb_heuristic_candidates(
                query,
                limit=max(1, int(getattr(self, "retrieval_candidates_limit", 1200))),
            )
            return candidates
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
        context = self._current_match_input_context()
        context_article = self._normalize_article_lookup_value(
            context.get("query_article") or context.get("input_article") or ""
        )
        if context_article:
            value = f"{value}||article:{context_article}"
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    def _rank_candidates(
        self,
        query: str,
        limit: int = 40,
        candidate_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Tuple[float, Dict[str, Any]]]:
        normalized_query = self._normalize_text(query)
        query_tokens = self._tokenize(normalized_query)
        if candidate_pool is None and self._uses_duckdb_query_backend():
            retrieval_limit = max(limit * 20, int(getattr(self, "retrieval_candidates_limit", 1200)))
            heuristic_pool, _elapsed_ms = self._duckdb_heuristic_candidates(query, limit=retrieval_limit)
            pool = heuristic_pool
        else:
            pool = candidate_pool if candidate_pool is not None else getattr(self, "catalog_items", [])
        if not pool:
            return []

        if candidate_pool is None and not self._uses_duckdb_query_backend():
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
            "compatibility_status": "compatible",
            "incompatibility_reason": "",
            "gemini_shortlist_count": 0,
            "gemini_visible_candidates": 0,
            "gemini_truncated_candidates": 0,
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
        if normalized in {
            "скс",
            "лвс",
            "оборудование",
            "сетевая инфраструктура",
            "система кабельных лотков",
            "крепеж и аксессуары",
            "наименование оборудования материалов и кабелей",
        }:
            return "section"
        patterns = getattr(self, "taxonomy_rules", {}).get("section_row_patterns", [])
        for pattern in patterns:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return "section"
        tokens = self._tokenize(normalized)
        if normalized.startswith("раздел"):
            return "section"
        if normalized.startswith("наименование ") and len(tokens) <= 8:
            return "section"
        if len(tokens) <= 4 and not re.search(r"\d", normalized):
            for token in (
                "шкафы",
                "кабели",
                "коммутация",
                "электрика",
                "датчики",
                "свет",
                "аксессуары",
                "оборудование",
            ):
                if normalized.startswith(token):
                    return "section"
        return "item"

    def _extract_query_features(self, query: str) -> Dict[str, Any]:
        original = self._clean_text_value(query)
        normalized = self._normalize_text(original)
        tokens = self._tokenize(normalized)
        markers = shared_extract_item_markers(
            original,
            attribute_patterns=getattr(self, "taxonomy_rules", {}).get("attribute_patterns", {}),
            synonyms=getattr(self, "taxonomy_rules", {}).get("synonyms", {}),
        )
        registry_match = classify_entity_type_from_registry(
            original,
            rules=getattr(self, "taxonomy_rules", {}),
            markers=markers,
        )
        entity_type = self._classify_item_type(original)
        entity_family = self._entity_family(entity_type)
        family_confidence = 0.35 if entity_family in {"", "other", "cable", "wire", "coax", "rack", "sensor"} else 0.72
        if registry_match is not None:
            registry_entity_type = self._clean_text_value(registry_match.get("entity_type")) or entity_type
            registry_family = self._entity_family(registry_entity_type)
            registry_confidence = float(registry_match.get("confidence") or family_confidence)
            should_apply_registry = (
                registry_family == entity_family
                or entity_family in {"", "other"}
                and registry_confidence >= 0.72
                or entity_family in {"cable", "wire", "coax", "rack", "sensor"}
                and registry_confidence >= 0.62
            )
            if should_apply_registry:
                entity_type = registry_entity_type
                entity_family = registry_family
                family_confidence = registry_confidence
        features: Dict[str, Any] = {
            "original_text": original,
            "normalized_text": normalized,
            "tokens": tokens,
            "row_type": self._detect_query_row_type(original),
            "entity_type": entity_type,
            "family_confidence": family_confidence,
            "attributes": dict(markers),
            "markers": dict(markers),
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

        current_matches = re.finditer(r"(\d+(?:[.,]\d+)?)\s*а\b", normalized)
        for current_match in current_matches:
            prefix = normalized[max(0, current_match.start() - 16) : current_match.start()]
            if re.search(r"(?:cat|кат|категор(?:ия|ии)?)\s*$", prefix, flags=re.IGNORECASE):
                continue
            features["attributes"]["current_a"] = current_match.group(1).replace(",", ".")
            break

        if "zero u" in normalized:
            features["attributes"]["zero_u"] = "yes"
        if features["attributes"].get("rack_unit") == "1":
            features["attributes"]["rack_1u"] = "yes"
        if "19 inch" in normalized:
            features["attributes"]["rack_size"] = "19 inch"
            features["attributes"]["rack_mount_19"] = "yes"

        branch_hint = self._derive_branch_from_text(original)
        if branch_hint and branch_hint != "прочее":
            features["branch_hint"] = branch_hint
        features["markers"] = dict(features["attributes"])
        return features

    def _detect_query_row_type(self, text: str) -> str:
        return shared_detect_query_row_type(text, getattr(self, "taxonomy_rules", {}))

    def _extract_query_article_from_text(self, query: str) -> str:
        return shared_extract_query_article_from_text(query)

    def _extract_query_features(self, query: str) -> Dict[str, Any]:
        parsed = shared_parse_query_spec(query, taxonomy_rules=getattr(self, "taxonomy_rules", {}))
        features = parsed.to_feature_dict()
        if features.get("branch_hint") == "прочее":
            features["branch_hint"] = ""
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

        if self._uses_duckdb_query_backend():
            for path in self._default_branch_paths_for_family(query_features):
                if path and path != "прочее":
                    scores[path] += 1.8
            if not scores:
                fallback_paths = self._default_branch_paths_for_family(query_features)
                return [{"path": path, "score": 1.0} for path in fallback_paths if path]
            ranked_duckdb = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
            return [{"path": path, "score": float(score)} for path, score in ranked_duckdb[:TOP_BRANCH_COUNT]]

        branch_token_index = getattr(self, "branch_token_index", {}) or {}
        token_idf = getattr(self, "token_idf", {}) or {}
        for token in set(tokens):
            for branch in branch_token_index.get(token, []):
                scores[branch] += 0.45 * float(token_idf.get(token, 1.0))

        entity_type = self._entity_family(query_features.get("entity_type", ""))
        for branch in getattr(self, "branch_index", {}) or {}:
            branch_norm = self._normalize_text(branch)
            if entity_type == "pdu" and "pdu" in branch_norm:
                scores[branch] += 1.2
            elif entity_type == "rack" and "шкаф" in branch_norm:
                scores[branch] += 1.0
            elif entity_type == "patch_panel" and "патч панел" in branch_norm:
                scores[branch] += 1.2
            elif entity_type in {"patch_cord", "optical_patch_cord"} and "патч корд" in branch_norm:
                scores[branch] += 1.2
            elif entity_type in {"keystone", "rj45_connector", "rj45_outlet"} and "модул" in branch_norm:
                scores[branch] += 1.0
            elif entity_type in {"rack_accessory_strict", "rack_shelf", "rack_rail"} and "аксессуар" in branch_norm:
                scores[branch] += 0.9
            elif entity_type == "floor_box" and "люч" in branch_norm:
                scores[branch] += 1.1
            elif entity_type == "sensor" and "датчик" in branch_norm:
                scores[branch] += 1.0
            elif entity_type == "ats_sts" and "ats" in branch_norm:
                scores[branch] += 1.0
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

    def _collect_branch_candidates(
        self,
        branches: List[Any],
        limit: int | None = None,
        query_features: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
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

        if self._uses_duckdb_query_backend():
            if not branch_paths:
                return []
            branch_column = self._quote_sql_identifier("search_branch_path")
            clauses: List[str] = []
            params: List[Any] = []
            for path in branch_paths:
                clauses.append(f"({branch_column} = ? OR {branch_column} LIKE ?)")
                params.extend([path, f"{path}{BRANCH_PATH_SEPARATOR}%"])
            where_clauses = ["(" + " OR ".join(clauses) + ")"]
            query_family = self._entity_family((query_features or {}).get("entity_type", ""))
            family_types = sorted(self._entity_types_for_family((query_features or {}).get("entity_type", "")))
            if family_types and query_family not in {"", "other"}:
                entity_column = self._quote_sql_identifier("search_entity_type")
                placeholders = ", ".join("?" for _ in family_types)
                where_clauses.append(f"{entity_column} IN ({placeholders})")
                params.extend(family_types)
            duckdb_limit = max(1, int(limit)) if limit is not None else None
            return self._duckdb_fetch_items(
                where_sql=" AND ".join(where_clauses),
                params=params,
                limit=duckdb_limit,
            )

        limit = max(1, int(limit or getattr(self, "retrieval_candidates_limit", 3000)))
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
        item_markers = item.get("item_markers", {}) or {}

        if self._entity_family(query_features.get("entity_type", "")) == self._entity_family(item.get("entity_type", "")):
            score += 0.08

        for key, bonus in (
            ("connector_pair", 0.18),
            ("sensor_kind", 0.18),
            ("mount_kind", 0.15),
            ("installation_kind", 0.15),
            ("fiber_mode", 0.15),
            ("category", 0.12),
        ):
            query_value = self._clean_text_value(attributes.get(key))
            item_value = self._clean_text_value(item_markers.get(key))
            if query_value and item_value and query_value == item_value:
                score += bonus

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

        score -= self._compatibility_penalty(query_features, item)
        return max(0.0, min(0.999, score))

    def _score_candidates_locally(self, query_features: Dict[str, Any], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        ranked = self._rank_candidates(
            query_features.get("original_text", ""),
            limit=max(80, min(len(candidates), int(getattr(self, "gemini_shortlist_limit", 96)) * 2)),
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

    @staticmethod
    def _top_branch_gap(ranked_branches: List[Dict[str, Any]]) -> float:
        if len(ranked_branches) > 1:
            return float(ranked_branches[0]["score"]) - float(ranked_branches[1]["score"])
        if ranked_branches:
            return float(ranked_branches[0]["score"])
        return 0.0

    def _is_weak_shortlist(self, scored_entries: List[Dict[str, Any]], ranked_branches: List[Dict[str, Any]]) -> bool:
        if not scored_entries:
            return True
        best_score = float(scored_entries[0]["score"])
        if len(scored_entries) >= 3 or best_score >= 0.45:
            return False
        branch_scores_present = bool(ranked_branches and float(ranked_branches[0].get("score", 0.0)) > 0.0)
        top_branch_gap = self._top_branch_gap(ranked_branches)
        return (not branch_scores_present) or top_branch_gap < 0.05

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
        compatibility_status: str = "compatible",
        incompatibility_reason: str = "",
        gemini_shortlist_count: int = 0,
        gemini_visible_candidates: int = 0,
        gemini_truncated_candidates: int = 0,
        gemini_model: str = "",
        gemini_result_status: str = "",
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
            "compatibility_status": compatibility_status,
            "incompatibility_reason": incompatibility_reason,
            "gemini_shortlist_count": int(gemini_shortlist_count),
            "gemini_visible_candidates": int(gemini_visible_candidates),
            "gemini_truncated_candidates": int(gemini_truncated_candidates),
            "gemini_model": gemini_model,
            "gemini_result_status": gemini_result_status,
        }

    def _build_missing_result(
        self,
        query: str,
        reason: str,
        error: str | None = None,
        alternatives: str = "",
        compatibility_status: str = "unresolved_no_compatible_candidates",
        incompatibility_reason: str = "",
        gemini_shortlist_count: int = 0,
        gemini_visible_candidates: int = 0,
        gemini_truncated_candidates: int = 0,
        gemini_model: str = "",
        gemini_result_status: str = "",
    ) -> Dict[str, Any]:
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
            "compatibility_status": compatibility_status,
            "incompatibility_reason": incompatibility_reason,
            "gemini_shortlist_count": int(gemini_shortlist_count),
            "gemini_visible_candidates": int(gemini_visible_candidates),
            "gemini_truncated_candidates": int(gemini_truncated_candidates),
            "gemini_model": gemini_model,
            "gemini_result_status": gemini_result_status,
        }

    def _diagnostic_candidate_from_item(
        self,
        query_features: Dict[str, Any],
        item: Dict[str, Any],
        *,
        score: float | None = None,
        compatibility_label: str | None = None,
        incompatibility_reason: str | None = None,
    ) -> Dict[str, Any]:
        label = compatibility_label or self._compatibility_label(query_features, item)
        reason = incompatibility_reason or (
            "" if label == "compatible" else self._explain_incompatibility(query_features, item)
        )
        snapshot = {
            "name": self._clean_text_value(item.get("name")),
            "article": self._clean_text_value(item.get("article")),
            "family": self._entity_family(item.get("entity_type", "")),
            "compatibility": label,
            "reason": reason,
        }
        if score is not None:
            snapshot["score"] = round(float(score), 4)
        return snapshot

    def _diagnostic_candidates_from_entries(
        self,
        query_features: Dict[str, Any],
        entries: List[Dict[str, Any]],
        *,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        snapshots: List[Dict[str, Any]] = []
        for entry in entries[:limit]:
            item = entry.get("item")
            if not isinstance(item, dict):
                continue
            label = self._compatibility_label(query_features, item)
            reason = "" if label == "compatible" else self._explain_incompatibility(query_features, item)
            snapshots.append(
                self._diagnostic_candidate_from_item(
                    query_features,
                    item,
                    score=float(entry.get("score", 0.0)),
                    compatibility_label=label,
                    incompatibility_reason=reason,
                )
            )
        return snapshots

    def _attach_diagnostic_trace(
        self,
        result: Dict[str, Any],
        *,
        query_text: str,
        query_article: str = "",
        article_source: str = "none",
        article_lookup_hit: bool = False,
        article_lookup_conflict: bool = False,
        query_features: Dict[str, Any] | None,
        stage_of_failure: str,
        reason_code: str,
        trace_steps: List[Dict[str, Any]],
        pipeline_counts: Dict[str, Any],
        candidate_snapshots: Dict[str, Any],
        gemini_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        reason_code_value = str(reason_code or "resolved").strip() or "resolved"
        row_type = str((query_features or {}).get("row_type") or "")
        entity_type = str((query_features or {}).get("entity_type") or "")
        query_family = self._entity_family(entity_type)
        resolver_source = str(result.get("resolution_source") or "")
        resolver_path = str(
            result.get("resolver_path")
            or (query_features or {}).get("active_resolver_path")
            or self._resolver_path_for_source(resolver_source)
        )
        diagnostic_trace = {
            "query_text": self._clean_text_value(query_text),
            "query_article": self._clean_text_value(query_article),
            "article_source": self._clean_text_value(article_source) or "none",
            "article_lookup_hit": bool(article_lookup_hit),
            "article_lookup_conflict": bool(article_lookup_conflict),
            "article_validation_status": self._clean_text_value((query_features or {}).get("article_validation_status")),
            "parser_source": self._clean_text_value((query_features or {}).get("parser_source")) or "legacy",
            "parsed_article_in_text": self._clean_text_value((query_features or {}).get("extracted_article")),
            "designation_signature": self._clean_text_value((query_features or {}).get("designation_signature")),
            "row_type": row_type,
            "entity_type": entity_type,
            "query_family": query_family,
            "family_confidence": float((query_features or {}).get("family_confidence") or 0.0),
            "retrieval_mode": str((pipeline_counts or {}).get("retrieval_mode") or getattr(self, "retrieval_mode", "")),
            "retrieval_backend": str((pipeline_counts or {}).get("retrieval_backend") or getattr(self, "retrieval_backend", "")),
            "resolution_source": resolver_source,
            "resolver_name": resolver_source,
            "resolver_path": resolver_path,
            "resolver_confidence": float(result.get("similarity_score") or 0.0),
            "verifier_decision": str(result.get("verifier_decision") or ""),
            "verifier_reason": str(result.get("verifier_reason") or ""),
            "auto_accept": bool(result.get("auto_accept")),
            "compatibility_status": str(result.get("compatibility_status") or ""),
            "incompatibility_reason": str(result.get("incompatibility_reason") or ""),
            "stage_of_failure": stage_of_failure,
            "reason_code": reason_code_value,
            "reason_class": infer_reason_class(stage_of_failure, reason_code_value),
            "gemini_route_used": bool((query_features or {}).get("gemini_route_used")),
            "gemini_validation_used": bool(result.get("gemini_validation_used") or (query_features or {}).get("gemini_validation_used")),
            "secondary_filter_rule_set": list((query_features or {}).get("secondary_filter_rule_set") or []),
            "pipeline_counts": pipeline_counts,
            "candidate_snapshots": candidate_snapshots,
            "gemini": gemini_payload,
            "trace_steps": trace_steps,
        }
        result["stage_of_failure"] = diagnostic_trace["stage_of_failure"]
        result["reason_code"] = diagnostic_trace["reason_code"]
        result["reason_class"] = diagnostic_trace["reason_class"]
        result["resolver_path"] = diagnostic_trace["resolver_path"]
        result["diagnostic_trace"] = diagnostic_trace
        return result

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

    def _extract_json_object(self, raw_text: str) -> Dict[str, Any]:
        start_idx = raw_text.find("{")
        end_idx = raw_text.rfind("}") + 1
        if start_idx == -1 or end_idx <= start_idx:
            raise ValueError("JSON not found in model response")
        payload = json.loads(raw_text[start_idx:end_idx])
        if not isinstance(payload, dict):
            raise ValueError("Gemini payload is not a JSON object")
        return payload

    def _should_use_family_router_gemini(self, query_features: Dict[str, Any]) -> bool:
        if not hasattr(self, "backend"):
            return False
        if not bool(registry_gemini_policy_value(getattr(self, "taxonomy_rules", {}), "family_router", "enabled", False)):
            return False
        if self._clean_text_value(query_features.get("row_type")) != "item":
            return False
        family = self._entity_family(query_features.get("entity_type", ""))
        allowed_families = {
            self._clean_text_value(item)
            for item in registry_gemini_policy_value(getattr(self, "taxonomy_rules", {}), "family_router", "families", [])
            if self._clean_text_value(item)
        }
        min_confidence = float(
            registry_gemini_policy_value(getattr(self, "taxonomy_rules", {}), "family_router", "min_family_confidence", 0.6)
        )
        return family in allowed_families and float(query_features.get("family_confidence") or 0.0) < min_confidence

    def _route_query_family_with_gemini(self, query: str, query_features: Dict[str, Any]) -> Dict[str, Any] | None:
        family_options = sorted(registry_audited_families(getattr(self, "taxonomy_rules", {})) | {"other"})
        prompt = (
            "Ты помогаешь только с маршрутизацией технической номенклатуры.\n"
            f"Запрос: {query}\n"
            f"Текущая локальная family: {self._entity_family(query_features.get('entity_type', '')) or 'other'}\n"
            "Выбери наиболее подходящее семейство и ветку каталога. Не выбирай товар.\n"
            f"Разрешенные family: {', '.join(family_options)}\n"
            "Верни только JSON: "
            '{"family":"family_name","branch_hint":"catalog > branch or empty","confidence":0.0,'
            '"markers":{"category":"","shielding":"","connector_pair":"","component_kind":"","mount_kind":""},'
            '"reasoning":"short"}'
        )
        last_error: Exception | None = None
        for model_name in self._candidate_models():
            try:
                raw_text = self._generate_gemini_text_limited(prompt, model_name)
                payload = self._extract_json_object(raw_text)
                family_name = self._entity_family(payload.get("family", ""))
                if not family_name:
                    continue
                branch_hint = self._clean_text_value(payload.get("branch_hint"))
                confidence = float(payload.get("confidence") or 0.0)
                markers = payload.get("markers") if isinstance(payload.get("markers"), dict) else {}
                return {
                    "family": family_name,
                    "branch_hint": branch_hint,
                    "confidence": confidence,
                    "markers": {self._clean_text_value(key): self._clean_text_value(value) for key, value in markers.items()},
                    "gemini_model": model_name,
                    "reasoning": self._clean_text_value(payload.get("reasoning")),
                }
            except Exception as exc:
                last_error = exc
                logger.warning("Family router model %s failed: %s", model_name, exc)
        if last_error is not None:
            logger.info("Gemini family router skipped after failures: query=%s error=%s", query[:120], last_error)
        return None

    def _gemini_route_changes_query_features(
        self,
        query_features: Dict[str, Any],
        routed: Dict[str, Any] | None,
    ) -> bool:
        if not isinstance(routed, dict):
            return False
        original_entity_type = self._clean_text_value(query_features.get("entity_type"))
        original_branch_hint = self._clean_text_value(query_features.get("branch_hint"))
        original_markers = dict(query_features.get("markers", {}) or {})

        routed_family = self._clean_text_value(routed.get("family"))
        if routed_family and routed_family != original_entity_type:
            return True

        routed_branch = self._clean_text_value(routed.get("branch_hint"))
        if routed_branch and routed_branch != original_branch_hint:
            return True

        routed_markers = routed.get("markers") if isinstance(routed.get("markers"), dict) else {}
        for key, value in routed_markers.items():
            cleaned_key = self._clean_text_value(key)
            cleaned_value = self._clean_text_value(value)
            if cleaned_key and cleaned_value and cleaned_value != self._clean_text_value(original_markers.get(cleaned_key)):
                return True
        return False

    def _should_use_article_validator_gemini(self, query_features: Dict[str, Any], reason_code: str) -> bool:
        if not hasattr(self, "backend"):
            return False
        if not bool(registry_gemini_policy_value(getattr(self, "taxonomy_rules", {}), "article_validator", "enabled", False)):
            return False
        allowed_reasons = {
            self._clean_text_value(item)
            for item in registry_gemini_policy_value(getattr(self, "taxonomy_rules", {}), "article_validator", "conflict_reasons", [])
            if self._clean_text_value(item)
        }
        if self._clean_text_value(reason_code) not in allowed_reasons:
            return False
        min_confidence = float(
            registry_gemini_policy_value(getattr(self, "taxonomy_rules", {}), "article_validator", "min_domain_confidence", 0.5)
        )
        candidate_text = self._clean_text_value(query_features.get("article_candidate_text"))
        query_domain = registry_infer_domain_match(
            self._clean_text_value(query_features.get("original_text")),
            entity_family=self._entity_family(query_features.get("entity_type", "")),
            rules=getattr(self, "taxonomy_rules", {}),
        )
        candidate_domain = registry_infer_domain_match(
            candidate_text,
            entity_family=self._clean_text_value(query_features.get("article_candidate_family")),
            rules=getattr(self, "taxonomy_rules", {}),
        )
        return float(query_domain.get("confidence") or 0.0) >= min_confidence and float(candidate_domain.get("confidence") or 0.0) >= min_confidence

    def _validate_article_match_with_gemini(
        self,
        query: str,
        query_features: Dict[str, Any],
        article_match: Dict[str, Any],
        query_article: str,
    ) -> Dict[str, Any] | None:
        max_alternatives = int(
            registry_gemini_policy_value(getattr(self, "taxonomy_rules", {}), "article_validator", "max_alternatives", 2)
        )
        shortlist: List[Dict[str, Any]] = [article_match]
        for item in self._lookup_catalog_items_by_article_series(query_article, query_features)[:max_alternatives]:
            row_idx = int(item.get("row_idx", -1))
            if row_idx == int(article_match.get("row_idx", -2)):
                continue
            shortlist.append(item)
        result = self._match_with_gemini(
            query,
            query_features=query_features,
            branches=[self._clean_text_value(article_match.get("branch_path"))],
            candidates=shortlist,
        )
        found_name = self._clean_text_value(result.get("found_name"))
        if not found_name or found_name == MISSING_POSITION_TEXT:
            return None
        result["resolution_source"] = "article_validator_gemini"
        result["gemini_validation_used"] = True
        result["article_validation_status"] = "validated"
        return result

    def _should_use_candidate_tiebreaker_gemini(
        self,
        query_features: Dict[str, Any],
        scored_entries: List[Dict[str, Any]],
        margin: float,
        top_branch_gap: float,
    ) -> bool:
        if not hasattr(self, "backend"):
            return False
        if not bool(registry_gemini_policy_value(getattr(self, "taxonomy_rules", {}), "candidate_tiebreaker", "enabled", True)):
            return False
        if len(scored_entries) < int(registry_gemini_policy_value(getattr(self, "taxonomy_rules", {}), "candidate_tiebreaker", "min_candidates", 2)):
            return False
        if len(scored_entries) > int(registry_gemini_policy_value(getattr(self, "taxonomy_rules", {}), "candidate_tiebreaker", "max_candidates", 8)):
            return False
        margin_threshold = float(
            registry_gemini_policy_value(getattr(self, "taxonomy_rules", {}), "candidate_tiebreaker", "margin_threshold", 0.05)
        )
        branch_gap_threshold = float(
            registry_gemini_policy_value(getattr(self, "taxonomy_rules", {}), "candidate_tiebreaker", "branch_gap_threshold", 0.15)
        )
        if self._clean_text_value(query_features.get("article_lookup_rejected_reason")):
            return False
        return margin <= margin_threshold or top_branch_gap <= branch_gap_threshold

    def _get_gemini_request_limit(self) -> int:
        configured = int(getattr(self, "_gemini_request_limit", 0) or 0)
        if configured > 0:
            return max(1, configured)
        return min(25, max(1, int(getattr(self, "parallel_requests", 1) or 1)))

    def _get_gemini_request_semaphore(self) -> threading.BoundedSemaphore:
        limit = self._get_gemini_request_limit()
        semaphore = getattr(self, "_gemini_request_semaphore", None)
        current_limit = int(getattr(self, "_gemini_request_limit", 0) or 0)
        if semaphore is None or current_limit != limit:
            semaphore = threading.BoundedSemaphore(limit)
            self._gemini_request_semaphore = semaphore
            self._gemini_request_limit = limit
        return semaphore

    def _get_gemini_chunk_parallelism(self) -> int:
        configured = int(getattr(self, "gemini_chunk_parallelism", 0) or 0)
        if configured > 0:
            return max(1, min(configured, self._get_gemini_request_limit(), max(1, int(getattr(self, "gemini_max_chunks", 8) or 1))))
        return max(
            1,
            min(
                4,
                self._get_gemini_request_limit(),
                max(1, int(getattr(self, "gemini_max_chunks", 8) or 1)),
            ),
        )

    def _generate_gemini_text_limited(self, prompt: str, model_name: str) -> str:
        semaphore = self._get_gemini_request_semaphore()
        semaphore.acquire()
        try:
            return self._generate_gemini_text(prompt, model_name)
        finally:
            semaphore.release()

    def _evaluate_gemini_prompt(
        self,
        query: str,
        prompt: str,
        candidate_lookup: Dict[str, Dict[str, Any]],
        article_lookup: Dict[str, Dict[str, Any]],
        source: str,
    ) -> Dict[str, Any]:
        last_missing: Dict[str, Any] | None = None
        last_error: Exception | None = None
        last_raw_text = ""
        last_model_name = ""
        for model_name in self._candidate_models():
            try:
                raw_text = self._generate_gemini_text_limited(prompt, model_name)
                parsed = self._parse_gemini_result(query, raw_text, candidate_lookup, article_lookup, source, model_name)
                if parsed["found_name"] == MISSING_POSITION_TEXT:
                    last_missing = parsed
                    last_raw_text = raw_text
                    last_model_name = model_name
                    continue
                return {
                    "status": "success",
                    "parsed": parsed,
                    "raw_text": raw_text,
                    "model_name": model_name,
                }
            except Exception as exc:
                last_error = exc
                last_model_name = model_name
                logger.warning("Model %s failed: %s", model_name, exc)
        if last_missing is not None:
            return {
                "status": "missing",
                "parsed": last_missing,
                "raw_text": last_raw_text,
                "model_name": last_model_name,
            }
        return {
            "status": "error",
            "error": last_error if last_error is not None else RuntimeError("Gemini did not return result"),
            "model_name": last_model_name,
        }

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
        query: str | None = None,
    ) -> List[str]:
        if not candidates:
            return []
        chunk_size = max(1, int(getattr(self, "gemini_chunk_size", 12)))
        max_chunks = max(1, int(getattr(self, "gemini_max_chunks", 8)))
        chunks: List[str] = []
        for offset in range(0, len(candidates), chunk_size):
            if len(chunks) >= max_chunks:
                break
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
        visible_candidates = min(len(candidates), chunk_size * max_chunks)
        truncated_candidates = max(0, len(candidates) - visible_candidates)
        logger.info(
            "Gemini chunks prepared: query=%s chunk_size=%s max_chunks=%s chunks=%s visible_candidates=%s truncated=%s",
            self._clean_text_value(query)[:120] if query is not None else "",
            chunk_size,
            max_chunks,
            len(chunks),
            visible_candidates,
            truncated_candidates,
        )
        return chunks

    def _parse_gemini_result(
        self,
        query: str,
        raw_text: str,
        candidate_lookup: Dict[str, Dict[str, Any]],
        article_lookup: Dict[str, Dict[str, Any]],
        source: str,
        model_name: str,
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
        compatibility = self._clean_text_value(payload.get("compatibility")).lower()
        rejection_reason = self._clean_text_value(payload.get("rejection_reason"))
        if compatibility not in {"compatible", "weakly_compatible", "incompatible"}:
            compatibility = "compatible"

        matched_item = None
        if found_name:
            matched_item = candidate_lookup.get(found_name.lower()) or self._lookup_catalog_item_by_name(found_name)
        if matched_item is None and article:
            matched_item = article_lookup.get(article.lower())

        if compatibility == "incompatible":
            return self._build_missing_result(
                query,
                rejection_reason or reasoning or "Gemini отверг все кандидаты как несовместимые",
                compatibility_status="rejected_incompatible_gemini",
                incompatibility_reason=rejection_reason or "gemini_rejected_incompatible",
                gemini_model=model_name,
                gemini_result_status="rejected_incompatible",
            )
        if matched_item is None:
            return self._build_missing_result(
                query,
                rejection_reason or reasoning or "Gemini не выбрал валидного кандидата",
                compatibility_status="unresolved_no_compatible_candidates",
                incompatibility_reason=rejection_reason,
                gemini_model=model_name,
                gemini_result_status="no_valid_candidate",
            )

        return self._build_result_from_item(
            matched_item,
            score=max(0.0, min(0.999, confidence)),
            source=source,
            requires_review=confidence < 0.9 or compatibility != "compatible",
            alternatives="",
            reason=reasoning,
            compatibility_status=compatibility or "compatible",
            incompatibility_reason=rejection_reason,
            gemini_model=model_name,
            gemini_result_status="selected_candidate",
        )

    def _match_with_gemini(
        self,
        query: str,
        query_features: Optional[Dict[str, Any]] = None,
        branches: Optional[List[str]] = None,
        candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if candidates:
            context_chunks = self._build_narrow_candidate_chunks(
                branches or [],
                candidates,
                query_features,
                query=query,
            )
            source = "local_tree+gemini"
        else:
            context_chunks = self._build_context_chunks(
                query,
                max_chunks=max(1, int(getattr(self, "gemini_max_chunks", 8))),
            )
            source = "gemini"

        if not context_chunks:
            return self._build_missing_result(
                query,
                "Контекст для Gemini отсутствует",
                gemini_result_status="no_context",
            )

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
        strictness = self._match_strictness_for_query(query_features or {})

        def build_prompt(context_text: str) -> str:
            if candidates:
                if strictness == "strict":
                    selection_policy = (
                        "Выбирай только если кандидат товарно и технически совместим. "
                        "Если совместимого кандидата нет, верни found_name=null, article=null, compatibility=\"incompatible\" "
                        "и краткую rejection_reason."
                    )
                elif strictness == "semi_strict":
                    selection_policy = (
                        "Сначала ищи полностью совместимый кандидат. Если есть только частично совместимый, можешь выбрать его "
                        "с compatibility=\"weakly_compatible\" и низкой уверенностью. Если все несовместимы, верни found_name=null."
                    )
                else:
                    selection_policy = (
                        "Выбери лучший кандидат из списка. Если есть только слабое совпадение, допустим best-effort, "
                        "но укажи compatibility=\"weakly_compatible\" и кратко опиши риск."
                    )
                return (
                    "Ты выбираешь лучший товар только из уже отобранного короткого списка.\n"
                    f"Запрос КП: {query}\n"
                    f"Строка типа: {(query_features or {}).get('row_type', 'item')}\n"
                    f"Режим строгости: {strictness}\n"
                    f"Категории: {' | '.join(branches or [])}\n"
                    "Ниже только допустимые кандидаты:\n"
                    f"{context_text}\n\n"
                    f"{selection_policy}\n"
                    "Верни только JSON: "
                    '{"found_name":"Точное имя из списка или null","article":"Артикул из списка или null","confidence":0.0,"reasoning":"краткое объяснение","compatibility":"compatible|weakly_compatible|incompatible","rejection_reason":"краткая причина или пусто"}'
                )
            return (
                "Ты эксперт по технической номенклатуре оборудования, кабеля и материалов.\n"
                f"Запрос пользователя: {query}\n"
                "Найди лучший товар в каталоге ниже.\n"
                f"{context_text}\n"
                "Верни только JSON: "
                '{"found_name":"Точное название из каталога или null","article":"Артикул или null","confidence":0.0,"reasoning":"краткое объяснение","compatibility":"compatible|weakly_compatible|incompatible","rejection_reason":"краткая причина или пусто"}'
            )

        prompts = [build_prompt(context_text) for context_text in context_chunks]
        last_missing: Dict[str, Any] | None = None
        last_error: Exception | None = None
        last_raw_text = ""
        last_model_name = ""
        chunk_parallelism = min(len(prompts), self._get_gemini_chunk_parallelism())
        if len(prompts) > 1 and chunk_parallelism > 1:
            logger.info(
                "Gemini chunk execution: query=%s prompts=%s chunk_parallelism=%s global_limit=%s",
                self._clean_text_value(query)[:120],
                len(prompts),
                chunk_parallelism,
                self._get_gemini_request_limit(),
            )
            pool = ThreadPoolExecutor(max_workers=chunk_parallelism)
            future_map: Dict[Any, int] = {}
            resolved_results: Dict[int, Dict[str, Any]] = {}
            next_to_submit = 0
            next_to_resolve = 0
            cancelled = False

            def submit_chunk(chunk_idx: int) -> None:
                future = pool.submit(
                    self._evaluate_gemini_prompt,
                    query,
                    prompts[chunk_idx],
                    candidate_lookup,
                    article_lookup,
                    source,
                )
                future_map[future] = chunk_idx

            try:
                while next_to_submit < chunk_parallelism:
                    submit_chunk(next_to_submit)
                    next_to_submit += 1

                while future_map:
                    done, _pending = wait(set(future_map), timeout=0.25, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    for future in done:
                        chunk_idx = future_map.pop(future)
                        try:
                            resolved_results[chunk_idx] = future.result()
                        except Exception as exc:
                            resolved_results[chunk_idx] = {"status": "error", "error": exc, "model_name": ""}

                    while next_to_resolve in resolved_results:
                        outcome = resolved_results.pop(next_to_resolve)
                        status = str(outcome.get("status") or "")
                        if status == "success":
                            parsed = dict(outcome.get("parsed") or {})
                            raw_text = str(outcome.get("raw_text") or "")
                            model_name = str(outcome.get("model_name") or "")
                            self.model_name = model_name or getattr(self, "model_name", None)
                            for pending_future in future_map:
                                pending_future.cancel()
                            cancelled = True
                            self._save_to_cache(
                                query,
                                parsed["found_name"],
                                parsed["price"],
                                parsed["article"] or "",
                                parsed["similarity_score"],
                                raw_text,
                            )
                            return parsed
                        if status == "missing":
                            last_missing = dict(outcome.get("parsed") or {})
                            last_raw_text = str(outcome.get("raw_text") or "")
                            last_model_name = str(outcome.get("model_name") or "")
                        else:
                            error = outcome.get("error")
                            if isinstance(error, Exception):
                                last_error = error
                            else:
                                last_error = RuntimeError(str(error or "Gemini did not return result"))
                            last_model_name = str(outcome.get("model_name") or "")
                        next_to_resolve += 1
                        if next_to_submit < len(prompts):
                            submit_chunk(next_to_submit)
                            next_to_submit += 1
            finally:
                pool.shutdown(wait=not cancelled, cancel_futures=cancelled)
        else:
            for prompt in prompts:
                outcome = self._evaluate_gemini_prompt(query, prompt, candidate_lookup, article_lookup, source)
                status = str(outcome.get("status") or "")
                if status == "success":
                    parsed = dict(outcome.get("parsed") or {})
                    raw_text = str(outcome.get("raw_text") or "")
                    model_name = str(outcome.get("model_name") or "")
                    self.model_name = model_name or getattr(self, "model_name", None)
                    self._save_to_cache(
                        query,
                        parsed["found_name"],
                        parsed["price"],
                        parsed["article"] or "",
                        parsed["similarity_score"],
                        raw_text,
                    )
                    return parsed
                if status == "missing":
                    last_missing = dict(outcome.get("parsed") or {})
                    last_raw_text = str(outcome.get("raw_text") or "")
                    last_model_name = str(outcome.get("model_name") or "")
                else:
                    error = outcome.get("error")
                    if isinstance(error, Exception):
                        last_error = error
                    else:
                        last_error = RuntimeError(str(error or "Gemini did not return result"))
                    last_model_name = str(outcome.get("model_name") or "")

        if last_missing is not None:
            if last_model_name:
                self.model_name = last_model_name
            self._save_to_cache(
                query,
                last_missing["found_name"],
                last_missing["price"],
                last_missing["article"] or "",
                last_missing["similarity_score"],
                last_raw_text,
            )
            return last_missing

        return self._build_missing_result(
            query,
            "",
            error=str(last_error) if last_error else "Gemini did not return result",
            gemini_model=last_model_name or str(getattr(self, "model_name", "") or ""),
            gemini_result_status="runtime_error" if last_error else "no_valid_candidate",
        )

    def _resolve_ambiguous_candidates_with_gemini(
        self,
        query: str,
        query_features: Dict[str, Any],
        branches: List[str],
        scored_entries: List[Dict[str, Any]],
        *,
        source_label: str = "candidate_tiebreaker_gemini",
    ) -> Optional[Dict[str, Any]]:
        strictness = self._match_strictness_for_query(query_features)
        shortlist = [
            entry["item"]
            for entry in scored_entries[: min(int(getattr(self, "gemini_shortlist_limit", 96)), len(scored_entries))]
        ]
        if not shortlist:
            return None
        chunk_size = max(1, int(getattr(self, "gemini_chunk_size", 12)))
        max_chunks = max(1, int(getattr(self, "gemini_max_chunks", 8)))
        visible_candidates = min(len(shortlist), chunk_size * max_chunks)
        truncated_candidates = max(0, len(shortlist) - visible_candidates)
        try:
            result = self._match_with_gemini(
                query,
                query_features=query_features,
                branches=branches,
                candidates=shortlist,
            )
        except TypeError:
            result = self._match_with_gemini(query)
        found_name = self._clean_text_value((result or {}).get("found_name"))
        if result:
            result["gemini_shortlist_count"] = len(shortlist)
            result["gemini_visible_candidates"] = visible_candidates
            result["gemini_truncated_candidates"] = truncated_candidates
        if not result or not found_name or found_name == MISSING_POSITION_TEXT:
            if strictness == "strict" and result:
                return result
            return None
        matched_item = self._lookup_catalog_item_by_name(found_name, candidate_pool=shortlist)
        reject_weak_exact = self._should_reject_weak_resolution_in_exact_mode(query_features)
        if str(result.get("compatibility_status") or "").strip() == "weakly_compatible" and (
            strictness == "strict" or reject_weak_exact
        ):
            return self._build_missing_result(
                query,
                "Gemini нашел только частично совместимый кандидат; для этой позиции требуется строго совместимое совпадение.",
                compatibility_status="unresolved_no_compatible_candidates",
                incompatibility_reason=(
                    "exact_mode_requires_compatible_match"
                    if reject_weak_exact and strictness != "strict"
                    else "strict_class_requires_compatible_match"
                ),
                gemini_shortlist_count=len(shortlist),
                gemini_visible_candidates=visible_candidates,
                gemini_truncated_candidates=truncated_candidates,
                gemini_model=str(result.get("gemini_model") or ""),
                gemini_result_status=(
                    "weakly_compatible_rejected_exact_mode"
                    if reject_weak_exact and strictness != "strict"
                    else "weakly_compatible_rejected_strict"
                ),
            )
        if matched_item and not self._is_gemini_result_family_valid(query_features, matched_item):
            query_family = self._entity_family(query_features.get("entity_type", ""))
            result_family = self._entity_family(matched_item.get("entity_type", ""))
            logger.info(
                "🧠 Gemini result rejected by family gate: query=%s query_family=%s result_family=%s",
                query[:120],
                query_family or "other",
                result_family or "other",
            )
            rejected = self._build_missing_result(
                query,
                "Gemini выбрал кандидата из несовместимого товарного семейства; позиция отклонена.",
                compatibility_status="rejected_incompatible_gemini",
                incompatibility_reason="gemini_family_gate_rejected",
                gemini_shortlist_count=len(shortlist),
                gemini_visible_candidates=visible_candidates,
                gemini_truncated_candidates=truncated_candidates,
                gemini_model=str(result.get("gemini_model") or ""),
                gemini_result_status="family_gate_rejected",
            )
            if strictness == "strict":
                return rejected
            return None
        if matched_item and self._is_hard_incompatible_match(query_features, matched_item):
            reason = self._hard_incompatibility_reason(query_features, matched_item) or "gemini_selected_incompatible_candidate"
            logger.info("Skipping Gemini result due to hard incompatibility: query=%s found=%s reason=%s", query, result.get("found_name"), reason)
            rejected = self._build_missing_result(
                query,
                "Gemini выбрал несовместимого кандидата; позиция отклонена.",
                compatibility_status="rejected_incompatible_gemini",
                incompatibility_reason=reason,
                gemini_shortlist_count=len(shortlist),
                gemini_visible_candidates=visible_candidates,
                gemini_truncated_candidates=truncated_candidates,
                gemini_model=str(result.get("gemini_model") or ""),
                gemini_result_status="hard_incompatibility_rejected",
            )
            if strictness == "strict":
                return rejected
            return None
        result["alternatives"] = result.get("alternatives") or self._format_alternatives(scored_entries, skip_first=True)
        if result.get("requires_review") not in {"да", "нет"}:
            result["requires_review"] = "да" if result.get("similarity_score", 0) < 0.9 else "нет"
        if not result.get("category_path") and matched_item:
            result["category_path"] = matched_item.get("branch_path")
        result.setdefault(
            "confidence_level",
            self._confidence_level_from_score(result.get("similarity_score", 0), result.get("requires_review") == "да"),
        )
        result["resolution_source"] = source_label
        result.setdefault("gemini_result_status", "selected_candidate")
        return result

    def match(self, query: str, use_cache: bool = True) -> Dict[str, Any]:
        query_text = self._clean_text_value(query)
        input_context = self._current_match_input_context()
        column_article = self._clean_text_value(input_context.get("input_article"))
        extracted_article_from_context = self._clean_text_value(input_context.get("extracted_article"))
        extracted_article = extracted_article_from_context or self._extract_query_article_from_text(query_text)
        normalized_column_article = self._normalize_article_lookup_value(column_article)
        normalized_text_article = self._normalize_article_lookup_value(extracted_article)
        article_lookup_conflict = bool(
            normalized_column_article and normalized_text_article and normalized_column_article != normalized_text_article
        )
        query_article = column_article or extracted_article
        article_source = "column" if column_article else ("text" if extracted_article else "none")
        article_lookup_hit = False
        query_features: Dict[str, Any] = {}
        trace_steps: List[Dict[str, Any]] = []
        local_candidate_pool: List[Dict[str, Any]] = []
        all_scored_entries: List[Dict[str, Any]] = []
        same_family_entries: List[Dict[str, Any]] = []
        compatible_entries_all: List[Dict[str, Any]] = []
        best_compatible: Dict[str, Any] | None = None
        best_weak: Dict[str, Any] | None = None
        gemini_attempted = False
        gemini_result_status = ""
        gemini_model = ""
        retrieval_mode = "legacy_limited"
        query_category_key = ""
        category_candidate_count = 0
        category_rows_scanned = 0
        duckdb_query_ms = 0.0
        python_scoring_ms = 0.0
        compatibility_filter_ms = 0.0
        gemini_total_ms = 0.0
        article_series_candidates: List[Dict[str, Any]] = []

        def _build_pipeline_counts() -> Dict[str, Any]:
            return {
                "local_pool_count": len(local_candidate_pool),
                "scored_count": len(all_scored_entries),
                "same_family_count": len(same_family_entries),
                "compatible_count": len(compatible_entries_all),
                "retrieval_mode": retrieval_mode,
                "retrieval_backend": getattr(self, "retrieval_backend", "memory"),
                "query_category_key": query_category_key,
                "category_candidate_count": category_candidate_count,
                "category_rows_scanned": category_rows_scanned,
                "duckdb_query_ms": round(float(duckdb_query_ms), 2),
                "python_scoring_ms": round(float(python_scoring_ms), 2),
                "compatibility_filter_ms": round(float(compatibility_filter_ms), 2),
                "gemini_ms": round(float(gemini_total_ms), 2),
                "secondary_filter_rule_set": list(query_features.get("secondary_filter_rule_set") or []),
                "secondary_filter_before_count": int(query_features.get("secondary_filter_before_count") or 0),
                "secondary_filter_after_count": int(query_features.get("secondary_filter_after_count") or 0),
            }

        def _build_candidate_snapshots() -> Dict[str, Any]:
            snapshots = {
                "top_scored": self._diagnostic_candidates_from_entries(query_features, all_scored_entries),
                "top_same_family": self._diagnostic_candidates_from_entries(query_features, same_family_entries),
                "top_compatible": self._diagnostic_candidates_from_entries(query_features, compatible_entries_all),
            }
            if best_compatible is not None and isinstance(best_compatible.get("item"), dict):
                snapshots["best_compatible"] = self._diagnostic_candidate_from_item(
                    query_features,
                    best_compatible["item"],
                    score=float(best_compatible.get("score", 0.0)),
                )
            if best_weak is not None and isinstance(best_weak.get("item"), dict):
                snapshots["best_weak"] = self._diagnostic_candidate_from_item(
                    query_features,
                    best_weak["item"],
                    score=float(best_weak.get("score", 0.0)),
                )
            return snapshots

        def _build_gemini_payload(result: Dict[str, Any] | None = None) -> Dict[str, Any]:
            current_result = result or {}
            return {
                "attempted": gemini_attempted,
                "model": str(current_result.get("gemini_model") or gemini_model or ""),
                "shortlist_count": int(current_result.get("gemini_shortlist_count") or 0),
                "visible_candidates": int(current_result.get("gemini_visible_candidates") or 0),
                "truncated_candidates": int(current_result.get("gemini_truncated_candidates") or 0),
                "result_status": str(current_result.get("gemini_result_status") or gemini_result_status or ""),
            }

        def _finalize(result: Dict[str, Any], *, stage_of_failure: str, reason_code: str) -> Dict[str, Any]:
            result = self._apply_verifier_decision(dict(result), query_features=query_features)
            trace_steps_with_final = list(trace_steps)
            trace_steps_with_final.append(
                {
                    "stage": "final",
                    "status": "resolved" if stage_of_failure == "resolved" else "failed",
                    "resolution_source": str(result.get("resolution_source") or ""),
                    "compatibility_status": str(result.get("compatibility_status") or ""),
                    "reason_code": str(reason_code or "resolved"),
                }
            )
            return self._attach_diagnostic_trace(
                result,
                query_text=query_text or str(query or ""),
                query_article=query_article,
                article_source=article_source,
                article_lookup_hit=article_lookup_hit,
                article_lookup_conflict=article_lookup_conflict,
                query_features=query_features,
                stage_of_failure=stage_of_failure,
                reason_code=str(reason_code or "resolved"),
                trace_steps=trace_steps_with_final,
                pipeline_counts=_build_pipeline_counts(),
                candidate_snapshots=_build_candidate_snapshots(),
                gemini_payload=_build_gemini_payload(result),
            )

        if query_article:
            trace_steps.append(
                {
                    "stage": "article_lookup",
                    "status": "pending",
                    "article_source": article_source,
                    "query_article": query_article,
                    "article_lookup_conflict": article_lookup_conflict,
                }
            )

        try:
            if not query_text:
                result = self._build_missing_result(query, "Пустая строка")
                trace_steps.append({"stage": "query_input", "status": "failed", "reason_code": "empty_query"})
                return _finalize(result, stage_of_failure="query_input", reason_code="empty_query")

            normalized_query = self._normalize_text(query_text)
            query_features = self._extract_query_features(query_text)
            query_features["query_article"] = query_article
            query_features["article_source"] = article_source
            query_family = self._entity_family(query_features.get("entity_type", ""))
            trace_steps.append(
                {
                    "stage": "query_classification",
                    "status": "ok",
                    "row_type": str(query_features.get("row_type") or ""),
                    "entity_type": str(query_features.get("entity_type") or ""),
                    "query_family": query_family,
                    "family_confidence": float(query_features.get("family_confidence") or 0.0),
                }
            )
            if query_features.get("row_type") == "section":
                result = self._build_missing_result(
                    query_text,
                    "Строка похожа на раздел каталога и не является конкретной товарной позицией.",
                    incompatibility_reason="section_row_detected",
                )
                trace_steps.append({"stage": "query_input", "status": "failed", "reason_code": "section_row_detected"})
                return _finalize(result, stage_of_failure="query_input", reason_code="section_row_detected")

            if use_cache and query_text:
                cached = self._get_from_cache(query_text)
                if cached:
                    cached_item = {
                        "name": cached.get("found_name"),
                        "article": cached.get("article"),
                        "normalized_name": self._normalize_text(self._clean_text_value(cached.get("found_name"))),
                    }
                    promoted_source = self._exact_resolution_source_for_item(
                        query_text,
                        query_article,
                        article_source,
                        cached_item,
                    )
                    if promoted_source:
                        cached = dict(cached)
                        cached["resolution_source"] = promoted_source
                        cached["resolver_path"] = self._resolver_path_for_source(promoted_source) or cached.get("resolver_path", "")
                        cached["similarity_score"] = self._exact_resolution_score(promoted_source)
                        cached["confidence_level"] = self._confidence_level_from_score(
                            cached["similarity_score"],
                            False,
                        )
                    else:
                        cached = dict(cached)
                        cached["resolver_path"] = self._cached_result_resolver_path(query_features)
                    cached = self._apply_verifier_decision(cached, query_features=query_features)
                    trace_steps.append({"stage": "cache", "status": "hit"})
                    return _finalize(cached, stage_of_failure="resolved", reason_code="resolved")

            # Keep article-first authoritative: if we already have a parsed article/designation,
            # let exact article resolution run before Gemini rewrites the family.
            if not query_article and self._should_use_family_router_gemini(query_features):
                routed = self._route_query_family_with_gemini(query_text, query_features)
                if routed is not None:
                    route_changed = self._gemini_route_changes_query_features(query_features, routed)
                    query_features["entity_type"] = self._clean_text_value(routed.get("family")) or query_features.get("entity_type")
                    routed_branch = self._clean_text_value(routed.get("branch_hint"))
                    if routed_branch:
                        query_features["branch_hint"] = routed_branch
                    routed_markers = routed.get("markers") if isinstance(routed.get("markers"), dict) else {}
                    if routed_markers:
                        merged_markers = dict(query_features.get("markers", {}) or {})
                        for key, value in routed_markers.items():
                            if self._clean_text_value(value):
                                merged_markers[key] = value
                        query_features["markers"] = merged_markers
                        query_features["attributes"] = dict(merged_markers)
                    query_features["family_confidence"] = max(
                        float(query_features.get("family_confidence") or 0.0),
                        float(routed.get("confidence") or 0.0),
                    )
                    if route_changed:
                        query_features["gemini_route_used"] = True
                        trace_steps.append(
                            {
                                "stage": "query_classification",
                                "status": "routed",
                                "reason_code": "family_router_gemini",
                                "query_family": self._entity_family(query_features.get("entity_type", "")),
                                "family_confidence": float(query_features.get("family_confidence") or 0.0),
                            }
                        )
            query_family = self._entity_family(query_features.get("entity_type", ""))
            strictness = self._match_strictness_for_query(query_features)

            preferred_result: Dict[str, Any] | None = None
            preferred_entry: Dict[str, Any] | None = None

            article_resolution = self._resolve_article_stack(
                query_text,
                query_article,
                article_source,
                article_lookup_conflict,
                query_features,
                trace_steps,
            )
            article_lookup_hit = bool(article_resolution.get("article_lookup_hit"))
            article_series_candidates = list(article_resolution.get("article_series_candidates") or [])
            if article_resolution.get("result") is not None:
                return _finalize(article_resolution["result"], stage_of_failure="resolved", reason_code="resolved")

            preferred_result, preferred_entry = self._resolve_direct_exact_stack(
                query_text,
                normalized_query,
                query_article,
                article_source,
            )
            if preferred_result and str(preferred_result.get("resolution_source") or "") in {
                "article_exact",
                "article_extracted_exact",
                "name_exact",
                "normalized_name_exact",
            }:
                return _finalize(preferred_result, stage_of_failure="resolved", reason_code="resolved")

            article_match = self._lookup_catalog_item_by_article(query_article) if query_article else None
            if query_article:
                article_lookup_hit = article_match is not None
                article_sanity_reason = ""
                article_lookup_status = "miss"
                if article_match is not None:
                    query_features["article_candidate_text"] = " ".join(
                        filter(
                            None,
                            [
                                self._clean_text_value(article_match.get("name")),
                                self._clean_text_value(article_match.get("normalized_name")),
                                self._clean_text_value(article_match.get("branch_path")),
                            ],
                        )
                    )
                    query_features["article_candidate_family"] = self._entity_family(article_match.get("entity_type", ""))
                    article_sanity_reason = self._article_match_sanity_reason(query_features, article_match)
                    article_lookup_status = "rejected" if article_sanity_reason else "hit"
                    if article_sanity_reason and self._should_use_article_validator_gemini(query_features, article_sanity_reason):
                        validated_result = self._validate_article_match_with_gemini(query_text, query_features, article_match, query_article)
                        if validated_result is not None:
                            article_lookup_status = "validated"
                            query_features["gemini_validation_used"] = True
                            query_features["article_validation_status"] = "validated_by_gemini"
                            trace_steps.append(
                                {
                                    "stage": "article_lookup",
                                    "status": "validated",
                                    "article_source": article_source,
                                    "query_article": query_article,
                                    "article_lookup_conflict": article_lookup_conflict,
                                    "reason_code": article_sanity_reason,
                                    "gemini_validation_used": True,
                                }
                            )
                            return _finalize(validated_result, stage_of_failure="resolved", reason_code="resolved")
                        query_features["gemini_validation_used"] = True
                        query_features["article_validation_status"] = "rejected_by_gemini"
                    if article_sanity_reason:
                        query_features["article_lookup_rejected_reason"] = article_sanity_reason
                        query_features.setdefault("article_validation_status", "rejected")
                trace_steps.append(
                    {
                        "stage": "article_lookup",
                        "status": article_lookup_status,
                        "article_source": article_source,
                        "query_article": query_article,
                        "article_lookup_conflict": article_lookup_conflict,
                        "reason_code": article_sanity_reason,
                    }
                )
            if article_match is not None and not article_sanity_reason:
                article_reason = "Exact article match from input column."
                resolution_source = "article_exact"
                if article_source == "text":
                    article_reason = "Exact article match extracted from row text."
                    resolution_source = "article_extracted_exact"
                elif article_lookup_conflict:
                    article_reason = "Exact article match from input column; column article took priority over text."
                result = self._build_result_from_item(
                    article_match,
                    1.0,
                    resolution_source,
                    False,
                    "",
                    article_reason,
                )
                return _finalize(result, stage_of_failure="resolved", reason_code="resolved")

            cable_designation_match = self._lookup_catalog_item_by_cable_designation(query_text, query_article)
            if cable_designation_match is not None:
                trace_steps.append(
                    {
                        "stage": "designation_lookup",
                        "status": "hit",
                        "designation_source": article_source if query_article else "query",
                    }
                )
                result = self._build_result_from_item(
                    cable_designation_match,
                    0.995,
                    "article_designation_exact" if query_article else "designation_exact",
                    False,
                    "",
                    "Техническое обозначение кабеля из строки точно сопоставлено с номенклатурой каталога.",
                )
                return _finalize(result, stage_of_failure="resolved", reason_code="resolved")

            if query_article:
                article_series_candidates = self._lookup_catalog_items_by_article_series(query_article, query_features)
                if article_series_candidates:
                    trace_steps.append(
                        {
                            "stage": "article_lookup",
                            "status": "series_candidates",
                            "article_source": article_source,
                            "query_article": query_article,
                            "series_candidate_count": len(article_series_candidates),
                        }
                    )
                    article_series_match = self._best_article_series_match(
                        query_features,
                        article_series_candidates,
                        article=query_article,
                    )
                    if article_series_match is not None:
                        result = self._build_result_from_item(
                            article_series_match,
                            0.985,
                            "article_series_local",
                            True,
                            "",
                            "Сопоставлено по расширенной серии артикула с проверкой на смысловую и размерную совместимость.",
                        )
                        return _finalize(result, stage_of_failure="resolved", reason_code="resolved")

            exact_match = self._lookup_catalog_item_by_name(query_text)
            if exact_match:
                exact_source = self._exact_resolution_source_for_item(query_text, query_article, article_source, exact_match) or "name_exact"
                exact_score = self._exact_resolution_score(exact_source)
                preferred_result = self._build_result_from_item(exact_match, exact_score, exact_source, False, "", "")
                preferred_entry = {"item": exact_match, "score": exact_score, "lexical_score": exact_score}
            else:
                normalized_match = self._lookup_catalog_item_by_normalized_name(normalized_query)
                if normalized_match:
                    exact_source = self._exact_resolution_source_for_item(
                        query_text,
                        query_article,
                        article_source,
                        normalized_match,
                    ) or "normalized_name_exact"
                    exact_score = self._exact_resolution_score(exact_source)
                    preferred_result = self._build_result_from_item(
                        normalized_match,
                        exact_score,
                        exact_source,
                        False,
                        "",
                        "",
                    )
                    preferred_entry = {"item": normalized_match, "score": exact_score, "lexical_score": exact_score}
                else:
                    local_direct = self._try_local_semantic_match(query_text)
                    if local_direct:
                        matched_item = local_direct.pop("_matched_item", None)
                        direct_source = self._exact_resolution_source_for_item(
                            query_text,
                            query_article,
                            article_source,
                            matched_item,
                        )
                        if matched_item and direct_source:
                            direct_score = self._exact_resolution_score(direct_source)
                            preferred_result = self._build_result_from_item(matched_item, direct_score, direct_source, False, "", "")
                            preferred_entry = {"item": matched_item, "score": direct_score, "lexical_score": direct_score}
                        else:
                            preferred_result = dict(local_direct)
                            if matched_item:
                                preferred_entry = {
                                    "item": matched_item,
                                    "score": float(local_direct["similarity_score"]),
                                    "lexical_score": float(local_direct["similarity_score"]),
                                }

            if preferred_result and str(preferred_result.get("resolution_source") or "") in {
                "article_exact",
                "article_extracted_exact",
                "name_exact",
                "normalized_name_exact",
            }:
                return _finalize(preferred_result, stage_of_failure="resolved", reason_code="resolved")

            self._activate_semantic_resolver_path(query_features)
            ranked_branches = self._rank_branches(query_features)
            query_features["ranked_branches"] = ranked_branches
            branch_paths = [entry["path"] for entry in ranked_branches if entry.get("path")]
            if branch_paths and not query_category_key:
                query_category_key = branch_paths[0]
            local_recall_limit = int(getattr(self, "local_recall_pool", 300))
            retrieval_mode = "whole_category" if self._should_use_whole_category_retrieval(query_features) else "heuristic_fallback"
            retrieval_started_at = time.perf_counter()
            branch_candidates = self._typed_candidate_pool(query_text, query_features, local_recall_limit)
            query_category_key = self._clean_text_value(query_features.get("query_category_key"))
            if retrieval_mode == "whole_category":
                if not branch_candidates:
                    query_category_key = query_category_key or self._clean_text_value(query_features.get("branch_hint"))
                    branch_candidates = self._collect_branch_candidates(
                        branch_paths,
                        limit=None,
                        query_features=query_features,
                    )
            else:
                if branch_candidates:
                    fallback_candidates = self._collect_branch_candidates(
                        branch_paths,
                        limit=local_recall_limit,
                        query_features=query_features,
                    )
                    seen_candidates = {int(item.get("row_idx", -1)) for item in branch_candidates}
                    for item in fallback_candidates:
                        row_idx = int(item.get("row_idx", -1))
                        if row_idx in seen_candidates:
                            continue
                        branch_candidates.append(item)
                        seen_candidates.add(row_idx)
                        if len(branch_candidates) >= local_recall_limit:
                            break
                else:
                    branch_candidates = self._collect_branch_candidates(
                        branch_paths,
                        limit=local_recall_limit,
                        query_features=query_features,
                    )
            if article_series_candidates:
                merged_candidates: List[Dict[str, Any]] = []
                seen_row_idx: set[int] = set()
                for item in article_series_candidates + branch_candidates:
                    row_idx = int(item.get("row_idx", -1))
                    if row_idx in seen_row_idx:
                        continue
                    seen_row_idx.add(row_idx)
                    merged_candidates.append(item)
                branch_candidates = merged_candidates
            if not branch_candidates:
                branch_candidates = self._select_candidates(query_text, limit=local_recall_limit)
            duckdb_query_ms = round((time.perf_counter() - retrieval_started_at) * 1000, 2)

            local_candidate_pool = branch_candidates
            category_candidate_count = len(local_candidate_pool)
            category_rows_scanned = len(local_candidate_pool)
            scoring_started_at = time.perf_counter()
            scored_entries = self._score_candidates_locally(query_features, branch_candidates)
            python_scoring_ms = round((time.perf_counter() - scoring_started_at) * 1000, 2)
            if not scored_entries and getattr(self, "catalog_items", []):
                local_candidate_pool = self._select_candidates(query_text, limit=local_recall_limit)
                category_candidate_count = len(local_candidate_pool)
                category_rows_scanned = len(local_candidate_pool)
                scoring_started_at = time.perf_counter()
                scored_entries = self._score_candidates_locally(query_features, local_candidate_pool)
                python_scoring_ms = round((time.perf_counter() - scoring_started_at) * 1000, 2)
            if preferred_entry:
                preferred_key = int(preferred_entry["item"].get("row_idx", -1))
                seen_preferred = any(int(entry["item"].get("row_idx", -2)) == preferred_key for entry in scored_entries)
                if not seen_preferred:
                    scored_entries.append(preferred_entry)
                    scored_entries.sort(
                        key=lambda entry: (entry["score"], entry["lexical_score"], -int(entry["item"].get("row_idx", 0))),
                        reverse=True,
                    )
            all_scored_entries = list(scored_entries)
            compatibility_started_at = time.perf_counter()
            same_family_entries = [
                entry
                for entry in all_scored_entries
                if self._entity_family(entry["item"].get("entity_type", "")) == query_family
            ]
            compatible_entries_all = [
                entry for entry in all_scored_entries if not self._is_hard_incompatible_match(query_features, entry["item"])
            ]
            compatibility_filter_ms = round((time.perf_counter() - compatibility_started_at) * 1000, 2)
            trace_steps.append(
                {
                    "stage": "local_recall",
                    "status": "ok" if all_scored_entries else "empty",
                    "strictness": strictness,
                    "retrieval_mode": retrieval_mode,
                    "retrieval_backend": getattr(self, "retrieval_backend", "memory"),
                    "category_key": query_category_key or (branch_paths[0] if branch_paths else ""),
                    "category_candidate_count": category_candidate_count,
                    "category_rows_scanned": category_rows_scanned,
                    "duckdb_query_ms": duckdb_query_ms,
                    "python_scoring_ms": python_scoring_ms,
                    "compatibility_filter_ms": compatibility_filter_ms,
                    "local_pool_count": len(local_candidate_pool),
                    "scored_count": len(all_scored_entries),
                    "same_family_count": len(same_family_entries),
                    "compatible_count": len(compatible_entries_all),
                }
            )
            if not scored_entries:
                if not self._should_query_gemini_without_candidates(query_features):
                    result = self._build_missing_result(
                        query_text,
                        "Кандидаты в подходящей категории не найдены; позиция оставлена без свободного Gemini-подбора.",
                        compatibility_status="unresolved_no_compatible_candidates",
                        incompatibility_reason="no_compatible_candidates",
                    )
                    return _finalize(result, stage_of_failure="local_recall", reason_code="no_compatible_candidates")
                gemini_attempted = True
                gemini_started_at = time.perf_counter()
                gemini_result = self._match_with_gemini(query_text)
                gemini_total_ms += round((time.perf_counter() - gemini_started_at) * 1000, 2)
                gemini_model = str(gemini_result.get("gemini_model") or gemini_model or "")
                gemini_result_status = str(gemini_result.get("gemini_result_status") or gemini_result_status or "")
                trace_steps.append(
                    {
                        "stage": "gemini_selection",
                        "status": gemini_result_status or "completed",
                        "shortlist_count": int(gemini_result.get("gemini_shortlist_count") or 0),
                        "gemini_ms": round(gemini_total_ms, 2),
                    }
                )
                if self._clean_text_value(gemini_result.get("found_name")) and gemini_result.get("found_name") != MISSING_POSITION_TEXT:
                    return _finalize(gemini_result, stage_of_failure="resolved", reason_code="resolved")
                if preferred_result:
                    preferred_result["requires_review"] = "да"
                    preferred_result["confidence_level"] = self._confidence_level_from_score(
                        preferred_result["similarity_score"], True
                    )
                    preferred_result["reason"] = (
                        preferred_result.get("reason")
                        or "Gemini не подтвердил позицию; сохранен лучший локальный кандидат. Требуется проверка."
                    )
                    preferred_result["resolution_source"] = "gemini_fallback"
                    self._save_to_cache(
                        query_text,
                        preferred_result["found_name"],
                        preferred_result["price"],
                        preferred_result["article"] or "",
                        preferred_result["similarity_score"],
                        "gemini_fallback",
                    )
                    trace_steps.append({"stage": "fallback_policy", "status": "accepted", "fallback": "gemini_fallback"})
                    return _finalize(preferred_result, stage_of_failure="resolved", reason_code="resolved")
                return _finalize(
                    gemini_result,
                    stage_of_failure="gemini_selection",
                    reason_code=gemini_result.get("incompatibility_reason") or "gemini_returned_no_valid_candidate",
                )

            logger.info(
                "Gemini compatibility filter: query=%s scored=%s compatible=%s filtered_out=%s strictness=%s",
                query_text[:120],
                len(all_scored_entries),
                len(compatible_entries_all),
                max(0, len(all_scored_entries) - len(compatible_entries_all)),
                strictness,
            )
            if compatible_entries_all:
                scored_entries = compatible_entries_all
            else:
                trace_steps.append(
                    {
                        "stage": "compatibility_filter",
                        "status": "failed",
                        "reason_code": "no_compatible_candidates",
                    }
                )
                result = self._build_missing_result(
                    query_text,
                    "Точные совместимые кандидаты не найдены: ближайшие совпадения конфликтуют с типом или ключевыми признаками позиции.",
                    alternatives=self._format_alternatives(all_scored_entries),
                    compatibility_status="unresolved_no_compatible_candidates",
                    incompatibility_reason="no_compatible_candidates",
                )
                return _finalize(
                    result,
                    stage_of_failure="compatibility_filter" if same_family_entries else "local_recall",
                    reason_code="no_compatible_candidates",
                )

            best_entry = scored_entries[0]
            best_score = float(best_entry["score"])
            second_score = float(scored_entries[1]["score"]) if len(scored_entries) > 1 else 0.0
            margin = best_score - second_score
            top_branch_gap = self._top_branch_gap(ranked_branches)
            strong_local = (
                best_score >= getattr(self, "local_confidence_threshold", 0.92)
                and margin >= getattr(self, "local_margin_threshold", 0.08)
                and top_branch_gap >= 0.15
                and query_features.get("row_type") == "item"
                and self._compatibility_label(query_features, best_entry["item"]) == "compatible"
            )
            ambiguous = (
                query_features.get("row_type") == "section"
                or margin < max(0.05, getattr(self, "local_margin_threshold", 0.08))
                or top_branch_gap < 0.15
            )

            shortlist_count = min(len(scored_entries), int(getattr(self, "gemini_shortlist_limit", 96)))
            logger.info(
                "Gemini shortlist prepared: query=%s local_pool=%s scored=%s shortlist=%s",
                query_text[:120],
                len(local_candidate_pool),
                len(scored_entries),
                shortlist_count,
            )

            weak_shortlist = self._is_weak_shortlist(scored_entries, ranked_branches)
            gemini_result: Optional[Dict[str, Any]] = None
            use_candidate_tiebreaker = ambiguous and self._should_use_candidate_tiebreaker_gemini(
                query_features,
                scored_entries,
                margin,
                top_branch_gap,
            )
            if not use_candidate_tiebreaker:
                trace_steps.append(
                    {
                        "stage": "gemini_selection",
                        "status": "skipped",
                        "reason_code": "candidate_tiebreaker_not_needed",
                    }
                )
            elif weak_shortlist and bool(getattr(self, "skip_weak_shortlist", False)):
                logger.info(
                    "Gemini skipped for weak shortlist: query=%s reason=weak_shortlist",
                    query_text[:120],
                )
                trace_steps.append({"stage": "gemini_selection", "status": "skipped", "reason_code": "weak_shortlist_skipped"})
            else:
                gemini_attempted = True
                gemini_started_at = time.perf_counter()
                gemini_result = self._resolve_ambiguous_candidates_with_gemini(
                    query_text,
                    query_features,
                    branch_paths,
                    scored_entries,
                    source_label="candidate_tiebreaker_gemini",
                )
                gemini_total_ms += round((time.perf_counter() - gemini_started_at) * 1000, 2)
                if gemini_result is not None:
                    gemini_model = str(gemini_result.get("gemini_model") or gemini_model or "")
                    gemini_result_status = str(gemini_result.get("gemini_result_status") or gemini_result_status or "")
                    trace_steps.append(
                        {
                            "stage": "gemini_selection",
                            "status": gemini_result_status or "completed",
                            "shortlist_count": int(gemini_result.get("gemini_shortlist_count") or 0),
                            "compatibility_status": str(gemini_result.get("compatibility_status") or ""),
                            "gemini_ms": round(gemini_total_ms, 2),
                        }
                    )
            if gemini_result:
                if not self._should_accept_weak_gemini_result(
                    gemini_result,
                    compatible_entries_all,
                    query_features,
                    retrieval_mode,
                ):
                    logger.info(
                        "🧠 Weak Gemini result rejected in favor of local compatible candidates: query=%s compatible=%s retrieval_mode=%s",
                        query_text[:120],
                        len(compatible_entries_all),
                        retrieval_mode,
                    )
                    trace_steps.append(
                        {
                            "stage": "gemini_selection",
                            "status": "rejected",
                            "reason_code": "weakly_compatible_rejected_local_compatible_exists",
                        }
                    )
                    gemini_result = None
                else:
                    if self._clean_text_value(gemini_result.get("found_name")) and gemini_result.get("found_name") != MISSING_POSITION_TEXT:
                        return _finalize(gemini_result, stage_of_failure="resolved", reason_code="resolved")
                    return _finalize(
                        gemini_result,
                        stage_of_failure="gemini_selection",
                        reason_code=gemini_result.get("incompatibility_reason") or "gemini_returned_no_valid_candidate",
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
                return _finalize(result, stage_of_failure="resolved", reason_code="resolved")

            best_compatible = self._best_compatible_local_entry(query_features, scored_entries)
            best_weak = self._best_compatible_local_entry(query_features, scored_entries, allow_weak=True)
            if strictness == "strict":
                if best_compatible is None:
                    assembly_entries = self._assembly_scored_entries(query_features)
                    if assembly_entries:
                        best_assembly = assembly_entries[0]
                        best_assembly_item = best_assembly["item"]
                        best_assembly_family = self._entity_family(best_assembly_item.get("entity_type", ""))
                        assembly_reason = (
                            "assembly_possible_from_patch_cable"
                            if best_assembly_family == "cable"
                            else "assembly_possible_from_bulk_cable"
                        )
                        trace_steps.append(
                            {
                                "stage": "fallback_policy",
                                "status": "accepted",
                                "fallback": "assembly_possible_local_fallback",
                                "reason_code": assembly_reason,
                                "assembly_candidates": len(assembly_entries),
                            }
                        )
                        result = self._build_result_from_item(
                            best_assembly_item,
                            float(best_assembly["score"]),
                            "assembly_possible_local_fallback",
                            True,
                            self._format_alternatives(assembly_entries, skip_first=True),
                            "Готовый патч-корд с нужными параметрами не найден; сохранена patch-like кабельная заготовка как материал под сборку. Требуется инженерная проверка.",
                            compatibility_status="assembly_possible",
                            incompatibility_reason=assembly_reason,
                        )
                        return _finalize(result, stage_of_failure="resolved", reason_code="resolved")
                    trace_steps.append(
                        {
                            "stage": "compatibility_filter",
                            "status": "failed",
                            "reason_code": "strict_class_no_compatible_candidate",
                        }
                    )
                    result = self._build_missing_result(
                        query_text,
                        "Нет совместимого кандидата для строго типизированной позиции.",
                        alternatives=self._format_alternatives(scored_entries),
                        compatibility_status="unresolved_no_compatible_candidates",
                        incompatibility_reason="strict_class_no_compatible_candidate",
                    )
                    return _finalize(
                        result,
                        stage_of_failure="compatibility_filter" if same_family_entries else "local_recall",
                        reason_code="strict_class_no_compatible_candidate",
                    )
            if best_compatible is not None and not self._is_strict_fallback_allowed(query_features, best_compatible["item"]):
                query_family = self._entity_family(query_features.get("entity_type", ""))
                candidate_family = self._entity_family(best_compatible["item"].get("entity_type", ""))
                logger.info(
                    "🧠 Strict fallback rejected: query=%s query_family=%s candidate_family=%s reason=%s",
                    query_text[:120],
                    query_family or "other",
                    candidate_family or "other",
                    "strict_fallback_family_mismatch",
                )
                trace_steps.append(
                    {
                        "stage": "fallback_policy",
                        "status": "rejected",
                        "reason_code": "strict_fallback_family_mismatch",
                    }
                )
                if strictness == "strict":
                    result = self._build_missing_result(
                        query_text,
                        "Локальный fallback отклонен: лучший кандидат относится к несовместимому товарному семейству.",
                        alternatives=self._format_alternatives(scored_entries),
                        compatibility_status="unresolved_no_compatible_candidates",
                        incompatibility_reason="strict_fallback_family_mismatch",
                    )
                    return _finalize(result, stage_of_failure="fallback_policy", reason_code="strict_fallback_family_mismatch")
                best_compatible = None
            if best_compatible is not None:
                trace_steps.append({"stage": "fallback_policy", "status": "accepted", "fallback": "compatible_local_fallback"})
                result = self._build_result_from_item(
                    best_compatible["item"],
                    float(best_compatible["score"]),
                    "compatible_local_fallback",
                    True,
                    self._format_alternatives(scored_entries, skip_first=True),
                    "Gemini не подтвердил позицию; сохранен лучший локально совместимый кандидат. Требуется проверка.",
                    compatibility_status="compatible",
                )
                self._save_to_cache(
                    query_text,
                    result["found_name"],
                    result["price"],
                    result["article"] or "",
                    result["similarity_score"],
                    "compatible_local_fallback",
                )
                return _finalize(result, stage_of_failure="resolved", reason_code="resolved")

            if best_weak is not None and not self._should_reject_weak_resolution_in_exact_mode(query_features):
                trace_steps.append({"stage": "fallback_policy", "status": "accepted", "fallback": "weak_compatible_fallback"})
                weak_reason = self._explain_incompatibility(query_features, best_weak["item"]) or "weak_compatible_shortlist"
                result = self._build_result_from_item(
                    best_weak["item"],
                    float(best_weak["score"]),
                    "weak_compatible_fallback",
                    True,
                    self._format_alternatives(scored_entries, skip_first=True),
                    "Gemini не подтвердил полное совпадение; сохранен частично совместимый кандидат. Требуется проверка.",
                    compatibility_status="weakly_compatible",
                    incompatibility_reason=weak_reason,
                )
                self._save_to_cache(
                    query_text,
                    result["found_name"],
                    result["price"],
                    result["article"] or "",
                    result["similarity_score"],
                    "weak_compatible_fallback",
                )
                return _finalize(result, stage_of_failure="resolved", reason_code="resolved")
            if best_weak is not None:
                trace_steps.append(
                    {
                        "stage": "fallback_policy",
                        "status": "rejected",
                        "reason_code": "weakly_compatible_rejected_exact_mode",
                    }
                )

            trace_steps.append(
                {
                    "stage": "fallback_policy",
                    "status": "failed",
                    "reason_code": "no_confirmed_compatible_candidate",
                }
            )
            result = self._build_missing_result(
                query_text,
                "Совместимый кандидат не подтвержден; позиция оставлена без сопоставления.",
                alternatives=self._format_alternatives(scored_entries),
                compatibility_status="unresolved_no_compatible_candidates",
                incompatibility_reason="no_confirmed_compatible_candidate",
            )
            unresolved_stage = "gemini_selection" if gemini_attempted else ("compatibility_filter" if same_family_entries else "local_recall")
            return _finalize(result, stage_of_failure=unresolved_stage, reason_code="no_confirmed_compatible_candidate")

        except Exception as exc:
            logger.error("Matching error: %s", exc, exc_info=True)
            result = self._build_missing_result(query, "", error=str(exc), incompatibility_reason="runtime_exception")
            trace_steps.append({"stage": "runtime_error", "status": "failed", "reason_code": "runtime_exception"})
            return _finalize(result, stage_of_failure="runtime_error", reason_code="runtime_exception")

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

    @staticmethod
    def _unpack_match_task(task: Tuple[Any, ...]) -> Tuple[int, str, Dict[str, Any]]:
        if len(task) >= 3:
            idx, query, context = task[0], task[1], task[2]
            return int(idx), str(query), dict(context) if isinstance(context, dict) else {}
        idx, query = task[0], task[1]
        return int(idx), str(query), {}

    def _probe_cache_with_context(self, query: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        local_context = getattr(self, "_match_context_local", None)
        if local_context is not None:
            local_context.payload = dict(context or {})
        try:
            return self._get_from_cache(query)
        finally:
            if local_context is not None:
                local_context.payload = None

    def _execute_match_task(self, query: str, context: Dict[str, Any], *, use_cache: bool = True) -> Dict[str, Any]:
        local_context = getattr(self, "_match_context_local", None)
        if local_context is not None:
            local_context.payload = dict(context or {})
        try:
            return self.match(query, use_cache=use_cache)
        finally:
            if local_context is not None:
                local_context.payload = None

    def _run_matches_parallel(
        self,
        tasks: List[Tuple[Any, ...]],
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> Iterator[Tuple[int, Dict[str, Any]]]:
        if not tasks:
            return

        workers = min(max(1, int(getattr(self, "parallel_requests", 1))), len(tasks))
        if workers <= 1:
            for task in tasks:
                idx, query, context = self._unpack_match_task(task)
                if cancel_requested is not None and cancel_requested():
                    logger.info("🛑 Match processing cancelled before row idx=%s", idx)
                    return
                yield idx, self._execute_match_task(query, context, use_cache=True)
            return

        pool = ThreadPoolExecutor(max_workers=workers)
        future_map: Dict[Any, int] = {}
        for task in tasks:
            idx, query, context = self._unpack_match_task(task)
            future_map[pool.submit(self._execute_match_task, query, context, use_cache=True)] = idx
        pending = set(future_map)
        completed = 0
        total = len(tasks)
        cancelled = False
        try:
            while pending:
                if cancel_requested is not None and cancel_requested():
                    cancelled = True
                    logger.info(
                        "🛑 Match processing cancellation requested: completed=%s total=%s pending=%s",
                        completed,
                        total,
                        len(pending),
                    )
                    for future in pending:
                        future.cancel()
                    break

                done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                if not done:
                    continue

                for future in done:
                    idx = future_map[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = self._build_missing_result("", "", error=str(exc))
                    completed += 1
                    if completed % 10 == 0 or completed == total:
                        logger.info("Processed %s/%s rows", completed, total)
                    yield idx, result
        finally:
            pool.shutdown(wait=not cancelled, cancel_futures=cancelled)

    def _prioritize_match_tasks(self, tasks: List[Tuple[Any, ...]]) -> List[Tuple[Any, ...]]:
        prioritized: List[Tuple[Tuple[int, int, int, int, int, int], Tuple[Any, ...]]] = []
        cache_hits = 0
        for task in tasks:
            idx, query, context = self._unpack_match_task(task)
            query_text = self._clean_text_value(query)
            cache_rank = 1
            try:
                if query_text and self._probe_cache_with_context(query_text, context):
                    cache_rank = 0
                    cache_hits += 1
            except Exception as exc:
                logger.debug("Task prioritization cache probe failed for query=%s: %s", query_text[:120], exc)

            row_type_rank = 1
            broad_family_rank = 0
            query_length_rank = len(query_text)
            article_rank = 0 if self._normalize_article_lookup_value(context.get("query_article")) else 1
            if cache_rank != 0 and query_text:
                try:
                    query_features = self._extract_query_features(query_text)
                    row_type_rank = 0 if self._clean_text_value(query_features.get("row_type")) == "section" else 1
                    query_family = self._entity_family(query_features.get("entity_type", ""))
                    broad_family_rank = 1 if query_family in {"rack", "sensor", "rack_accessory_strict"} else 0
                except Exception as exc:
                    logger.debug("Task prioritization feature probe failed for query=%s: %s", query_text[:120], exc)

            prioritized.append(
                ((cache_rank, article_rank, row_type_rank, broad_family_rank, query_length_rank, idx), task)
            )

        prioritized.sort(key=lambda entry: entry[0])
        if prioritized:
            logger.info(
                "🧠 Match task prioritization: tasks=%s cache_hits=%s parallel_workers=%s",
                len(prioritized),
                cache_hits,
                min(max(1, int(getattr(self, "parallel_requests", 1))), len(prioritized)),
            )
        return [task for _priority, task in prioritized]

    def _compose_not_found_reason(self, query: str, result: Dict[str, Any]) -> str:
        query_text = str(query or "").strip()
        model_reason = str((result or {}).get("reason") or "").strip()
        model_error = str((result or {}).get("error") or "").strip()
        incompatibility_reason = str((result or {}).get("incompatibility_reason") or "").strip()
        if model_error:
            return (
                f"Позиция '{query_text}' не сопоставлена из-за ошибки обращения к модели/сервису: {model_error}. "
                "Рекомендуется повторить попытку позже и проверить доступность API/лимиты."
            )
        if incompatibility_reason:
            return (
                f"Позиция '{query_text}' не найдена: совместимый кандидат не подтвержден. "
                f"Причина: {incompatibility_reason}. "
                "Проверьте тип позиции, ключевые технические признаки и наличие релевантного аналога в каталоге."
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

    def process_excel(
        self,
        excel_path: str,
        output_path: str | None = None,
        progress_callback: Callable[..., None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        logger.info("Start processing Excel: %s", excel_path)
        if progress_callback is not None:
            progress_callback(stage="reading_excel", message="Чтение Excel-файла")
        df = pd.read_excel(excel_path)
        df = self._promote_embedded_header_row(df)
        query_column, article_column = self._resolve_input_columns(df)

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
            "Совместимость решения",
            "Причина несовместимости",
            "Этап отказа",
            "Код причины",
            "Класс причины",
            "Verifier decision",
            "Auto accept",
            "Gemini shortlist",
            "Gemini visible candidates",
            "Gemini truncated",
        ):
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
            "gemini_rows_total": 0,
            "gemini_rows_confirmed_compatible": 0,
            "gemini_rows_weakly_compatible": 0,
            "gemini_rows_rejected_incompatible": 0,
            "unresolved_no_compatible_candidates": 0,
            "compatible_local_fallback_count": 0,
            "weak_compatible_fallback_count": 0,
            "assembly_possible_count": 0,
            "strict_class_unresolved_count": 0,
            "article_exact_count": 0,
            "article_extracted_exact_count": 0,
            "name_exact_count": 0,
            "normalized_name_exact_count": 0,
            "diagnostic_stage_counts": {},
            "diagnostic_reason_class_counts": {},
            "diagnostic_reason_code_counts": {},
            "matcher_init_ms": round(float(getattr(self, "matcher_init_ms", 0.0)), 2),
            "retrieval_backend": str(getattr(self, "retrieval_backend", "memory") or "memory"),
            "retrieval_mode": str(getattr(self, "retrieval_mode", "legacy_limited") or "legacy_limited"),
            "input_query_column": str(query_column),
            "input_article_column": str(article_column or ""),
            "duckdb_category_query_ms_total": 0.0,
            "python_scoring_ms_total": 0.0,
            "compatibility_filter_ms_total": 0.0,
            "gemini_total_ms_total": 0.0,
            "category_candidate_count_total": 0,
            "category_rows_scanned_total": 0,
        }
        diagnostic_rows: List[dict[str, Any]] = []
        diagnostic_stage_counts: Counter[str] = Counter()
        diagnostic_reason_class_counts: Counter[str] = Counter()
        diagnostic_reason_code_counts: Counter[str] = Counter()
        tasks: List[Tuple[int, str, Dict[str, Any]]] = []
        for idx, row in df.iterrows():
            query = str(row[query_column]).strip()
            if not query or query.lower() == "nan":
                continue
            if query.strip().lower() in {"наименование", "наименование оборудования, материалов и кабелей", "nomenclature"}:
                continue
            input_article = self._clean_text_value(row.get(article_column)) if article_column else ""
            extracted_article = self._extract_query_article_from_text(query)
            tasks.append(
                (
                    idx,
                    query,
                    {
                        "input_article": input_article,
                        "extracted_article": extracted_article,
                        "query_article": input_article or extracted_article,
                        "article_source": "column" if input_article else ("text" if extracted_article else "none"),
                        "query_column": str(query_column),
                        "article_column": str(article_column or ""),
                    },
                )
            )

        tasks = self._prioritize_match_tasks(tasks)
        stats["total"] = len(tasks)
        if progress_callback is not None:
            progress_callback(
                stage="matching",
                current=0,
                total=len(tasks),
                message=f"Подготовлено строк к обработке: {len(tasks)}",
            )
        task_query_map = {idx: query for idx, query, _context in tasks}
        processed_count = 0
        for idx, result in self._run_matches_parallel(tasks, cancel_requested=cancel_requested):
            processed_count += 1
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
            df.at[idx, "Совместимость решения"] = result.get("compatibility_status")
            df.at[idx, "Причина несовместимости"] = result.get("incompatibility_reason")
            df.at[idx, "Verifier decision"] = result.get("verifier_decision")
            df.at[idx, "Auto accept"] = bool(result.get("auto_accept"))
            df.at[idx, "Этап отказа"] = result.get("stage_of_failure")
            df.at[idx, "Код причины"] = result.get("reason_code")
            df.at[idx, "Класс причины"] = result.get("reason_class")
            df.at[idx, "Gemini shortlist"] = result.get("gemini_shortlist_count")
            df.at[idx, "Gemini visible candidates"] = result.get("gemini_visible_candidates")
            df.at[idx, "Gemini truncated"] = result.get("gemini_truncated_candidates")

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

            used_gemini = int(result.get("gemini_shortlist_count") or 0) > 0
            if used_gemini:
                stats["gemini_rows_total"] += 1

            compatibility_status = str(result.get("compatibility_status") or "").strip()
            if used_gemini and compatibility_status == "compatible":
                stats["gemini_rows_confirmed_compatible"] += 1
            elif used_gemini and compatibility_status == "weakly_compatible":
                stats["gemini_rows_weakly_compatible"] += 1
            elif used_gemini and compatibility_status == "rejected_incompatible_gemini":
                stats["gemini_rows_rejected_incompatible"] += 1
            elif compatibility_status == "unresolved_no_compatible_candidates":
                stats["unresolved_no_compatible_candidates"] += 1

            resolution_source = str(result.get("resolution_source") or "").strip()
            if resolution_source == "compatible_local_fallback":
                stats["compatible_local_fallback_count"] += 1
            elif resolution_source == "weak_compatible_fallback":
                stats["weak_compatible_fallback_count"] += 1
            elif resolution_source == "assembly_possible_local_fallback":
                stats["assembly_possible_count"] += 1
            elif resolution_source == "article_exact":
                stats["article_exact_count"] += 1
            elif resolution_source == "article_extracted_exact":
                stats["article_extracted_exact_count"] += 1
            elif resolution_source == "name_exact":
                stats["name_exact_count"] += 1
            elif resolution_source == "normalized_name_exact":
                stats["normalized_name_exact_count"] += 1

            incompatibility_reason = str(result.get("incompatibility_reason") or "").strip()
            if compatibility_status == "unresolved_no_compatible_candidates" and incompatibility_reason.startswith("strict_class"):
                stats["strict_class_unresolved_count"] += 1

            stage_of_failure = str(result.get("stage_of_failure") or "").strip()
            if not stage_of_failure:
                stage_of_failure = "resolved" if found_name != MISSING_POSITION_TEXT else "local_recall"
            reason_code = str(result.get("reason_code") or "").strip()
            if not reason_code:
                reason_code = "resolved" if stage_of_failure == "resolved" else "no_diagnostic_trace"
            reason_class = str(result.get("reason_class") or "").strip() or infer_reason_class(
                stage_of_failure,
                reason_code,
            )
            diagnostic_stage_counts[stage_of_failure] += 1
            diagnostic_reason_class_counts[reason_class] += 1
            diagnostic_reason_code_counts[reason_code] += 1
            df.at[idx, "Этап отказа"] = stage_of_failure
            df.at[idx, "Код причины"] = reason_code
            df.at[idx, "Класс причины"] = reason_class

            trace = result.get("diagnostic_trace")
            if isinstance(trace, dict):
                trace_row = dict(trace)
                trace_row["run_row_number"] = int(idx) + 2
                diagnostic_rows.append(trace_row)
                pipeline_counts = dict(trace.get("pipeline_counts") or {})
                stats["duckdb_category_query_ms_total"] += float(pipeline_counts.get("duckdb_query_ms") or 0.0)
                stats["python_scoring_ms_total"] += float(pipeline_counts.get("python_scoring_ms") or 0.0)
                stats["compatibility_filter_ms_total"] += float(pipeline_counts.get("compatibility_filter_ms") or 0.0)
                stats["gemini_total_ms_total"] += float(pipeline_counts.get("gemini_ms") or 0.0)
                stats["category_candidate_count_total"] += int(pipeline_counts.get("category_candidate_count") or 0)
                stats["category_rows_scanned_total"] += int(pipeline_counts.get("category_rows_scanned") or 0)

            if progress_callback is not None:
                progress_callback(
                    stage="matching",
                    current=processed_count,
                    total=len(tasks),
                    message=f"Обработано позиций: {processed_count} из {len(tasks)}",
                )

            if cancel_requested is not None and cancel_requested():
                logger.info("🛑 Excel processing interrupted after %s/%s rows", processed_count, len(tasks))
                break

        stats["diagnostic_stage_counts"] = dict(sorted(diagnostic_stage_counts.items()))
        stats["diagnostic_reason_class_counts"] = dict(sorted(diagnostic_reason_class_counts.items()))
        stats["diagnostic_reason_code_counts"] = dict(sorted(diagnostic_reason_code_counts.items()))
        for key in (
            "duckdb_category_query_ms_total",
            "python_scoring_ms_total",
            "compatibility_filter_ms_total",
            "gemini_total_ms_total",
        ):
            stats[key] = round(float(stats.get(key) or 0.0), 2)

        if cancel_requested is not None and cancel_requested():
            self.last_match_diagnostics_rows = diagnostic_rows
            self.last_match_diagnostics_payload = build_match_diagnostics_payload(
                diagnostic_rows,
                run_id=str(Path(excel_path).stem),
            )
            stats["_interrupted"] = True
            stats["processed"] = processed_count
            logger.info("Result processing interrupted before final save: processed=%s total=%s", processed_count, len(tasks))
            return df, stats

        if output_path is None:
            src = Path(excel_path)
            output_path = str(src.with_name(f"{src.stem}_matched{src.suffix}"))

        if progress_callback is not None:
            progress_callback(
                stage="saving_results",
                current=stats["total"],
                total=stats["total"],
                message="Сохранение итогового Excel-файла",
            )
        df.to_excel(output_path, index=False)
        self.last_match_diagnostics_rows = diagnostic_rows
        self.last_match_diagnostics_payload = build_match_diagnostics_payload(
            diagnostic_rows,
            run_id=str(Path(excel_path).stem),
        )
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
