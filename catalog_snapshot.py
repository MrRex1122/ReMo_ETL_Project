"""Utilities for preparing memory-safe catalog snapshot exports."""

from __future__ import annotations

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


def resolve_catalog_path_for_inspection(db_csv_value: str | None, merge_all_sources: bool = False) -> Path:
    base_path = get_catalog_csv_path(db_csv_value)
    if base_path.is_dir():
        return build_merged_catalog(base_path, base_path / "price_clean_merged.csv")

    if merge_all_sources and base_path.suffix.lower() == ".csv" and base_path.parent.exists():
        return build_merged_catalog(base_path.parent, base_path.parent / "price_clean_merged.csv")

    return base_path


def prepare_catalog_snapshot(
    db_csv_value: str | None,
    merge_all_sources: bool = False,
    *,
    public_dir: Path | None = None,
) -> CatalogSnapshotBundle:
    resolved_path = resolve_catalog_path_for_inspection(db_csv_value, merge_all_sources=merge_all_sources)
    export_dir = get_public_export_dir(public_dir)
    export_base = build_snapshot_export_basename(resolved_path)
    duplicate_csv_path = export_dir / f"{export_base}_duplicates.csv"
    duplicate_stats, duplicate_path = build_duplicate_report_from_csv(
        resolved_path,
        duplicate_csv_path=duplicate_csv_path,
    )
    return make_snapshot_bundle(
        resolved_path,
        duplicate_stats,
        duplicate_path,
        public_dir=export_dir,
    )
