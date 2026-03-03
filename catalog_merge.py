"""Helpers for building a single merged catalog CSV from multiple supplier catalogs."""

from __future__ import annotations

from contextlib import contextmanager
import csv
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from typing import Iterable, Iterator, Literal
import uuid

import pandas as pd

logger = logging.getLogger(__name__)

CANONICAL_NAME_COLUMN = "Наименование"
CANONICAL_ARTICLE_COLUMN = "Артикул"
CANONICAL_PRICE_COLUMN = "Цена розничная"
MERGED_CATALOG_FILENAME = "price_clean_merged.csv"
DEFAULT_MERGE_CHUNKSIZE = 50000
DEFAULT_MERGE_LOCK_TIMEOUT_SECONDS = 10 * 60
DEFAULT_MERGE_LOCK_STALE_SECONDS = 30 * 60


@dataclass
class CatalogReadiness:
    source_path: Path
    clean_dir: Path | None
    merged_path: Path
    state: Literal["ready", "missing", "stale", "invalid"]
    reason: str | None
    clean_sources_count: int
    latest_clean_mtime: float | None
    merged_mtime: float | None


def _normalize_text(text: str) -> str:
    lowered = str(text or "").lower().replace("ё", "е")
    lowered = re.sub(r"[^a-zа-я0-9]+", " ", lowered)
    return " ".join(lowered.split())


def _sanitize_temp_stem(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    sanitized = sanitized.strip("._")
    return sanitized or "catalog_merge"


def get_merged_catalog_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / MERGED_CATALOG_FILENAME


def _infer_clean_dir(source_path: Path) -> Path | None:
    source_path = Path(source_path)
    if source_path.is_dir():
        return source_path
    if source_path.name == MERGED_CATALOG_FILENAME and source_path.parent.exists():
        return source_path.parent
    if source_path.parent.exists():
        sibling_clean_files = [
            path for path in source_path.parent.glob("*_clean.csv")
            if path.is_file() and path.name != MERGED_CATALOG_FILENAME
        ]
        if sibling_clean_files:
            return source_path.parent
    return None


def get_catalog_readiness(source_path: str | Path) -> CatalogReadiness:
    source_path = Path(str(source_path))
    clean_dir = _infer_clean_dir(source_path)
    merged_path = get_merged_catalog_path(clean_dir) if clean_dir is not None else source_path

    if clean_dir is None:
        if merged_path.exists():
            readiness = CatalogReadiness(
                source_path=source_path,
                clean_dir=None,
                merged_path=merged_path,
                state="ready",
                reason=None,
                clean_sources_count=0,
                latest_clean_mtime=None,
                merged_mtime=merged_path.stat().st_mtime,
            )
        else:
            readiness = CatalogReadiness(
                source_path=source_path,
                clean_dir=None,
                merged_path=merged_path,
                state="missing",
                reason=f"Не найден файл БД: {merged_path}",
                clean_sources_count=0,
                latest_clean_mtime=None,
                merged_mtime=None,
            )
        logger.info(
            "ℹ️ Catalog readiness: source=%s state=%s clean_sources=%s merged=%s",
            readiness.source_path,
            readiness.state,
            readiness.clean_sources_count,
            readiness.merged_path,
        )
        return readiness

    clean_sources = _catalog_sources(clean_dir, merged_path)
    clean_sources_count = len(clean_sources)
    if not clean_sources:
        readiness = CatalogReadiness(
            source_path=source_path,
            clean_dir=clean_dir,
            merged_path=merged_path,
            state="invalid",
            reason=f"В папке {clean_dir} нет файлов *_clean.csv",
            clean_sources_count=0,
            latest_clean_mtime=None,
            merged_mtime=merged_path.stat().st_mtime if merged_path.exists() else None,
        )
        logger.info(
            "ℹ️ Catalog readiness: source=%s state=%s clean_sources=%s merged=%s reason=%s",
            readiness.source_path,
            readiness.state,
            readiness.clean_sources_count,
            readiness.merged_path,
            readiness.reason,
        )
        return readiness

    latest_clean_mtime = max(path.stat().st_mtime for path in clean_sources)
    if not merged_path.exists():
        state = "missing"
        reason = f"Итоговая БД не собрана: отсутствует {merged_path.name}"
        merged_mtime = None
    else:
        merged_mtime = merged_path.stat().st_mtime
        if merged_mtime < latest_clean_mtime:
            state = "stale"
            reason = (
                "Итоговая БД устарела: есть более новые *_clean.csv, "
                "требуется обновить БД"
            )
        else:
            state = "ready"
            reason = None

    readiness = CatalogReadiness(
        source_path=source_path,
        clean_dir=clean_dir,
        merged_path=merged_path,
        state=state,
        reason=reason,
        clean_sources_count=clean_sources_count,
        latest_clean_mtime=latest_clean_mtime,
        merged_mtime=merged_mtime,
    )
    logger.info(
        "ℹ️ Catalog readiness: source=%s state=%s clean_sources=%s merged=%s",
        readiness.source_path,
        readiness.state,
        readiness.clean_sources_count,
        readiness.merged_path,
    )
    return readiness


def refresh_merged_catalog(clean_dir: Path) -> Path:
    clean_dir = Path(clean_dir)
    logger.info("🔄 Merged DB rebuild requested: clean_dir=%s", clean_dir)
    readiness = get_catalog_readiness(clean_dir)
    if readiness.clean_dir is None or readiness.clean_sources_count == 0:
        message = readiness.reason or f"В папке {clean_dir} нет файлов *_clean.csv"
        logger.error("❌ Merged DB rebuild failed: %s", message)
        raise FileNotFoundError(message)

    logger.info(
        "🔄 Merged DB rebuild start: clean_dir=%s output=%s clean_sources=%s",
        clean_dir,
        readiness.merged_path,
        readiness.clean_sources_count,
    )
    try:
        merged_path = build_merged_catalog(clean_dir, readiness.merged_path)
    except Exception:
        logger.exception("❌ Merged DB rebuild failed: clean_dir=%s", clean_dir)
        raise

    logger.info("✅ Merged DB rebuild complete: %s", merged_path)
    return merged_path


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
    safe_stem = _sanitize_temp_stem(output_path.stem)
    return Path(tempfile.gettempdir()) / f"{safe_stem}_{os.getpid()}_{uuid.uuid4().hex}.merge.sqlite3"


def _output_part_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.name}.{os.getpid()}.{uuid.uuid4().hex}.part")


