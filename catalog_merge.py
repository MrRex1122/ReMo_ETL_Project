"""Helpers for building a single merged catalog CSV from multiple supplier catalogs."""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
import csv
from dataclasses import dataclass
import hashlib
import json
import logging
import multiprocessing
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
from typing import Iterable, Literal
import uuid

import pandas as pd

logger = logging.getLogger(__name__)

CANONICAL_NAME_COLUMN = "Наименование"
CANONICAL_ARTICLE_COLUMN = "Артикул"
CANONICAL_PRICE_COLUMN = "Цена розничная"
MERGED_CATALOG_FILENAME = "price_clean_merged.csv"
DEFAULT_MERGE_DB_BATCH_SIZE = 1000
DEFAULT_MERGE_PROGRESS_ROWS = 25000
DEFAULT_MERGE_LOCK_TIMEOUT_SECONDS = 10 * 60
DEFAULT_MERGE_LOCK_STALE_SECONDS = 30 * 60
DEFAULT_SHARD_MERGE_WORKERS = 4
DEFAULT_SHARD_MERGE_SHARDS = 16
DEFAULT_SHARD_MERGE_OPEN_FILES = 8
DEFAULT_SHARD_MERGE_PHASE_TIMEOUT_SECONDS = 60 * 60
DEFAULT_SHARD_MERGE_PROGRESS_ROWS = 25000
MAX_SHARD_MERGE_SHARDS = 128
UPSERT_SQL = """
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
"""


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


@dataclass
class PartitionSourceResult:
    source_order: int
    source_path: Path
    source_columns: list[str]
    rows_processed: int
    rows_skipped: int
    shard_file_paths: list[Path]
    rss_peak_mb: float | None


@dataclass
class ShardReduceResult:
    shard_id: int
    rows_read: int
    rows_written: int
    output_csv_path: Path
    rss_peak_mb: float | None


def _configure_csv_field_limit() -> None:
    limit = 2**31 - 1
    while limit > 1024:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


_configure_csv_field_limit()


def _normalize_text(text: str) -> str:
    lowered = str(text or "").lower().replace("ё", "е")
    lowered = re.sub(r"[^a-zа-я0-9]+", " ", lowered)
    return " ".join(lowered.split())


def _normalize_article_for_merge(value: object) -> str:
    article = str(value or "").strip()
    if article.lower() in {"", "unknown", "nan", "none", "null"}:
        return ""
    return article


def _sanitize_temp_stem(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    sanitized = sanitized.strip("._")
    return sanitized or "catalog_merge"


def _read_env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return max(minimum, int(raw_value))
    except (TypeError, ValueError):
        logger.warning("Invalid integer env %s=%r, using default=%s", name, raw_value, default)
        return default


def _current_rss_mb() -> float | None:
    status_path = Path("/proc/self/status")
    if not status_path.exists():
        return None
    try:
        for line in status_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]) / 1024.0
    except OSError:
        return None
    return None


def _enforce_rss_budget(limit_mb: int | None, *, context: str) -> None:
    if not limit_mb or limit_mb <= 0:
        return
    rss_mb = _current_rss_mb()
    if rss_mb is not None and rss_mb > limit_mb:
        raise MemoryError(
            f"Merge memory budget exceeded during {context}: rss_mb={rss_mb:.1f} limit_mb={limit_mb}"
        )


def _enforce_merge_memory_budget(*, context: str) -> None:
    _enforce_rss_budget(_read_env_int("REMO_MERGE_MAX_RSS_MB", 0, minimum=0), context=context)


def _touch_lock_file(lock_path: Path | None) -> None:
    if lock_path is None:
        return
    try:
        os.utime(lock_path, None)
    except FileNotFoundError:
        pass


def _read_lock_pid(lock_path: Path) -> int | None:
    try:
        with lock_path.open("r", encoding="utf-8") as handle:
            raw_value = handle.readline().strip()
    except OSError:
        return None
    if not raw_value:
        return None
    try:
        return int(raw_value)
    except ValueError:
        return None


def _is_process_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def get_merged_catalog_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / MERGED_CATALOG_FILENAME


