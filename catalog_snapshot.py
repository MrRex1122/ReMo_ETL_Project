"""Utilities for preparing memory-safe catalog snapshot exports."""

from __future__ import annotations

import logging
from pathlib import Path

from catalog_merge import build_merged_catalog
from config import get_catalog_csv_path
from snapshot_export import (
    CatalogSnapshotBundle,
    build_snapshot_export_basename,
    build_duplicate_report_from_csv,
    get_public_export_dir,
    make_snapshot_bundle,
)

logger = logging.getLogger(__name__)


def resolve_catalog_path_for_inspection(db_csv_value: str | None, merge_all_sources: bool = False) -> Path:
    base_path = get_catalog_csv_path(db_csv_value)
    logger.info(
        "🔎 Snapshot source resolve start: explicit=%s merge_all_sources=%s resolved_base=%s",
        db_csv_value,
        merge_all_sources,
        base_path,
    )
    if base_path.is_dir():
        merged_path = build_merged_catalog(base_path, base_path / "price_clean_merged.csv")
        logger.info("📦 Snapshot source resolved from clean dir: %s", merged_path)
        return merged_path

    if merge_all_sources and base_path.suffix.lower() == ".csv" and base_path.parent.exists():
        merged_path = build_merged_catalog(base_path.parent, base_path.parent / "price_clean_merged.csv")
        logger.info("📦 Snapshot source resolved via merged sibling dir: %s", merged_path)
        return merged_path

    logger.info("📄 Snapshot source resolved as direct file: %s", base_path)
    return base_path


def prepare_catalog_snapshot(
    db_csv_value: str | None,
    merge_all_sources: bool = False,
    *,
    public_dir: Path | None = None,
) -> CatalogSnapshotBundle:
    logger.info(
        "🚚 Snapshot preparation start: db_csv_value=%s merge_all_sources=%s public_dir=%s",
        db_csv_value,
        merge_all_sources,
        public_dir,
    )
    resolved_path = resolve_catalog_path_for_inspection(db_csv_value, merge_all_sources=merge_all_sources)
    export_dir = get_public_export_dir(public_dir)
    export_base = build_snapshot_export_basename(resolved_path)
    duplicate_csv_path = export_dir / f"{export_base}_duplicates.csv"
    logger.info(
        "🧾 Snapshot paths prepared: resolved_csv=%s export_dir=%s duplicate_csv=%s",
        resolved_path,
        export_dir,
        duplicate_csv_path,
    )
    duplicate_stats, duplicate_path = build_duplicate_report_from_csv(
        resolved_path,
        duplicate_csv_path=duplicate_csv_path,
    )
    bundle = make_snapshot_bundle(
        resolved_path,
        duplicate_stats,
        duplicate_path,
        public_dir=export_dir,
    )
    logger.info(
        "✅ Snapshot preparation complete: csv=%s size_bytes=%s rows=%s duplicates=%s duplicate_csv=%s xlsx_status=%s",
        bundle.public_csv_path,
        bundle.resolved_csv_size_bytes,
        duplicate_stats.get("rows_total", 0),
        duplicate_stats.get("duplicates_total", 0),
        bundle.duplicate_csv_path,
        bundle.xlsx_status,
    )
    return bundle
