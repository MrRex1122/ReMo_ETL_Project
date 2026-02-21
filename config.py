"""
Shared runtime configuration for ReMo tools.
"""

from __future__ import annotations

import os
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parent

DEFAULT_UPLOAD_DIR = PROJECT_ROOT
DEFAULT_CATALOG_CSV_NAME = "price_clean.csv"
DEFAULT_PRICE_RAW_CSV_NAME = "price.csv"
DEFAULT_PRICE_CONVERTED_CSV_NAME = "price_converted.csv"
DEFAULT_SAMPLE_XLSX_NAME = "РеМо_Шаблон_коммерческого_предложения_020625.xlsx"
DEFAULT_MATCHER_CACHE_DB_NAME = "matcher_cache.db"
DEFAULT_MATCHER_MODELS = "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash,gemini-2.0-flash-lite,gemini-1.5-flash,gemini-1.5-flash-8b,gemini-1.5-pro,gemini-pro"
DEFAULT_MATCHER_CANDIDATE_LIMIT = 40
DEFAULT_MATCHER_CONTEXT_LINES = 60
DEFAULT_MATCHER_CATALOG_SAMPLE_ITEMS = 500
DEFAULT_MATCHER_LOCAL_CONFIDENCE_THRESHOLD = 0.92
DEFAULT_MATCHER_LOCAL_MARGIN_THRESHOLD = 0.08


def _normalize_path(raw: str | Path) -> Path:
    text = str(raw).strip()
    # На Linux/macOS pathlib не считает путь вида D:\... абсолютным.
    # Не префиксуем такие пути PROJECT_ROOT, чтобы не получать /app/D:\...
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


def get_upload_dir() -> Path:
    env = os.getenv("REMO_UPLOAD_DIR")
    if env and env.strip():
        return _normalize_path(env)
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
    return values or [value.strip() for value in DEFAULT_MATCHER_MODELS.split(",")]


def get_matcher_candidate_limit() -> int:
    raw = os.getenv("REMO_MATCHER_CANDIDATE_LIMIT", str(DEFAULT_MATCHER_CANDIDATE_LIMIT))
    try:
        value = int(raw)
        return max(1, value)
    except ValueError:
        return DEFAULT_MATCHER_CANDIDATE_LIMIT


def get_matcher_context_lines() -> int:
    raw = os.getenv("REMO_MATCHER_CONTEXT_LINES", str(DEFAULT_MATCHER_CONTEXT_LINES))
    try:
        value = int(raw)
        return max(1, value)
    except ValueError:
        return DEFAULT_MATCHER_CONTEXT_LINES


def get_matcher_catalog_sample_items() -> int:
    raw = os.getenv("REMO_MATCHER_CATALOG_SAMPLE_ITEMS", str(DEFAULT_MATCHER_CATALOG_SAMPLE_ITEMS))
    try:
        value = int(raw)
        return max(1, value)
    except ValueError:
        return DEFAULT_MATCHER_CATALOG_SAMPLE_ITEMS


def get_matcher_local_confidence_threshold() -> float:
    raw = os.getenv(
        "REMO_MATCHER_LOCAL_CONFIDENCE_THRESHOLD",
        str(DEFAULT_MATCHER_LOCAL_CONFIDENCE_THRESHOLD),
    )
    try:
        value = float(raw)
        return min(1.0, max(0.0, value))
    except ValueError:
        return DEFAULT_MATCHER_LOCAL_CONFIDENCE_THRESHOLD


def get_matcher_local_margin_threshold() -> float:
    raw = os.getenv(
        "REMO_MATCHER_LOCAL_MARGIN_THRESHOLD",
        str(DEFAULT_MATCHER_LOCAL_MARGIN_THRESHOLD),
    )
    try:
        value = float(raw)
        return min(1.0, max(0.0, value))
    except ValueError:
        return DEFAULT_MATCHER_LOCAL_MARGIN_THRESHOLD
