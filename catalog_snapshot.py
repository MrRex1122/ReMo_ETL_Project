"""Utilities for inspecting active catalog snapshots and duplicate diagnostics."""

from __future__ import annotations

from pathlib import Path
import re

import pandas as pd

from catalog_merge import build_merged_catalog
from config import get_catalog_csv_path


def resolve_catalog_path_for_inspection(db_csv_value: str | None) -> Path:
    base_path = get_catalog_csv_path(db_csv_value)
    if base_path.is_dir():
        return build_merged_catalog(base_path, base_path / "price_clean_merged.csv")
    return base_path


def _normalize_key(value: str) -> str:
    lowered = str(value or "").lower().replace("ё", "е")
    lowered = re.sub(r"[^a-zа-я0-9]+", " ", lowered)
    return " ".join(lowered.split())


def build_duplicate_report(catalog_df: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    working = catalog_df.copy()
    article_series = working.get('Артикул', pd.Series([''] * len(working), index=working.index))
    name_series = working.get('Наименование', pd.Series([''] * len(working), index=working.index))

    article_key = article_series.fillna('').astype(str).str.strip().str.lower()
    name_key = name_series.fillna('').astype(str).map(_normalize_key)

    by_article = article_key.ne('') & article_key.duplicated(keep=False)
    by_name = name_key.ne('') & name_key.duplicated(keep=False)
    duplicate_mask = by_article | by_name

    duplicate_df = working[duplicate_mask].copy()
    if not duplicate_df.empty:
        duplicate_df.insert(0, 'Дубль по артикулу', by_article[duplicate_df.index].map({True: 'да', False: ''}))
        duplicate_df.insert(1, 'Дубль по наименованию', by_name[duplicate_df.index].map({True: 'да', False: ''}))

    stats = {
        'rows_total': int(len(working)),
        'duplicates_total': int(duplicate_mask.sum()),
        'duplicates_by_article': int(by_article.sum()),
        'duplicates_by_name': int(by_name.sum()),
    }
    return stats, duplicate_df


def prepare_catalog_snapshot(db_csv_value: str | None) -> tuple[pd.DataFrame, dict, Path]:
    resolved_path = resolve_catalog_path_for_inspection(db_csv_value)
    catalog_df = pd.read_csv(resolved_path, sep=';', encoding='utf-8')
    duplicate_stats, duplicate_df = build_duplicate_report(catalog_df)
    return catalog_df, {'stats': duplicate_stats, 'duplicate_df': duplicate_df}, resolved_path
