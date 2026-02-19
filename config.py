"""
Shared runtime configuration for ReMo tools.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

DEFAULT_UPLOAD_DIR = Path(r"D:\Data\Downloads\upload")
DEFAULT_CATALOG_CSV_NAME = "price_clean.csv"
DEFAULT_PRICE_RAW_CSV_NAME = "price.csv"
DEFAULT_PRICE_CONVERTED_CSV_NAME = "price_converted.csv"
DEFAULT_SAMPLE_XLSX_NAME = "РеМо_Шаблон_коммерческого_предложения_020625.xlsx"


def _normalize_path(raw: str | Path) -> Path:
    text = str(raw).strip()
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
