"""Helpers for building a single merged catalog CSV from multiple supplier catalogs."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Iterable, Iterator

import pandas as pd

logger = logging.getLogger(__name__)

CANONICAL_NAME_COLUMN = "Наименование"
CANONICAL_ARTICLE_COLUMN = "Артикул"
CANONICAL_PRICE_COLUMN = "Цена розничная"
DEFAULT_MERGE_CHUNKSIZE = 50000


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


def _warn_and_retry_bad_lines(path: Path, error: Exception, *, chunksize: int | None = None):
    logger.warning(
        "⚠️ Обнаружены битые строки в %s, повторное чтение с пропуском bad lines: %s",
        path,
        error,
    )
    kwargs = {
        "sep": ";",
        "encoding": "utf-8",
        "engine": "python",
        "on_bad_lines": "skip",
    }
    if chunksize is not None:
        kwargs["chunksize"] = chunksize
    return pd.read_csv(path, **kwargs)


def _read_catalog_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, sep=";", encoding="utf-8")
    except pd.errors.ParserError as error:
        return _warn_and_retry_bad_lines(path, error)


def _read_catalog_header(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, sep=";", encoding="utf-8", nrows=0)
    except pd.errors.ParserError as error:
        logger.warning(
            "⚠️ Обнаружены битые строки в %s, повторное чтение заголовка с пропуском bad lines: %s",
            path,
            error,
        )
        return pd.read_csv(
            path,
            sep=";",
            encoding="utf-8",
            engine="python",
            on_bad_lines="skip",
            nrows=0,
        )


def _iter_catalog_chunks(path: Path, *, chunksize: int = DEFAULT_MERGE_CHUNKSIZE) -> Iterator[pd.DataFrame]:
    try:
        yield from pd.read_csv(
            path,
            sep=";",
            encoding="utf-8",
            low_memory=False,
            chunksize=chunksize,
        )
    except pd.errors.ParserError as error:
        yield from _warn_and_retry_bad_lines(path, error, chunksize=chunksize)


def _prepare_merge_frame(frame: pd.DataFrame, source_order: int) -> pd.DataFrame:
    current = frame.copy()
    for column in (CANONICAL_NAME_COLUMN, CANONICAL_ARTICLE_COLUMN, CANONICAL_PRICE_COLUMN):
        if column not in current.columns:
            current[column] = None

    current["__source_order"] = source_order
    current["__has_article"] = current[CANONICAL_ARTICLE_COLUMN].fillna("").astype(str).str.strip() != ""
    current["__has_price"] = pd.to_numeric(current[CANONICAL_PRICE_COLUMN], errors="coerce").notna()
    current["__dedupe_key"] = _build_dedupe_key(current)
    return current


def _sqlite_temp_path(output_path: Path) -> Path:
    return output_path.with_suffix(f"{output_path.suffix}.merge.sqlite3")


def _cleanup_sqlite_sidecars(db_path: Path) -> None:
    for candidate in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if candidate.exists():
            candidate.unlink()


def _init_merge_db(db_path: Path) -> sqlite3.Connection:
    if db_path.exists():
        db_path.unlink()

    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(
        """
        CREATE TABLE merged_catalog (
            dedupe_key TEXT PRIMARY KEY,
            has_article INTEGER NOT NULL,
            has_price INTEGER NOT NULL,
            source_order INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    return connection


def _json_safe_value(value):
    if value is None:
        return None

    if isinstance(value, str):
        return value

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    if hasattr(value, "item") and callable(value.item):
        try:
            value = value.item()
        except Exception:
            pass

    if hasattr(value, "isoformat") and callable(value.isoformat):
        try:
            return value.isoformat()
        except Exception:
            pass

    if isinstance(value, (bool, int, float)):
        return value

    return str(value)


def _payload_from_row(row: pd.Series, columns: list[str]) -> str:
    payload = {column: _json_safe_value(row[column]) for column in columns}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _upsert_chunk_rows(
    connection: sqlite3.Connection,
    chunk: pd.DataFrame,
    *,
    source_order: int,
    payload_columns: list[str],
) -> None:
    current = chunk.copy()
    for column in (CANONICAL_NAME_COLUMN, CANONICAL_ARTICLE_COLUMN, CANONICAL_PRICE_COLUMN):
        if column not in current.columns:
            current[column] = None

    dedupe_keys = _build_dedupe_key(current)
    has_article = current[CANONICAL_ARTICLE_COLUMN].fillna("").astype(str).str.strip().ne("")
    has_price = pd.to_numeric(current[CANONICAL_PRICE_COLUMN], errors="coerce").notna()

    records = []
    for row_number, (_, row) in enumerate(current.iterrows()):
        records.append(
            (
                str(dedupe_keys.iloc[row_number]),
                int(bool(has_article.iloc[row_number])),
                int(bool(has_price.iloc[row_number])),
                source_order,
                _payload_from_row(row, payload_columns),
            )
        )

    if not records:
        return

    connection.executemany(
        """
        INSERT INTO merged_catalog (dedupe_key, has_article, has_price, source_order, payload_json)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(dedupe_key) DO UPDATE SET
            has_article = excluded.has_article,
            has_price = excluded.has_price,
            source_order = excluded.source_order,
            payload_json = excluded.payload_json
        WHERE
            excluded.has_article > merged_catalog.has_article
            OR (
                excluded.has_article = merged_catalog.has_article
                AND excluded.has_price > merged_catalog.has_price
            )
            OR (
                excluded.has_article = merged_catalog.has_article
                AND excluded.has_price = merged_catalog.has_price
                AND excluded.source_order < merged_catalog.source_order
            )
        """,
        records,
    )
    connection.commit()


def _write_merged_catalog_from_db(
    connection: sqlite3.Connection,
    output_path: Path,
    *,
    columns: list[str],
) -> None:
    part_path = output_path.with_suffix(f"{output_path.suffix}.part")
    if part_path.exists():
        part_path.unlink()

    try:
        with part_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, delimiter=";")
            writer.writeheader()
            cursor = connection.execute("SELECT payload_json FROM merged_catalog ORDER BY dedupe_key")
            for (payload_json,) in cursor:
                payload = json.loads(payload_json)
                row = {}
                for column in columns:
                    value = payload.get(column, "")
                    row[column] = "" if value is None else value
                writer.writerow(row)
        part_path.replace(output_path)
    except Exception:
        if part_path.exists():
            part_path.unlink()
        raise


