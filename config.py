"""
Shared runtime configuration for ReMo tools.
"""

from __future__ import annotations

import os
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parent

# Локальный дефолт для dev-среды. В Railway лучше использовать volume.
DEFAULT_UPLOAD_DIR = PROJECT_ROOT / "data"
DEFAULT_CATALOG_CSV_NAME = "price_clean.csv"
DEFAULT_PRICE_RAW_CSV_NAME = "price.csv"
DEFAULT_PRICE_CONVERTED_CSV_NAME = "price_converted.csv"
DEFAULT_SAMPLE_XLSX_NAME = "РеМо_Шаблон_коммерческого_предложения_020625.xlsx"
DEFAULT_MATCHER_CACHE_DB_NAME = "matcher_cache.db"
DEFAULT_MATCHER_MODELS = "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash"
DEFAULT_MATCHER_PARALLEL_REQUESTS = 50
DEFAULT_MATCHER_LOCAL_CONFIDENCE_THRESHOLD = 0.92
DEFAULT_MATCHER_LOCAL_MARGIN_THRESHOLD = 0.08
DEFAULT_MATCHER_CONTEXT_CHUNK_SIZE = 500
DEFAULT_MATCHER_MAX_CONTEXT_CHUNKS = 6
DEFAULT_MATCHER_RETRIEVAL_CANDIDATES = 3000
DEFAULT_MATCHER_GEMINI_SHORTLIST_LIMIT = 96
DEFAULT_MATCHER_GEMINI_CHUNK_SIZE = 12
DEFAULT_MATCHER_GEMINI_MAX_CHUNKS = 8
DEFAULT_MATCHER_LOCAL_RECALL_POOL = 300
DEFAULT_MATCHER_SKIP_WEAK_SHORTLIST = False


def _normalize_path(raw: str | Path) -> Path:
    text = str(raw).strip()
    # На Linux/macOS pathlib не считает Windows-путь с буквой диска абсолютным.
    if re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith("\\\\"):
        return Path(text)

    path = Path(text).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _pick_path(explicit: str | None, env_var: str, fallback: Path) -> Path:
    if explicit and explicit.strip():
        return _normalize_path(explicit)

    env = os.getenv(env_var)
    if env and env.strip():
        return _normalize_path(env)

    return fallback


def _railway_volume_dir() -> Path | None:
    raw = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    if not raw or not raw.strip():
        return None
    return _normalize_path(raw) / "remo_data"


def get_upload_dir() -> Path:
    env = os.getenv("REMO_UPLOAD_DIR")
    if env and env.strip():
        return _normalize_path(env)

    railway_dir = _railway_volume_dir()
    if railway_dir is not None:
        return railway_dir

    return DEFAULT_UPLOAD_DIR


def get_catalog_csv_path(explicit: str | None = None) -> Path:
    return _pick_path(explicit, "REMO_DB_CSV", get_upload_dir() / DEFAULT_CATALOG_CSV_NAME)


def get_price_raw_csv_path(explicit: str | None = None) -> Path:
    return _pick_path(explicit, "REMO_PRICE_RAW_CSV", get_upload_dir() / DEFAULT_PRICE_RAW_CSV_NAME)


def get_price_converted_csv_path(explicit: str | None = None) -> Path:
    return _pick_path(explicit, "REMO_PRICE_CONVERTED_CSV", get_upload_dir() / DEFAULT_PRICE_CONVERTED_CSV_NAME)


def get_sample_excel_path(explicit: str | None = None) -> Path:
    return _pick_path(explicit, "REMO_SAMPLE_XLSX", get_upload_dir() / DEFAULT_SAMPLE_XLSX_NAME)


def get_matcher_cache_db_path(explicit: str | None = None) -> Path:
    return _pick_path(explicit, "REMO_MATCHER_CACHE_DB", get_upload_dir() / DEFAULT_MATCHER_CACHE_DB_NAME)


def get_matcher_models() -> list[str]:
    raw = os.getenv("REMO_MATCHER_MODELS", DEFAULT_MATCHER_MODELS)
    values = [value.strip() for value in raw.split(",") if value.strip()]
    if values:
        return values
    return [value.strip() for value in DEFAULT_MATCHER_MODELS.split(",") if value.strip()]


