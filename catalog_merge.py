"""Helpers for building a single merged catalog CSV from multiple supplier catalogs."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

import pandas as pd

CANONICAL_NAME_COLUMN = "Наименование"
CANONICAL_ARTICLE_COLUMN = "Артикул"
CANONICAL_PRICE_COLUMN = "Цена розничная"


def _normalize_text(text: str) -> str:
    lowered = str(text or "").lower().replace("ё", "е")
    lowered = re.sub(r"[^a-zа-я0-9]+", " ", lowered)
    return " ".join(lowered.split())


def _catalog_sources(clean_dir: Path, output_path: Path) -> list[Path]:
    candidates = sorted(
        path for path in clean_dir.glob("*_clean.csv")
        if path.is_file() and path.resolve() != output_path.resolve()
    )
    return candidates


def _build_dedupe_key(df: pd.DataFrame) -> pd.Series:
    article_key = df[CANONICAL_ARTICLE_COLUMN].fillna("").astype(str).str.strip().str.lower()
    name_key = df[CANONICAL_NAME_COLUMN].fillna("").astype(str).map(_normalize_text)
    return article_key.where(article_key != "", name_key)


def merge_catalog_frames(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    prepared_frames: list[pd.DataFrame] = []
    for source_order, frame in enumerate(frames):
        current = frame.copy()
        for column in (CANONICAL_NAME_COLUMN, CANONICAL_ARTICLE_COLUMN, CANONICAL_PRICE_COLUMN):
            if column not in current.columns:
                current[column] = None

        current["__source_order"] = source_order
        current["__has_article"] = current[CANONICAL_ARTICLE_COLUMN].fillna("").astype(str).str.strip() != ""
        current["__has_price"] = pd.to_numeric(current[CANONICAL_PRICE_COLUMN], errors="coerce").notna()
        current["__dedupe_key"] = _build_dedupe_key(current)
        prepared_frames.append(current)

    if not prepared_frames:
        raise ValueError("Нет входных фреймов для объединения")

    merged = pd.concat(prepared_frames, ignore_index=True)

    # При дублях предпочитаем записи с артикулом и валидной ценой,
    # затем порядок источников (детерминированно по имени файла).
    merged = merged.sort_values(
        by=["__dedupe_key", "__has_article", "__has_price", "__source_order"],
        ascending=[True, False, False, True],
    )
    deduped = merged.drop_duplicates(subset=["__dedupe_key"], keep="first")

    return deduped.drop(columns=["__source_order", "__has_article", "__has_price", "__dedupe_key"])


def build_merged_catalog(clean_dir: Path, output_path: Path) -> Path:
    clean_dir = Path(clean_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sources = _catalog_sources(clean_dir, output_path)
    if not sources:
        raise FileNotFoundError(f"В папке {clean_dir} не найдено файлов *_clean.csv")

    latest_source_mtime = max(path.stat().st_mtime for path in sources)
    if output_path.exists() and output_path.stat().st_mtime >= latest_source_mtime:
        return output_path

    frames = [pd.read_csv(path, sep=';', encoding='utf-8') for path in sources]
    merged = merge_catalog_frames(frames)
    merged.to_csv(output_path, sep=';', index=False, encoding='utf-8')
    return output_path
