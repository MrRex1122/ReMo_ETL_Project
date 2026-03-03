"""Memory-safe helpers for catalog snapshot export artifacts."""

from __future__ import annotations

import csv
from codecs import BOM_UTF8
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import re
import shutil
import threading
import time
from urllib.parse import quote

from openpyxl import Workbook
import pandas as pd

from catalog_merge import CANONICAL_ARTICLE_COLUMN, CANONICAL_NAME_COLUMN
from config import PROJECT_ROOT

logger = logging.getLogger(__name__)

PUBLIC_STATIC_DIR = PROJECT_ROOT / "static" / "exports"
PUBLIC_STATIC_URL_PREFIX = "/app/static/exports"
COPY_BUFFER_SIZE = 4 * 1024 * 1024
DEFAULT_DUPLICATE_CHUNKSIZE = 50000
DEFAULT_XLSX_STALE_SECONDS = 30 * 60
ARTICLE_DUPLICATE_COLUMN = "Дубль по артикулу"
NAME_DUPLICATE_COLUMN = "Дубль по наименованию"


@dataclass
class CatalogSnapshotBundle:
    resolved_csv_path: Path
    resolved_csv_size_bytes: int
    public_csv_path: Path
    public_csv_url: str
    duplicate_stats: dict[str, int]
    duplicate_csv_path: Path | None
    public_duplicate_csv_url: str | None
    xlsx_path: Path | None
    public_xlsx_url: str | None
    xlsx_status: str
    xlsx_started_at: str | None


def _timestamp_to_iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _normalize_key(value: str) -> str:
    lowered = str(value or "").lower().replace("ё", "е")
    lowered = re.sub(r"[^a-zа-я0-9]+", " ", lowered)
    return " ".join(lowered.split())