def merge_catalog_frames(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    prepared_frames: list[pd.DataFrame] = []
    for source_order, frame in enumerate(frames):
        prepared_frames.append(_prepare_merge_frame(frame, source_order))

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

    db_path = _sqlite_temp_path(output_path)
    connection = _init_merge_db(db_path)
    all_columns: list[str] = []
    seen_columns: set[str] = set()

    try:
        for source_order, source_path in enumerate(sources):
            header_df = _read_catalog_header(source_path)
            source_columns = list(header_df.columns)
            for required_column in (CANONICAL_NAME_COLUMN, CANONICAL_ARTICLE_COLUMN, CANONICAL_PRICE_COLUMN):
                if required_column not in source_columns:
                    source_columns.append(required_column)
            for column in source_columns:
                if column in seen_columns:
                    continue
                seen_columns.add(column)
                all_columns.append(column)

            for chunk in _iter_catalog_chunks(source_path, chunksize=DEFAULT_MERGE_CHUNKSIZE):
                payload_columns = list(chunk.columns)
                for required_column in (CANONICAL_NAME_COLUMN, CANONICAL_ARTICLE_COLUMN, CANONICAL_PRICE_COLUMN):
                    if required_column not in payload_columns:
                        payload_columns.append(required_column)
                _upsert_chunk_rows(
                    connection,
                    chunk,
                    source_order=source_order,
                    payload_columns=payload_columns,
                )

        _write_merged_catalog_from_db(connection, output_path, columns=all_columns)
        return output_path
    finally:
        connection.close()
        _cleanup_sqlite_sidecars(db_path)