@contextmanager
def _merge_build_lock(
    output_path: Path,
    *,
    timeout_seconds: int = DEFAULT_MERGE_LOCK_TIMEOUT_SECONDS,
    stale_after_seconds: int = DEFAULT_MERGE_LOCK_STALE_SECONDS,
):
    lock_path = output_path.with_suffix(f"{output_path.suffix}.lock")
    started_at = time.time()

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"{os.getpid()}\n{time.time()}\n")
            logger.info("🔒 Merge lock acquired: %s", lock_path)
            break
        except FileExistsError:
            try:
                age_seconds = max(0.0, time.time() - lock_path.stat().st_mtime)
            except FileNotFoundError:
                continue

            if age_seconds > stale_after_seconds:
                logger.warning(
                    "🧹 Removing stale merge lock: %s age_seconds=%.1f",
                    lock_path,
                    age_seconds,
                )
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue

            waited_seconds = max(0.0, time.time() - started_at)
            if waited_seconds > timeout_seconds:
                raise TimeoutError(
                    f"Не удалось дождаться merge lock {lock_path} за {timeout_seconds} секунд"
                )

            logger.info(
                "⏳ Waiting for merge lock: %s waited_seconds=%.1f",
                lock_path,
                waited_seconds,
            )
            time.sleep(1.0)

    try:
        yield
    finally:
        try:
            lock_path.unlink()
            logger.info("🔓 Merge lock released: %s", lock_path)
        except FileNotFoundError:
            pass


def _cleanup_sqlite_sidecars(db_path: Path) -> None:
    for candidate in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if candidate.exists():
            candidate.unlink()


def _init_merge_db(db_path: Path) -> sqlite3.Connection:
    if db_path.exists():
        db_path.unlink()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("🗄️ Initializing merge temp DB: %s", db_path)
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
    part_path = _output_part_path(output_path)
    if part_path.exists():
        part_path.unlink()

    logger.info("📝 Writing merged catalog from temp DB: output=%s part=%s", output_path, part_path)
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
    logger.info("🔗 Merge catalog start: clean_dir=%s output=%s", clean_dir, output_path)

    sources = _catalog_sources(clean_dir, output_path)
    if not sources:
        raise FileNotFoundError(f"В папке {clean_dir} не найдено файлов *_clean.csv")
    logger.info("🔗 Merge catalog sources: count=%s files=%s", len(sources), ", ".join(path.name for path in sources))

    latest_source_mtime = max(path.stat().st_mtime for path in sources)
    if output_path.exists() and output_path.stat().st_mtime >= latest_source_mtime:
        logger.info("♻️ Reusing up-to-date merged catalog: %s", output_path)
        return output_path

    with _merge_build_lock(output_path):
        if output_path.exists() and output_path.stat().st_mtime >= latest_source_mtime:
            logger.info("♻️ Merge completed by another worker while waiting: %s", output_path)
            return output_path

        db_path = _sqlite_temp_path(output_path)
        connection: sqlite3.Connection | None = None
        all_columns: list[str] = []
        seen_columns: set[str] = set()
        total_chunks = 0
        total_rows_read = 0

        try:
            connection = _init_merge_db(db_path)
            for source_order, source_path in enumerate(sources):
                logger.info("📥 Merge source start: #%s file=%s", source_order + 1, source_path)
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

                source_chunks = 0
                source_rows = 0
                for chunk in _iter_catalog_chunks(source_path, chunksize=DEFAULT_MERGE_CHUNKSIZE):
                    source_chunks += 1
                    total_chunks += 1
                    source_rows += len(chunk)
                    total_rows_read += len(chunk)
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
                    if source_chunks == 1 or source_chunks % 10 == 0:
                        logger.info(
                            "📥 Merge source progress: file=%s chunks=%s rows=%s total_rows=%s",
                            source_path.name,
                            source_chunks,
                            source_rows,
                            total_rows_read,
                        )
                logger.info(
                    "✅ Merge source complete: file=%s chunks=%s rows=%s columns=%s",
                    source_path.name,
                    source_chunks,
                    source_rows,
                    len(source_columns),
                )

            _write_merged_catalog_from_db(connection, output_path, columns=all_columns)
            final_rows = connection.execute("SELECT COUNT(*) FROM merged_catalog").fetchone()[0]
            logger.info(
                "✅ Merge catalog complete: output=%s rows=%s columns=%s total_rows_read=%s total_chunks=%s size_bytes=%s",
                output_path,
                final_rows,
                len(all_columns),
                total_rows_read,
                total_chunks,
                output_path.stat().st_size,
            )
            return output_path
        finally:
            if connection is not None:
                connection.close()
            _cleanup_sqlite_sidecars(db_path)