def _sanitize_export_stem(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    sanitized = sanitized.strip("._")
    return sanitized or "catalog_snapshot"


def build_snapshot_export_basename(source_path: Path) -> str:
    stat = source_path.stat()
    return f"{_sanitize_export_stem(source_path.stem)}_{stat.st_size}_{stat.st_mtime_ns}"


def _is_snapshot_artifact(path: Path, source_stem: str) -> bool:
    stem_prefix = f"{_sanitize_export_stem(source_stem)}_"
    if not path.name.startswith(stem_prefix):
        return False
    return any(
        path.name.endswith(suffix)
        for suffix in (".csv", ".csv.part", ".xlsx", ".xlsx.part")
    )


def prune_stale_snapshot_exports(
    source_path: Path,
    keep_paths: set[Path],
    *,
    public_dir: Path | None = None,
) -> list[Path]:
    source_path = Path(source_path)
    export_dir = get_public_export_dir(public_dir)
    normalized_keep = {Path(path) for path in keep_paths}
    removed_paths: list[Path] = []

    for candidate in export_dir.iterdir():
        if not candidate.is_file():
            continue
        if not _is_snapshot_artifact(candidate, source_path.stem):
            continue
        if candidate in normalized_keep:
            continue
        candidate.unlink()
        removed_paths.append(candidate)

    if removed_paths:
        logger.info(
            "🧹 Snapshot export cleanup removed %s stale file(s): %s",
            len(removed_paths),
            ", ".join(str(path.name) for path in removed_paths),
        )
    else:
        logger.info("🧹 Snapshot export cleanup found no stale files in %s", export_dir)

    return removed_paths


def _xlsx_part_path(target_xlsx: Path) -> Path:
    return target_xlsx.with_suffix(f"{target_xlsx.suffix}.part")


def get_public_export_dir(public_dir: Path | None = None) -> Path:
    target_dir = Path(public_dir) if public_dir is not None else PUBLIC_STATIC_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    logger.info("📁 Snapshot public export dir ready: %s", target_dir)
    return target_dir


def build_public_export_url(public_path: Path) -> str:
    return f"{PUBLIC_STATIC_URL_PREFIX}/{quote(public_path.name)}"


def stage_public_export(
    source_path: Path,
    public_name: str,
    *,
    public_dir: Path | None = None,
    add_utf8_bom: bool = False,
) -> tuple[Path, str]:
    source_path = Path(source_path)
    export_dir = get_public_export_dir(public_dir)
    final_path = export_dir / public_name
    part_path = final_path.with_suffix(f"{final_path.suffix}.part")

    if final_path.exists():
        logger.info("♻️ Reusing existing public export: %s -> %s", source_path, final_path)
        return final_path, build_public_export_url(final_path)

    if part_path.exists():
        part_path.unlink()

    logger.info(
        "📤 Staging public export: source=%s target=%s add_utf8_bom=%s",
        source_path,
        final_path,
        add_utf8_bom,
    )
    try:
        with source_path.open("rb") as src, part_path.open("wb") as dst:
            if add_utf8_bom:
                dst.write(BOM_UTF8)
            shutil.copyfileobj(src, dst, length=COPY_BUFFER_SIZE)
        part_path.replace(final_path)
    except Exception:
        if part_path.exists():
            part_path.unlink()
        raise

    logger.info(
        "✅ Public export ready: %s (%s bytes) url=%s",
        final_path,
        final_path.stat().st_size,
        build_public_export_url(final_path),
    )

    return final_path, build_public_export_url(final_path)


def _article_key_series(chunk: pd.DataFrame) -> pd.Series:
    series = chunk.get(CANONICAL_ARTICLE_COLUMN)
    if series is None:
        series = pd.Series([""] * len(chunk), index=chunk.index)
    return series.fillna("").astype(str).str.strip().str.lower()


def _name_key_series(chunk: pd.DataFrame) -> pd.Series:
    series = chunk.get(CANONICAL_NAME_COLUMN)
    if series is None:
        series = pd.Series([""] * len(chunk), index=chunk.index)
    return series.fillna("").astype(str).map(_normalize_key)


def build_duplicate_report_from_csv(
    source_csv: Path,
    duplicate_csv_path: Path | None = None,
    *,
    chunksize: int = DEFAULT_DUPLICATE_CHUNKSIZE,
) -> tuple[dict[str, int], Path | None]:
    source_csv = Path(source_csv)
    logger.info(
        "🧮 Duplicate report start: source=%s duplicate_csv=%s chunksize=%s",
        source_csv,
        duplicate_csv_path,
        chunksize,
    )
    article_counts: Counter[str] = Counter()
    name_counts: Counter[str] = Counter()
    rows_total = 0

    read_kwargs = {
        "sep": ";",
        "encoding": "utf-8",
        "chunksize": chunksize,
        "low_memory": False,
    }

    for pass1_idx, chunk in enumerate(pd.read_csv(source_csv, **read_kwargs), start=1):
        rows_total += len(chunk)
        article_keys = _article_key_series(chunk)
        article_counts.update(article_keys[article_keys.ne("")].tolist())

        name_keys = _name_key_series(chunk)
        name_counts.update(name_keys[name_keys.ne("")].tolist())
        if pass1_idx == 1 or pass1_idx % 10 == 0:
            logger.info(
                "🧮 Duplicate report pass1 progress: chunk=%s rows_total=%s unique_articles=%s unique_names=%s",
                pass1_idx,
                rows_total,
                len(article_counts),
                len(name_counts),
            )

    duplicate_csv_path = Path(duplicate_csv_path) if duplicate_csv_path is not None else None
    duplicate_part_path = None
    if duplicate_csv_path is not None:
        duplicate_csv_path.parent.mkdir(parents=True, exist_ok=True)
        duplicate_part_path = duplicate_csv_path.with_suffix(f"{duplicate_csv_path.suffix}.part")
        if duplicate_part_path.exists():
            duplicate_part_path.unlink()

    duplicates_total = 0
    duplicates_by_article = 0
    duplicates_by_name = 0
    wrote_duplicate_header = False

    try:
        for pass2_idx, chunk in enumerate(pd.read_csv(source_csv, **read_kwargs), start=1):
            article_keys = _article_key_series(chunk)
            name_keys = _name_key_series(chunk)

            dup_by_article = article_keys.map(lambda value: bool(value) and article_counts[value] > 1)
            dup_by_name = name_keys.map(lambda value: bool(value) and name_counts[value] > 1)
            duplicate_mask = dup_by_article | dup_by_name

            duplicates_by_article += int(dup_by_article.sum())
            duplicates_by_name += int(dup_by_name.sum())
            duplicates_total += int(duplicate_mask.sum())

            if duplicate_part_path is None or not duplicate_mask.any():
                continue

            duplicate_chunk = chunk.loc[duplicate_mask].copy()
            duplicate_chunk.insert(
                0,
                ARTICLE_DUPLICATE_COLUMN,
                dup_by_article.loc[duplicate_chunk.index].map({True: "да", False: ""}),
            )
            duplicate_chunk.insert(
                1,
                NAME_DUPLICATE_COLUMN,
                dup_by_name.loc[duplicate_chunk.index].map({True: "да", False: ""}),
            )
            duplicate_chunk.to_csv(
                duplicate_part_path,
                sep=";",
                index=False,
                encoding="utf-8-sig",
                mode="w" if not wrote_duplicate_header else "a",
                header=not wrote_duplicate_header,
            )
            wrote_duplicate_header = True
            if pass2_idx == 1 or pass2_idx % 10 == 0:
                logger.info(
                    "🧮 Duplicate report pass2 progress: chunk=%s duplicates_total=%s by_article=%s by_name=%s",
                    pass2_idx,
                    duplicates_total,
                    duplicates_by_article,
                    duplicates_by_name,
                )
    except Exception:
        if duplicate_part_path is not None and duplicate_part_path.exists():
            duplicate_part_path.unlink()
        raise

    final_duplicate_path: Path | None = None
    if duplicate_part_path is not None and wrote_duplicate_header:
        duplicate_part_path.replace(duplicate_csv_path)
        final_duplicate_path = duplicate_csv_path
    elif duplicate_part_path is not None and duplicate_part_path.exists():
        duplicate_part_path.unlink()

    if final_duplicate_path is None and duplicate_csv_path is not None and duplicate_csv_path.exists():
        duplicate_csv_path.unlink()

    stats = {
        "rows_total": rows_total,
        "duplicates_total": duplicates_total,
        "duplicates_by_article": duplicates_by_article,
        "duplicates_by_name": duplicates_by_name,
    }
    logger.info(
        "✅ Duplicate report complete: rows=%s duplicates=%s by_article=%s by_name=%s duplicate_csv=%s",
        rows_total,
        duplicates_total,
        duplicates_by_article,
        duplicates_by_name,
        final_duplicate_path,
    )
    return stats, final_duplicate_path


def build_xlsx_from_csv_streaming(source_csv: Path, target_xlsx: Path) -> None:
    source_csv = Path(source_csv)
    target_xlsx = Path(target_xlsx)
    target_xlsx.parent.mkdir(parents=True, exist_ok=True)
    part_path = _xlsx_part_path(target_xlsx)
    logger.info("📗 XLSX build start: source=%s target=%s", source_csv, target_xlsx)

    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet(title="Catalog")

    try:
        with source_csv.open("r", encoding="utf-8-sig", newline="") as src:
            reader = csv.reader(src, delimiter=";")
            for row_number, row in enumerate(reader, start=1):
                worksheet.append(row)
                if row_number == 1 or row_number % 50000 == 0:
                    logger.info("📗 XLSX build progress: rows_written=%s target=%s", row_number, target_xlsx)
        workbook.save(part_path)
        part_path.replace(target_xlsx)
        logger.info("✅ XLSX build complete: %s (%s bytes)", target_xlsx, target_xlsx.stat().st_size)
    finally:
        workbook.close()


def get_snapshot_xlsx_status(
    source_csv: Path,
    xlsx_path: Path | None,
    *,
    stale_after_seconds: int = DEFAULT_XLSX_STALE_SECONDS,
) -> tuple[str, str | None]:
    if xlsx_path is None:
        return "idle", None

    source_csv = Path(source_csv)
    xlsx_path = Path(xlsx_path)
    part_path = _xlsx_part_path(xlsx_path)

    if xlsx_path.exists() and xlsx_path.stat().st_mtime_ns >= source_csv.stat().st_mtime_ns:
        return "ready", _timestamp_to_iso(xlsx_path.stat().st_mtime)

    if part_path.exists():
        started_at = _timestamp_to_iso(part_path.stat().st_mtime)
        age_seconds = max(0.0, time.time() - part_path.stat().st_mtime)
        if age_seconds > stale_after_seconds:
            return "failed_stale", started_at
        return "building", started_at

    return "idle", None


def _build_snapshot_xlsx_worker(source_csv: Path, xlsx_path: Path) -> None:
    try:
        logger.info("🧵 XLSX worker started: source=%s target=%s", source_csv, xlsx_path)
        build_xlsx_from_csv_streaming(source_csv, xlsx_path)
        logger.info("🧵 XLSX worker finished successfully: %s", xlsx_path)
    except Exception:
        part_path = _xlsx_part_path(xlsx_path)
        if not part_path.exists():
            part_path.parent.mkdir(parents=True, exist_ok=True)
            part_path.touch()
        logger.exception("Failed to build snapshot XLSX: %s", xlsx_path)


def start_snapshot_xlsx_build(
    source_csv: Path,
    xlsx_path: Path | None,
) -> tuple[str, str | None]:
    if xlsx_path is None:
        logger.info("ℹ️ XLSX build skipped: xlsx_path is None for source=%s", source_csv)
        return "idle", None

    source_csv = Path(source_csv)
    xlsx_path = Path(xlsx_path)
    current_status, started_at = get_snapshot_xlsx_status(source_csv, xlsx_path)
    logger.info(
        "🧪 XLSX build request: source=%s target=%s current_status=%s started_at=%s",
        source_csv,
        xlsx_path,
        current_status,
        started_at,
    )
    if current_status in {"ready", "building"}:
        return current_status, started_at

    part_path = _xlsx_part_path(xlsx_path)
    if part_path.exists():
        part_path.unlink()
    part_path.parent.mkdir(parents=True, exist_ok=True)
    part_path.touch()

    worker = threading.Thread(
        target=_build_snapshot_xlsx_worker,
        args=(source_csv, xlsx_path),
        daemon=True,
        name="catalog-snapshot-xlsx",
    )
    worker.start()
    logger.info("🧵 XLSX build thread launched: %s", worker.name)

    return get_snapshot_xlsx_status(source_csv, xlsx_path)


def make_snapshot_bundle(
    resolved_csv_path: Path,
    duplicate_stats: dict[str, int],
    duplicate_csv_path: Path | None,
    *,
    public_dir: Path | None = None,
) -> CatalogSnapshotBundle:
    resolved_csv_path = Path(resolved_csv_path)
    export_dir = get_public_export_dir(public_dir)
    export_base = build_snapshot_export_basename(resolved_csv_path)
    logger.info(
        "📦 Building snapshot bundle: resolved_csv=%s export_dir=%s export_base=%s",
        resolved_csv_path,
        export_dir,
        export_base,
    )

    public_csv_path, public_csv_url = stage_public_export(
        resolved_csv_path,
        f"{export_base}.csv",
        public_dir=export_dir,
        add_utf8_bom=True,
    )

    xlsx_path = export_dir / f"{export_base}.xlsx"
    xlsx_status, xlsx_started_at = get_snapshot_xlsx_status(resolved_csv_path, xlsx_path)
    public_xlsx_url = build_public_export_url(xlsx_path) if xlsx_status == "ready" else None
    public_duplicate_csv_url = (
        build_public_export_url(duplicate_csv_path) if duplicate_csv_path is not None else None
    )
    keep_paths = {public_csv_path}
    if duplicate_csv_path is not None:
        keep_paths.add(duplicate_csv_path)
    if xlsx_path is not None:
        keep_paths.add(xlsx_path)
        xlsx_part_path = _xlsx_part_path(xlsx_path)
        if xlsx_part_path.exists():
            keep_paths.add(xlsx_part_path)
    prune_stale_snapshot_exports(
        resolved_csv_path,
        keep_paths,
        public_dir=export_dir,
    )

    logger.info(
        "✅ Snapshot bundle ready: public_csv=%s duplicate_csv=%s xlsx=%s xlsx_status=%s",
        public_csv_path,
        duplicate_csv_path,
        xlsx_path,
        xlsx_status,
    )

    return CatalogSnapshotBundle(
        resolved_csv_path=resolved_csv_path,
        resolved_csv_size_bytes=resolved_csv_path.stat().st_size,
        public_csv_path=public_csv_path,
        public_csv_url=public_csv_url,
        duplicate_stats=duplicate_stats,
        duplicate_csv_path=duplicate_csv_path,
        public_duplicate_csv_url=public_duplicate_csv_url,
        xlsx_path=xlsx_path,
        public_xlsx_url=public_xlsx_url,
        xlsx_status=xlsx_status,
        xlsx_started_at=xlsx_started_at,
    )
