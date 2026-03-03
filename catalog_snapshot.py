"""Utilities for preparing memory-safe catalog snapshot exports."""

from __future__ import annotations

import logging
from pathlib import Path

from catalog_merge import get_catalog_readiness, get_merged_catalog_path
from config import get_catalog_csv_path
from snapshot_export import (
    CatalogSnapshotBundle,
    build_public_export_url,
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
        readiness = get_catalog_readiness(base_path)
        if readiness.state == "ready":
            logger.info("📦 Snapshot source resolved from clean dir: %s", readiness.merged_path)
            return readiness.merged_path
        if readiness.state == "missing":
            raise FileNotFoundError(readiness.reason or f"Не найден merged-файл: {readiness.merged_path}")
        raise RuntimeError(readiness.reason or f"БД не готова: {readiness.state}")

    if merge_all_sources and base_path.suffix.lower() == ".csv" and base_path.parent.exists():
        merged_path = get_merged_catalog_path(base_path.parent)
        readiness = get_catalog_readiness(merged_path)
        if readiness.state == "ready":
            logger.info("📦 Snapshot source resolved via prepared merged sibling dir: %s", readiness.merged_path)
            return readiness.merged_path
        if readiness.state == "missing":
            raise FileNotFoundError(readiness.reason or f"Не найден merged-файл: {merged_path}")
        raise RuntimeError(readiness.reason or f"БД не готова: {readiness.state}")

    if not base_path.exists():
        raise FileNotFoundError(f"Не найден файл БД: {base_path}")
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
    logger.info(
        "🧾 Snapshot paths prepared: resolved_csv=%s export_dir=%s",
        resolved_path,
        export_dir,
    )
    bundle = make_snapshot_bundle(
        resolved_path,
        {},
        None,
        public_dir=export_dir,
    )
    logger.info(
        "✅ Snapshot preparation complete: csv=%s size_bytes=%s duplicate_report=%s xlsx_status=%s",
        bundle.public_csv_path,
        bundle.resolved_csv_size_bytes,
        "not_requested",
        bundle.xlsx_status,
    )
    return bundle


def prepare_catalog_duplicate_report(
    bundle: CatalogSnapshotBundle,
    public_dir: Path | None = None,
) -> CatalogSnapshotBundle:
    logger.info("🧮 Duplicate report start for prepared bundle: source=%s", bundle.resolved_csv_path)
    export_dir = get_public_export_dir(public_dir or bundle.public_csv_path.parent)
    export_base = build_snapshot_export_basename(bundle.resolved_csv_path)
    duplicate_csv_path = export_dir / f"{export_base}_duplicates.csv"
    duplicate_stats, duplicate_path = build_duplicate_report_from_csv(
        bundle.resolved_csv_path,
        duplicate_csv_path=duplicate_csv_path,
    )
    bundle.duplicate_stats = duplicate_stats
    bundle.duplicate_csv_path = duplicate_path
    bundle.public_duplicate_csv_url = (
        build_public_export_url(duplicate_path) if duplicate_path is not None else None
    )
    logger.info(
        "✅ Duplicate report complete for prepared bundle: rows=%s duplicates=%s duplicate_csv=%s",
        duplicate_stats.get("rows_total", 0),
        duplicate_stats.get("duplicates_total", 0),
        duplicate_path,
    )
    return bundle