def get_matcher_parallel_requests() -> int:
    raw = os.getenv("REMO_MATCHER_PARALLEL_REQUESTS", str(DEFAULT_MATCHER_PARALLEL_REQUESTS))
    try:
        value = int(raw)
        # Ограничиваем параллелизм, чтобы не упереться в rate-limit API.
        # Gemini 2.5 Flash: 2000 RPM ≈ 33 req/sec — допустимо до 50 concurrent.
        return min(50, max(1, value))
    except ValueError:
        return DEFAULT_MATCHER_PARALLEL_REQUESTS


def get_matcher_local_confidence_threshold() -> float:
    raw = os.getenv("REMO_MATCHER_LOCAL_CONFIDENCE_THRESHOLD", str(DEFAULT_MATCHER_LOCAL_CONFIDENCE_THRESHOLD))
    try:
        value = float(raw)
        return min(1.0, max(0.0, value))
    except ValueError:
        return DEFAULT_MATCHER_LOCAL_CONFIDENCE_THRESHOLD


def get_matcher_local_margin_threshold() -> float:
    raw = os.getenv("REMO_MATCHER_LOCAL_MARGIN_THRESHOLD", str(DEFAULT_MATCHER_LOCAL_MARGIN_THRESHOLD))
    try:
        value = float(raw)
        return min(1.0, max(0.0, value))
    except ValueError:
        return DEFAULT_MATCHER_LOCAL_MARGIN_THRESHOLD


def get_matcher_context_chunk_size() -> int:
    raw = os.getenv("REMO_MATCHER_CONTEXT_CHUNK_SIZE", str(DEFAULT_MATCHER_CONTEXT_CHUNK_SIZE))
    try:
        value = int(raw)
        return min(1000, max(50, value))
    except ValueError:
        return DEFAULT_MATCHER_CONTEXT_CHUNK_SIZE


def get_matcher_max_context_chunks() -> int:
    raw = os.getenv("REMO_MATCHER_MAX_CONTEXT_CHUNKS", str(DEFAULT_MATCHER_MAX_CONTEXT_CHUNKS))
    try:
        value = int(raw)
        return min(10, max(1, value))
    except ValueError:
        return DEFAULT_MATCHER_MAX_CONTEXT_CHUNKS


def get_matcher_retrieval_candidates() -> int:
    raw = os.getenv("REMO_MATCHER_RETRIEVAL_CANDIDATES", str(DEFAULT_MATCHER_RETRIEVAL_CANDIDATES))
    try:
        value = int(raw)
        return min(10000, max(100, value))
    except ValueError:
        return DEFAULT_MATCHER_RETRIEVAL_CANDIDATES


def get_matcher_gemini_shortlist_limit() -> int:
    raw = os.getenv("REMO_MATCHER_GEMINI_SHORTLIST_LIMIT", str(DEFAULT_MATCHER_GEMINI_SHORTLIST_LIMIT))
    try:
        value = int(raw)
        return min(200, max(24, value))
    except ValueError:
        return DEFAULT_MATCHER_GEMINI_SHORTLIST_LIMIT


def get_matcher_gemini_chunk_size() -> int:
    raw = os.getenv("REMO_MATCHER_GEMINI_CHUNK_SIZE", str(DEFAULT_MATCHER_GEMINI_CHUNK_SIZE))
    try:
        value = int(raw)
        return min(20, max(6, value))
    except ValueError:
        return DEFAULT_MATCHER_GEMINI_CHUNK_SIZE


def get_matcher_gemini_max_chunks() -> int:
    raw = os.getenv("REMO_MATCHER_GEMINI_MAX_CHUNKS", str(DEFAULT_MATCHER_GEMINI_MAX_CHUNKS))
    try:
        value = int(raw)
        return min(12, max(1, value))
    except ValueError:
        return DEFAULT_MATCHER_GEMINI_MAX_CHUNKS


def get_matcher_local_recall_pool() -> int:
    raw = os.getenv("REMO_MATCHER_LOCAL_RECALL_POOL", str(DEFAULT_MATCHER_LOCAL_RECALL_POOL))
    try:
        value = int(raw)
        return min(1000, max(100, value))
    except ValueError:
        return DEFAULT_MATCHER_LOCAL_RECALL_POOL


def get_matcher_skip_weak_shortlist() -> bool:
    raw = os.getenv("REMO_MATCHER_SKIP_WEAK_SHORTLIST")
    if raw is None:
        return DEFAULT_MATCHER_SKIP_WEAK_SHORTLIST
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return DEFAULT_MATCHER_SKIP_WEAK_SHORTLIST
