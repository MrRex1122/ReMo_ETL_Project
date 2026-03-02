import os
import tempfile
import unittest
from codecs import BOM_UTF8
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from snapshot_export import (
    ARTICLE_DUPLICATE_COLUMN,
    NAME_DUPLICATE_COLUMN,
    build_duplicate_report_from_csv,
    build_snapshot_export_basename,
    build_xlsx_from_csv_streaming,
    get_snapshot_xlsx_status,
    make_snapshot_bundle,
    stage_public_export,
)


class SnapshotExportTests(unittest.TestCase):
    def test_build_duplicate_report_from_csv_matches_expected_stats(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_csv = root / "catalog.csv"
            duplicate_csv = root / "duplicates.csv"
            pd.DataFrame(
                [
                    {"Наименование": "Кабель UTP cat6", "Артикул": "A-1", "Цена розничная": 10},
                    {"Наименование": "Кабель UTP cat6", "Артикул": "", "Цена розничная": 11},
                    {"Наименование": "Автомат 16A", "Артикул": "A-1", "Цена розничная": 12},
                ]
            ).to_csv(source_csv, sep=";", encoding="utf-8", index=False)

            stats, resolved_duplicate_csv = build_duplicate_report_from_csv(
                source_csv,
                duplicate_csv_path=duplicate_csv,
                chunksize=2,
            )

            self.assertEqual(stats["rows_total"], 3)
            self.assertEqual(stats["duplicates_total"], 3)
            self.assertEqual(stats["duplicates_by_article"], 2)
            self.assertEqual(stats["duplicates_by_name"], 2)
            self.assertEqual(resolved_duplicate_csv, duplicate_csv)
            out_df = pd.read_csv(duplicate_csv, sep=";", encoding="utf-8-sig")
            self.assertEqual(len(out_df), 3)
            self.assertIn(ARTICLE_DUPLICATE_COLUMN, out_df.columns)
            self.assertIn(NAME_DUPLICATE_COLUMN, out_df.columns)

    def test_stage_public_export_streams_and_adds_utf8_bom(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_csv = root / "catalog.csv"
            public_dir = root / "public"
            source_csv.write_text("Наименование;Артикул\nКабель;A-1\n", encoding="utf-8")

            public_path, public_url = stage_public_export(
                source_csv,
                "catalog_snapshot.csv",
                public_dir=public_dir,
                add_utf8_bom=True,
            )

            self.assertTrue(public_path.exists())
            self.assertEqual(public_url, "/app/static/exports/catalog_snapshot.csv")
            self.assertTrue(public_path.read_bytes().startswith(BOM_UTF8))

    def test_build_xlsx_from_csv_streaming_creates_valid_workbook(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_csv = root / "catalog.csv"
            target_xlsx = root / "catalog.xlsx"
            source_csv.write_text(
                "Наименование;Артикул;Цена розничная\nКабель UTP cat6;A-1;100\n",
                encoding="utf-8",
            )

            build_xlsx_from_csv_streaming(source_csv, target_xlsx)

            self.assertTrue(target_xlsx.exists())
            workbook = load_workbook(target_xlsx, read_only=True)
            worksheet = workbook.active
            rows = list(worksheet.iter_rows(values_only=True))
            workbook.close()
            self.assertEqual(rows[0], ("Наименование", "Артикул", "Цена розничная"))
            self.assertEqual(rows[1], ("Кабель UTP cat6", "A-1", "100"))

    def test_get_snapshot_xlsx_status_reports_stale_partial(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_csv = root / "catalog.csv"
            target_xlsx = root / "catalog.xlsx"
            part_path = Path(f"{target_xlsx}.part")
            source_csv.write_text("Наименование;Артикул\nКабель;A-1\n", encoding="utf-8")
            part_path.write_text("building", encoding="utf-8")
            stale_time = part_path.stat().st_mtime - 3600
            os.utime(part_path, (stale_time, stale_time))

            status, started_at = get_snapshot_xlsx_status(
                source_csv,
                target_xlsx,
                stale_after_seconds=10,
            )

            self.assertEqual(status, "failed_stale")
            self.assertIsNotNone(started_at)

    def test_make_snapshot_bundle_prunes_stale_exports_for_same_source(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            public_dir = root / "public"
            source_csv = root / "catalog snapshot.csv"
            source_csv.write_text("Наименование;Артикул\nКабель;A-1\n", encoding="utf-8")

            stale_files = [
                public_dir / "catalog_snapshot_old.csv",
                public_dir / "catalog_snapshot_old_duplicates.csv",
                public_dir / "catalog_snapshot_old.xlsx",
                public_dir / "catalog_snapshot_old.xlsx.part",
            ]
            public_dir.mkdir(parents=True, exist_ok=True)
            for path in stale_files:
                path.write_text("stale", encoding="utf-8")

            export_base = build_snapshot_export_basename(source_csv)
            duplicate_csv = public_dir / f"{export_base}_duplicates.csv"
            duplicate_csv.write_text("Артикул\nA-1\n", encoding="utf-8")

            bundle = make_snapshot_bundle(
                source_csv,
                {"rows_total": 1, "duplicates_total": 0, "duplicates_by_article": 0, "duplicates_by_name": 0},
                duplicate_csv,
                public_dir=public_dir,
            )

            self.assertTrue(bundle.public_csv_path.exists())
            self.assertTrue(duplicate_csv.exists())
            for path in stale_files:
                self.assertFalse(path.exists())

    def test_make_snapshot_bundle_keeps_current_xlsx_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            public_dir = root / "public"
            source_csv = root / "catalog snapshot.csv"
            source_csv.write_text("Наименование;Артикул\nКабель;A-1\n", encoding="utf-8")

            export_base = build_snapshot_export_basename(source_csv)
            current_xlsx_part = public_dir / f"{export_base}.xlsx.part"
            stale_xlsx_part = public_dir / "catalog_snapshot_old.xlsx.part"
            public_dir.mkdir(parents=True, exist_ok=True)
            current_xlsx_part.write_text("building", encoding="utf-8")
            stale_xlsx_part.write_text("stale", encoding="utf-8")

            bundle = make_snapshot_bundle(
                source_csv,
                {"rows_total": 1, "duplicates_total": 0, "duplicates_by_article": 0, "duplicates_by_name": 0},
                None,
                public_dir=public_dir,
            )

            self.assertEqual(bundle.xlsx_status, "building")
            self.assertTrue(current_xlsx_part.exists())
            self.assertFalse(stale_xlsx_part.exists())


if __name__ == "__main__":
    unittest.main()