def _infer_clean_dir(source_path: Path) -> Path | None:
    source_path = Path(source_path)
    if source_path.is_dir():
        return source_path
    if source_path.name == MERGED_CATALOG_FILENAME and source_path.parent.exists():
        return source_path.parent
    if source_path.parent.exists() and any(source_path.parent.glob("*_clean.csv")):
        return source_path.parent
    return None


def _catalog_sources(clean_dir: Path, output_path: Path) -> list[Path]:
    return sorted(
        path for path in Path(clean_dir).glob("*_clean.csv")
        if path.is_file() and path.resolve() != Path(output_path).resolve()
    )


def get_catalog_readiness(source_path: str | Path) -> CatalogReadiness:
    source_path = Path(str(source_path))
    clean_dir = _infer_clean_dir(source_path)
    merged_path = get_merged_catalog_path(clean_dir) if clean_dir is not None else source_path

    if clean_dir is None:
        state = "ready" if merged_path.exists() else "missing"
        reason = None if state == "ready" else f"Не найден файл БД: {merged_path}"
        readiness = CatalogReadiness(
            source_path=source_path,
            clean_dir=None,
            merged_path=merged_path,
            state=state,
            reason=reason,
            clean_sources_count=0,
            latest_clean_mtime=None,
            merged_mtime=merged_path.stat().st_mtime if merged_path.exists() else None,
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
            "ℹ️ Catalog readiness: source=%s state=%s clean_sources=%s merged=%s",
            readiness.source_path,
            readiness.state,
            readiness.clean_sources_count,
            readiness.merged_path,
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
            reason = "Итоговая БД устарела: есть более новые *_clean.csv, требуется обновить БД"
        else:
            state = "ready"
            reason = None

    readiness = CatalogReadiness(
        source_path=source_path,
        clean_dir=clean_dir,
        merged_path=merged_path,
        state=state,
        reason=reason,
        clean_sources_count=len(clean_sources),
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
    merged_path = build_merged_catalog(clean_dir, readiness.merged_path)
    logger.info("✅ Merged DB rebuild complete: %s", merged_path)
    return merged_path


def _build_dedupe_key(df: pd.DataFrame) -> pd.Series:
    article_key = df[CANONICAL_ARTICLE_COLUMN].fillna("").astype(str).str.strip()
    article_key = article_key.mask(article_key.str.lower().isin({"", "unknown", "nan", "none", "null"}), "")
    article_key = article_key.str.lower()
    name_key = df[CANONICAL_NAME_COLUMN].fillna("").astype(str).map(_normalize_text)
    return article_key.where(article_key != "", name_key)


def _read_catalog_columns(path: Path) -> list[str]:
    try:
        with Path(path).open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.reader(handle, delimiter=";")
            return [column for column in next(reader, []) if column]
    except OSError:
        return []


def _has_numeric_value(value) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        float(normalized)
    except ValueError:
        return False
    return True


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


def _build_upsert_record(
    row: dict[str, object],
    *,
    source_order: int,
    payload_columns: list[str],
) -> tuple[str, int, int, int, str]:
    article_value = _normalize_article_for_merge(row.get(CANONICAL_ARTICLE_COLUMN))
    name_value = str(row.get(CANONICAL_NAME_COLUMN) or "").strip()
    dedupe_key = article_value.lower() if article_value else _normalize_text(name_value)
    payload = {column: _json_safe_value(row.get(column)) for column in payload_columns}
    return (
        dedupe_key,
        int(bool(article_value)),
        int(_has_numeric_value(row.get(CANONICAL_PRICE_COLUMN))),
        source_order,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


def _sqlite_temp_path(stem: str) -> Path:
    safe_stem = _sanitize_temp_stem(stem)
    return Path(tempfile.gettempdir()) / f"{safe_stem}_{os.getpid()}_{uuid.uuid4().hex}.merge.sqlite3"


def _output_part_path(output_path: Path) -> Path:
    return Path(output_path).with_name(f"{Path(output_path).name}.{os.getpid()}.{uuid.uuid4().hex}.part")


@contextmanager
def _merge_build_lock(
    output_path: Path,
    *,
    timeout_seconds: int = DEFAULT_MERGE_LOCK_TIMEOUT_SECONDS,
    stale_after_seconds: int = DEFAULT_MERGE_LOCK_STALE_SECONDS,
):
    lock_path = Path(output_path).with_suffix(f"{Path(output_path).suffix}.lock")
    started_at = time.time()
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"{os.getpid()}\n{time.time()}\n")
            logger.info("🔒 Merge lock acquired: %s", lock_path)
            break
        except FileExistsError:
            lock_pid = _read_lock_pid(lock_path)
            if lock_pid is not None and not _is_process_alive(lock_pid):
                logger.warning("Removing orphaned merge lock: %s pid=%s", lock_path, lock_pid)
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            try:
                age_seconds = max(0.0, time.time() - lock_path.stat().st_mtime)
            except FileNotFoundError:
                continue
            if age_seconds > stale_after_seconds:
                logger.warning("🧹 Removing stale merge lock: %s age_seconds=%.1f", lock_path, age_seconds)
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            waited_seconds = max(0.0, time.time() - started_at)
            if waited_seconds > timeout_seconds:
                raise TimeoutError(f"Не удалось дождаться merge lock {lock_path} за {timeout_seconds} секунд")
            logger.info("⏳ Waiting for merge lock: %s waited_seconds=%.1f", lock_path, waited_seconds)
            time.sleep(1.0)
    try:
        yield lock_path
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
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA cache_size=-32768")
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


def _upsert_records_batch(
    connection: sqlite3.Connection,
    records: list[tuple[str, int, int, int, str]],
) -> None:
    if records:
        connection.executemany(UPSERT_SQL, records)
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
    try:
        with part_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, delimiter=";")
            writer.writeheader()
            for payload_json, in connection.execute("SELECT payload_json FROM merged_catalog ORDER BY dedupe_key"):
                payload = json.loads(payload_json)
                writer.writerow(
                    {
                        column: "" if payload.get(column) is None else payload.get(column, "")
                        for column in columns
                    }
                )
        part_path.replace(output_path)
    except Exception:
        if part_path.exists():
            part_path.unlink()
        raise


def merge_catalog_frames(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    prepared_frames: list[pd.DataFrame] = []
    for source_order, frame in enumerate(frames):
        current = frame.copy()
        for column in (CANONICAL_NAME_COLUMN, CANONICAL_ARTICLE_COLUMN, CANONICAL_PRICE_COLUMN):
            if column not in current.columns:
                current[column] = None
        current["__source_order"] = source_order
        current["__has_article"] = ~(
            current[CANONICAL_ARTICLE_COLUMN]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
            .isin({"", "unknown", "nan", "none", "null"})
        )
        current["__has_price"] = pd.to_numeric(current[CANONICAL_PRICE_COLUMN], errors="coerce").notna()
        current["__dedupe_key"] = _build_dedupe_key(current)
        prepared_frames.append(current)
    if not prepared_frames:
        raise ValueError("Нет входных фреймов для объединения")
    merged = pd.concat(prepared_frames, ignore_index=True)
    merged = merged.sort_values(
        by=["__dedupe_key", "__has_article", "__has_price", "__source_order"],
        ascending=[True, False, False, True],
    )
    return merged.drop_duplicates(subset=["__dedupe_key"], keep="first").drop(
        columns=["__source_order", "__has_article", "__has_price", "__dedupe_key"]
    )


def _stream_source_into_db(
    connection: sqlite3.Connection,
    *,
    source_path: Path,
    source_order: int,
    source_columns: list[str],
    batch_size: int,
    progress_rows: int,
    lock_path: Path | None,
    rss_limit_mb: int | None,
) -> tuple[int, int, int]:
    rows = 0
    batches = 0
    skipped = 0
    next_progress = progress_rows
    pending: list[tuple[str, int, int, int, str]] = []

    with source_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if reader.fieldnames is None:
            logger.warning("⚠️ Empty merge source header: %s", source_path)
            return 0, 0, 0
        for line_number, raw_row in enumerate(reader, start=2):
            if raw_row is None:
                continue
            extra_values = raw_row.pop(None, None)
            if extra_values and any(str(value).strip() for value in extra_values):
                skipped += 1
                if skipped <= 3:
                    logger.warning(
                        "⚠️ Skipping malformed merge row: file=%s line=%s extra_fields=%s",
                        source_path,
                        line_number,
                        len(extra_values),
                    )
                continue
            row = dict(raw_row)
            for column in source_columns:
                row.setdefault(column, "")
            rows += 1
            pending.append(_build_upsert_record(row, source_order=source_order, payload_columns=source_columns))
            if len(pending) >= batch_size:
                _upsert_records_batch(connection, pending)
                pending.clear()
                batches += 1
                _touch_lock_file(lock_path)
                _enforce_rss_budget(rss_limit_mb, context=f"merge source {source_path.name}")
                if rows >= next_progress:
                    rss_value = _current_rss_mb()
                    logger.info(
                        "📥 Merge source progress: file=%s rows=%s batches=%s rss_mb=%s",
                        source_path.name,
                        rows,
                        batches,
                        f"{rss_value:.1f}" if rss_value is not None else "n/a",
                    )
                    next_progress += progress_rows

    if pending:
        _upsert_records_batch(connection, pending)
        batches += 1
        _touch_lock_file(lock_path)
        _enforce_rss_budget(rss_limit_mb, context=f"merge source {source_path.name} tail")
    return rows, batches, skipped


def _build_merged_catalog_streaming(clean_dir: Path, output_path: Path) -> Path:
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

    batch_size = _read_env_int("REMO_MERGE_DB_BATCH_SIZE", DEFAULT_MERGE_DB_BATCH_SIZE)
    progress_rows = _read_env_int("REMO_MERGE_PROGRESS_ROWS", DEFAULT_MERGE_PROGRESS_ROWS)
    logger.info(
        "🧠 Merge config: batch_size=%s progress_rows=%s memory_limit_mb=%s",
        batch_size,
        progress_rows,
        os.getenv("REMO_MERGE_MAX_RSS_MB", "disabled"),
    )

    with _merge_build_lock(output_path) as lock_path:
        if output_path.exists() and output_path.stat().st_mtime >= latest_source_mtime:
            logger.info("♻️ Merge completed by another worker while waiting: %s", output_path)
            return output_path
        db_path = _sqlite_temp_path(output_path.stem)
        connection: sqlite3.Connection | None = None
        all_columns: list[str] = []
        seen_columns: set[str] = set()
        total_rows = 0
        total_batches = 0
        try:
            connection = _init_merge_db(db_path)
            for source_order, source_path in enumerate(sources):
                logger.info("📥 Merge source start: #%s file=%s", source_order + 1, source_path)
                source_columns = _read_catalog_columns(source_path)
                for required in (CANONICAL_NAME_COLUMN, CANONICAL_ARTICLE_COLUMN, CANONICAL_PRICE_COLUMN):
                    if required not in source_columns:
                        source_columns.append(required)
                for column in source_columns:
                    if column not in seen_columns:
                        seen_columns.add(column)
                        all_columns.append(column)
                rows, batches, skipped = _stream_source_into_db(
                    connection,
                    source_path=source_path,
                    source_order=source_order,
                    source_columns=source_columns,
                    batch_size=batch_size,
                    progress_rows=progress_rows,
                    lock_path=lock_path,
                    rss_limit_mb=None,
                )
                total_rows += rows
                total_batches += batches
                rss_value = _current_rss_mb()
                logger.info(
                    "✅ Merge source complete: file=%s rows=%s columns=%s batches=%s skipped_rows=%s rss_mb=%s",
                    source_path.name,
                    rows,
                    len(source_columns),
                    batches,
                    skipped,
                    f"{rss_value:.1f}" if rss_value is not None else "n/a",
                )
            _touch_lock_file(lock_path)
            _enforce_merge_memory_budget(context="final write")
            _write_merged_catalog_from_db(connection, output_path, columns=all_columns)
            final_rows = int(connection.execute("SELECT COUNT(*) FROM merged_catalog").fetchone()[0])
            rss_value = _current_rss_mb()
            logger.info(
                "✅ Merge catalog complete: mode=streaming output=%s rows=%s columns=%s total_rows_read=%s total_batches=%s size_bytes=%s rss_mb=%s",
                output_path,
                final_rows,
                len(all_columns),
                total_rows,
                total_batches,
                output_path.stat().st_size,
                f"{rss_value:.1f}" if rss_value is not None else "n/a",
            )
            return output_path
        finally:
            if connection is not None:
                connection.close()
            _cleanup_sqlite_sidecars(db_path)


def _select_merge_mode() -> Literal["streaming", "sharded"]:
    raw_value = str(os.getenv("REMO_MERGE_MODE", "sharded")).strip().lower()
    mode = raw_value if raw_value in {"streaming", "sharded"} else "streaming"
    if mode != raw_value:
        logger.warning("Invalid merge mode %r, using streaming", raw_value)
    logger.info("🧠 Merge mode selected: %s", mode)
    return mode  # type: ignore[return-value]


def _resolve_sharded_parallelism() -> tuple[int, int]:
    workers = _read_env_int("REMO_SHARD_MERGE_WORKERS", DEFAULT_SHARD_MERGE_WORKERS)
    default_shards = max(DEFAULT_SHARD_MERGE_SHARDS, workers * 4)
    shards = _read_env_int("REMO_SHARD_MERGE_SHARDS", default_shards)
    if shards < workers:
        shards = workers
    if shards > MAX_SHARD_MERGE_SHARDS:
        shards = MAX_SHARD_MERGE_SHARDS
    return workers, shards


def _resolve_sharded_worker_limit_mb(workers: int) -> int | None:
    explicit = _read_env_int("REMO_SHARD_MERGE_WORKER_MAX_RSS_MB", 0, minimum=0)
    if explicit > 0:
        return explicit
    total = _read_env_int("REMO_MERGE_MAX_RSS_MB", 0, minimum=0)
    if total <= 0:
        return None
    return max(512, (total * 3) // (4 * max(1, workers)))


def _calc_shard_id(dedupe_key: str, shard_count: int) -> int:
    digest = hashlib.md5(dedupe_key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return int(digest[:8], 16) % max(1, shard_count)


def _cleanup_sharded_workspace(work_dir: Path) -> None:
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)


def _partition_source_to_shards(
    source_path: Path,
    source_order: int,
    shard_count: int,
    work_dir: Path,
    progress_rows: int,
    worker_rss_limit_mb: int | None,
    open_file_limit: int = DEFAULT_SHARD_MERGE_OPEN_FILES,
) -> PartitionSourceResult:
    source_path = Path(source_path)
    partition_dir = Path(work_dir) / "partition"
    partition_dir.mkdir(parents=True, exist_ok=True)
    source_columns = _read_catalog_columns(source_path)
    for required in (CANONICAL_NAME_COLUMN, CANONICAL_ARTICLE_COLUMN, CANONICAL_PRICE_COLUMN):
        if required not in source_columns:
            source_columns.append(required)

    rows = 0
    skipped = 0
    next_progress = progress_rows
    shard_paths: dict[int, Path] = {}
    handles: OrderedDict[int, object] = OrderedDict()
    rss_peak = _current_rss_mb()

    def get_handle(shard_id: int):
        handle = handles.get(shard_id)
        if handle is not None:
            handles.move_to_end(shard_id)
            return handle
        if len(handles) >= max(1, open_file_limit):
            _, old_handle = handles.popitem(last=False)
            old_handle.close()
        target = partition_dir / f"source_{source_order:03d}_shard_{shard_id:03d}.jsonl"
        shard_paths[shard_id] = target
        handle = target.open("a", encoding="utf-8", newline="")
        handles[shard_id] = handle
        return handle

    try:
        with source_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            if reader.fieldnames is None:
                return PartitionSourceResult(source_order, source_path, source_columns, 0, 0, [], rss_peak)
            for line_number, raw_row in enumerate(reader, start=2):
                if raw_row is None:
                    continue
                extra_values = raw_row.pop(None, None)
                if extra_values and any(str(value).strip() for value in extra_values):
                    skipped += 1
                    if skipped <= 3:
                        logger.warning("⚠️ Skipping malformed partition row: file=%s line=%s extra_fields=%s", source_path, line_number, len(extra_values))
                    continue
                row = dict(raw_row)
                for column in source_columns:
                    row.setdefault(column, "")
                record = _build_upsert_record(row, source_order=source_order, payload_columns=source_columns)
                shard_id = _calc_shard_id(record[0], shard_count)
                shard_handle = get_handle(shard_id)
                shard_handle.write(json.dumps({"dedupe_key": record[0], "has_article": record[1], "has_price": record[2], "source_order": record[3], "payload_json": record[4]}, ensure_ascii=False, separators=(",", ":")))
                shard_handle.write("\n")
                rows += 1
                if rows >= next_progress:
                    _enforce_rss_budget(worker_rss_limit_mb, context=f"partition source {source_path.name}")
                    rss_value = _current_rss_mb()
                    if rss_value is not None:
                        rss_peak = max(rss_peak or rss_value, rss_value)
                    logger.info("📥 Partition source progress: file=%s rows=%s rss_mb=%s", source_path.name, rows, f"{rss_value:.1f}" if rss_value is not None else "n/a")
                    next_progress += progress_rows
    finally:
        for file_handle in handles.values():
            file_handle.close()

    _enforce_rss_budget(worker_rss_limit_mb, context=f"partition source {source_path.name} tail")
    logger.info("✅ Partition source complete: file=%s rows=%s skipped=%s", source_path.name, rows, skipped)
    return PartitionSourceResult(source_order, source_path, source_columns, rows, skipped, [shard_paths[key] for key in sorted(shard_paths)], rss_peak)


def _reduce_single_shard(
    shard_id: int,
    spool_paths: list[Path],
    all_columns: list[str],
    reduce_dir: Path,
    db_batch_size: int,
    progress_rows: int,
    worker_rss_limit_mb: int | None,
) -> ShardReduceResult:
    reduce_dir = Path(reduce_dir)
    reduce_dir.mkdir(parents=True, exist_ok=True)
    db_path = reduce_dir / f"shard_{shard_id:03d}.sqlite3"
    output_csv_path = reduce_dir / f"shard_{shard_id:03d}.csv"
    connection: sqlite3.Connection | None = None
    rows_read = 0
    next_progress = progress_rows
    rss_peak = _current_rss_mb()
    pending: list[tuple[str, int, int, int, str]] = []
    logger.info("🧠 Reduce shard start: shard=%s files=%s", shard_id, len(spool_paths))
    try:
        connection = _init_merge_db(db_path)
        for spool_path in sorted(Path(path) for path in spool_paths):
            with spool_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    payload = json.loads(line)
                    pending.append((str(payload["dedupe_key"]), int(payload["has_article"]), int(payload["has_price"]), int(payload["source_order"]), str(payload["payload_json"])))
                    rows_read += 1
                    if len(pending) >= db_batch_size:
                        _upsert_records_batch(connection, pending)
                        pending.clear()
                        _enforce_rss_budget(worker_rss_limit_mb, context=f"reduce shard {shard_id}")
                    if rows_read >= next_progress:
                        rss_value = _current_rss_mb()
                        if rss_value is not None:
                            rss_peak = max(rss_peak or rss_value, rss_value)
                        logger.info("📦 Reduce shard progress: shard=%s rows=%s rss_mb=%s", shard_id, rows_read, f"{rss_value:.1f}" if rss_value is not None else "n/a")
                        next_progress += progress_rows
        if pending:
            _upsert_records_batch(connection, pending)
            _enforce_rss_budget(worker_rss_limit_mb, context=f"reduce shard {shard_id} tail")
        _write_merged_catalog_from_db(connection, output_csv_path, columns=all_columns)
        rows_written = int(connection.execute("SELECT COUNT(*) FROM merged_catalog").fetchone()[0])
        logger.info("✅ Reduce shard complete: shard=%s rows_read=%s rows_written=%s", shard_id, rows_read, rows_written)
        return ShardReduceResult(shard_id, rows_read, rows_written, output_csv_path, rss_peak)
    finally:
        if connection is not None:
            connection.close()
        _cleanup_sqlite_sidecars(db_path)


def _finalize_sharded_outputs(
    *,
    output_path: Path,
    all_columns: list[str],
    reduce_results: dict[int, ShardReduceResult],
    shard_count: int,
    lock_path: Path | None,
) -> tuple[Path, int]:
    part_path = _output_part_path(output_path)
    if part_path.exists():
        part_path.unlink()
    final_rows = 0
    logger.info("🧩 Sharded merge finalize start: output=%s shards=%s", output_path, shard_count)
    try:
        with part_path.open("w", encoding="utf-8", newline="") as output_handle:
            writer = csv.writer(output_handle, delimiter=";")
            writer.writerow(all_columns)
            for shard_id in range(shard_count):
                result = reduce_results.get(shard_id)
                if result is None or not result.output_csv_path.exists():
                    continue
                with result.output_csv_path.open("r", encoding="utf-8", newline="") as shard_handle:
                    reader = csv.reader(shard_handle, delimiter=";")
                    next(reader, None)
                    for row in reader:
                        writer.writerow(row)
                        final_rows += 1
                if shard_id % 4 == 0:
                    _touch_lock_file(lock_path)
                    _enforce_merge_memory_budget(context="sharded finalize")
        part_path.replace(output_path)
    except Exception:
        if part_path.exists():
            part_path.unlink()
        raise
    logger.info("✅ Sharded merge finalize complete: output=%s rows=%s size_bytes=%s", output_path, final_rows, output_path.stat().st_size)
    return output_path, final_rows


def _collect_executor_results(futures: dict, *, phase_name: str, timeout_seconds: int, lock_path: Path | None) -> list:
    pending = set(futures)
    results = []
    started_at = time.time()
    try:
        while pending:
            if time.time() - started_at > timeout_seconds:
                raise TimeoutError(f"{phase_name} exceeded timeout of {timeout_seconds} seconds")
            done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
            _touch_lock_file(lock_path)
            _enforce_merge_memory_budget(context=f"{phase_name} parent")
            for future in done:
                results.append(future.result())
        return results
    except Exception:
        for future in pending:
            future.cancel()
        raise


def _run_partition_phase(
    *,
    sources: list[Path],
    work_dir: Path,
    shard_count: int,
    workers: int,
    progress_rows: int,
    worker_rss_limit_mb: int | None,
    phase_timeout_seconds: int,
    lock_path: Path | None,
) -> list[PartitionSourceResult]:
    logger.info("🧩 Sharded merge partition start: sources=%s workers=%s", len(sources), workers)
    if workers <= 1:
        results = []
        for source_order, source_path in enumerate(sources):
            results.append(_partition_source_to_shards(source_path, source_order, shard_count, work_dir, progress_rows, worker_rss_limit_mb))
            _touch_lock_file(lock_path)
            _enforce_merge_memory_budget(context="partition parent")
        return results
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as executor:
        futures = {
            executor.submit(_partition_source_to_shards, source_path, source_order, shard_count, work_dir, progress_rows, worker_rss_limit_mb): source_path
            for source_order, source_path in enumerate(sources)
        }
        return _collect_executor_results(futures, phase_name="partition", timeout_seconds=phase_timeout_seconds, lock_path=lock_path)


def _run_reduce_phase(
    *,
    shard_inputs: dict[int, list[Path]],
    all_columns: list[str],
    reduce_dir: Path,
    workers: int,
    batch_size: int,
    progress_rows: int,
    worker_rss_limit_mb: int | None,
    phase_timeout_seconds: int,
    lock_path: Path | None,
) -> list[ShardReduceResult]:
    logger.info("🧩 Sharded merge reduce start: shards=%s workers=%s", len(shard_inputs), workers)
    items = sorted(shard_inputs.items())
    if workers <= 1:
        results = []
        for shard_id, spool_paths in items:
            results.append(_reduce_single_shard(shard_id, spool_paths, all_columns, reduce_dir, batch_size, progress_rows, worker_rss_limit_mb))
            _touch_lock_file(lock_path)
            _enforce_merge_memory_budget(context="reduce parent")
        return results
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as executor:
        futures = {
            executor.submit(_reduce_single_shard, shard_id, spool_paths, all_columns, reduce_dir, batch_size, progress_rows, worker_rss_limit_mb): shard_id
            for shard_id, spool_paths in items
        }
        return _collect_executor_results(futures, phase_name="reduce", timeout_seconds=phase_timeout_seconds, lock_path=lock_path)


def _build_merged_catalog_sharded(clean_dir: Path, output_path: Path) -> Path:
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

    configured_workers, shard_count = _resolve_sharded_parallelism()
    partition_workers = min(configured_workers, len(sources))
    reduce_workers = min(configured_workers, shard_count)
    worker_rss_limit_mb = _resolve_sharded_worker_limit_mb(configured_workers)
    phase_timeout_seconds = _read_env_int("REMO_SHARD_MERGE_PHASE_TIMEOUT_SECONDS", DEFAULT_SHARD_MERGE_PHASE_TIMEOUT_SECONDS)
    progress_rows = _read_env_int("REMO_SHARD_MERGE_PROGRESS_ROWS", DEFAULT_SHARD_MERGE_PROGRESS_ROWS)
    batch_size = _read_env_int("REMO_MERGE_DB_BATCH_SIZE", DEFAULT_MERGE_DB_BATCH_SIZE)
    logger.info(
        "🧠 Sharded merge config: workers=%s shards=%s worker_limit_mb=%s phase_timeout_seconds=%s progress_rows=%s batch_size=%s",
        configured_workers,
        shard_count,
        worker_rss_limit_mb if worker_rss_limit_mb is not None else "disabled",
        phase_timeout_seconds,
        progress_rows,
        batch_size,
    )

    with _merge_build_lock(output_path) as lock_path:
        if output_path.exists() and output_path.stat().st_mtime >= latest_source_mtime:
            logger.info("♻️ Merge completed by another worker while waiting: %s", output_path)
            return output_path
        work_dir = Path(tempfile.gettempdir()) / f"remo_merge_{_sanitize_temp_stem(output_path.stem)}_{os.getpid()}_{uuid.uuid4().hex}"
        reduce_dir = work_dir / "reduce"
        work_dir.mkdir(parents=True, exist_ok=True)
        reduce_dir.mkdir(parents=True, exist_ok=True)
        try:
            partition_results = _run_partition_phase(
                sources=sources,
                work_dir=work_dir,
                shard_count=shard_count,
                workers=partition_workers,
                progress_rows=progress_rows,
                worker_rss_limit_mb=worker_rss_limit_mb,
                phase_timeout_seconds=phase_timeout_seconds,
                lock_path=lock_path,
            )
            all_columns: list[str] = []
            seen_columns: set[str] = set()
            shard_inputs: dict[int, list[Path]] = {}
            for result in sorted(partition_results, key=lambda item: item.source_order):
                for column in result.source_columns:
                    if column not in seen_columns:
                        seen_columns.add(column)
                        all_columns.append(column)
                for shard_file in result.shard_file_paths:
                    match = re.search(r"_shard_(\d+)\.jsonl$", shard_file.name)
                    if match:
                        shard_inputs.setdefault(int(match.group(1)), []).append(shard_file)
            reduce_results = _run_reduce_phase(
                shard_inputs=shard_inputs,
                all_columns=all_columns,
                reduce_dir=reduce_dir,
                workers=reduce_workers,
                batch_size=batch_size,
                progress_rows=progress_rows,
                worker_rss_limit_mb=worker_rss_limit_mb,
                phase_timeout_seconds=phase_timeout_seconds,
                lock_path=lock_path,
            )
            reduce_map = {result.shard_id: result for result in reduce_results}
            _, final_rows = _finalize_sharded_outputs(output_path=output_path, all_columns=all_columns, reduce_results=reduce_map, shard_count=shard_count, lock_path=lock_path)
            logger.info(
                "✅ Merge catalog complete: mode=sharded output=%s partition_sources=%s partition_rows=%s reduce_shards=%s reduced_rows=%s final_rows=%s size_bytes=%s rss_mb=%s",
                output_path,
                len(partition_results),
                sum(item.rows_processed for item in partition_results),
                len(reduce_results),
                sum(item.rows_read for item in reduce_results),
                final_rows,
                output_path.stat().st_size,
                f"{_current_rss_mb():.1f}" if _current_rss_mb() is not None else "n/a",
            )
            return output_path
        finally:
            _cleanup_sharded_workspace(work_dir)


def build_merged_catalog(clean_dir: Path, output_path: Path) -> Path:
    mode = _select_merge_mode()
    if mode == "streaming":
        return _build_merged_catalog_streaming(clean_dir, output_path)
    try:
        return _build_merged_catalog_sharded(clean_dir, output_path)
    except FileNotFoundError:
        raise
    except (BrokenProcessPool, MemoryError, OSError, RuntimeError, TimeoutError, sqlite3.OperationalError) as error:
        logger.warning("❌ Sharded merge failed: %s", error, exc_info=True)
        logger.info("↩️ Falling back to streaming merge")
        return _build_merged_catalog_streaming(clean_dir, output_path)
