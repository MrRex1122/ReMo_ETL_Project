from __future__ import annotations

import re
from typing import Callable

import pandas as pd

CANONICAL_NAME_COLUMN = "Наименование"
CANONICAL_PRICE_COLUMN = "Цена розничная"
CANONICAL_ARTICLE_COLUMN = "Артикул"
REQUIRED_CATALOG_COLUMNS = (
    CANONICAL_NAME_COLUMN,
    CANONICAL_PRICE_COLUMN,
    CANONICAL_ARTICLE_COLUMN,
)

_COLUMN_ALIASES = {
    CANONICAL_NAME_COLUMN: (
        "наименование",
        "наименование товара",
        "наименование продукции",
        "номенклатура",
        "товар",
        "product name",
        "name",
    ),
    CANONICAL_PRICE_COLUMN: (
        "цена розничная",
        "розничная цена",
        "розница",
        "цена продажи",
        "цена",
        "retail price",
        "price",
    ),
    CANONICAL_ARTICLE_COLUMN: (
        "артикул",
        "артикул товара",
        "код товара",
        "код номенклатуры",
        "код",
        "sku",
        "vendor code",
        "партномер",
        "part number",
        "partnumber",
    ),
}


def normalize_header(value: object) -> str:
    text = str(value).replace("\ufeff", "").strip()
    return re.sub(r"\s+", " ", text)


def _normalize_lookup_key(value: object) -> str:
    return normalize_header(value).lower().replace("ё", "е")


def _looks_like_name_column(key: str) -> bool:
    return "наименован" in key or "номенклатур" in key or key in {"товар", "product name", "name"}


def _looks_like_price_column(key: str) -> bool:
    if "цена" in key and "закуп" not in key and "опт" not in key:
        return True
    return key in {"retail price", "price"}


def _looks_like_article_column(key: str) -> bool:
    if any(marker in key for marker in ("артикул", "sku", "партномер", "part number", "partnumber", "vendor code")):
        return True
    return key in {"код", "код товара", "код номенклатуры", "item code", "product code"}


def _pick_heuristic(canonical: str) -> Callable[[str], bool]:
    if canonical == CANONICAL_NAME_COLUMN:
        return _looks_like_name_column
    if canonical == CANONICAL_PRICE_COLUMN:
        return _looks_like_price_column
    return _looks_like_article_column


def _is_missing(series: pd.Series) -> pd.Series:
    as_text = series.astype(str).str.strip().str.lower()
    return series.isna() | as_text.eq("") | as_text.eq("nan")


def _is_alias_key(canonical: str, key: str) -> bool:
    alias_keys = {_normalize_lookup_key(item) for item in _COLUMN_ALIASES[canonical]}
    if key in alias_keys:
        return True
    return _pick_heuristic(canonical)(key)


def canonicalize_catalog_columns(df: pd.DataFrame, create_missing: bool = False) -> pd.DataFrame:
    result = df.copy()
    result.columns = [normalize_header(column) for column in result.columns]

    normalized_to_original: dict[str, str] = {}
    for column in result.columns:
        key = _normalize_lookup_key(column)
        normalized_to_original.setdefault(key, column)

    rename_map: dict[str, str] = {}
    used_originals: set[str] = set()

    for canonical, aliases in _COLUMN_ALIASES.items():
        if canonical in result.columns:
            continue

        matched_original = None
        for alias in aliases:
            alias_key = _normalize_lookup_key(alias)
            candidate = normalized_to_original.get(alias_key)
            if candidate and candidate not in used_originals:
                matched_original = candidate
                break

        if matched_original is None:
            heuristic = _pick_heuristic(canonical)
            for column in result.columns:
                if column in used_originals:
                    continue
                if heuristic(_normalize_lookup_key(column)):
                    matched_original = column
                    break

        if matched_original:
            rename_map[matched_original] = canonical
            used_originals.add(matched_original)

    if rename_map:
        result = result.rename(columns=rename_map)

    for canonical in REQUIRED_CATALOG_COLUMNS:
        if canonical not in result.columns:
            continue

        missing_mask = _is_missing(result[canonical])
        if not missing_mask.any():
            continue

        for column in result.columns:
            if column == canonical:
                continue
            if not _is_alias_key(canonical, _normalize_lookup_key(column)):
                continue

            source_missing = _is_missing(result[column])
            transfer_mask = missing_mask & ~source_missing
            if not transfer_mask.any():
                continue

            result.loc[transfer_mask, canonical] = result.loc[transfer_mask, column]
            missing_mask = _is_missing(result[canonical])
            if not missing_mask.any():
                break

    if create_missing:
        for canonical in REQUIRED_CATALOG_COLUMNS:
            if canonical not in result.columns:
                result[canonical] = pd.NA

    return result
