import tempfile
import unittest
from pathlib import Path

from catalog_merge import refresh_merged_catalog
from catalog_snapshot import prepare_catalog_duplicate_report, prepare_catalog_snapshot


class CatalogSnapshotTests(unittest.TestCase):
    def test_prepare_catalog_snapshot_uses_prepared_merged_directory_bundle(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            public_dir = root / "public"
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель UTP cat6;A-1;100\n",
                encoding="utf-8",
            )
            (root / "price17_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель UTP cat6;;110\n",
                encoding="utf-8",
            )
            refresh_merged_catalog(root)

            bundle = prepare_catalog_snapshot(str(root), public_dir=public_dir)

            self.assertTrue(bundle.resolved_csv_path.name.endswith("price_clean_merged.csv"))
            self.assertTrue(bundle.resolved_csv_path.exists())
            self.assertTrue(bundle.public_csv_path.exists())
            self.assertEqual(bundle.duplicate_stats, {})
            self.assertIsNone(bundle.duplicate_csv_path)
            self.assertEqual(bundle.xlsx_status, "idle")
            self.assertIsNone(bundle.public_xlsx_url)

            bundle = prepare_catalog_duplicate_report(bundle)
            self.assertEqual(bundle.duplicate_stats["rows_total"], 2)
            self.assertEqual(bundle.duplicate_stats["duplicates_total"], 2)
            self.assertIsNotNone(bundle.duplicate_csv_path)
            self.assertTrue(bundle.duplicate_csv_path.exists())

    def test_prepare_catalog_snapshot_file_path_can_use_single_or_merged_source(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            public_dir = root / "public"
            file_a = root / "price14_clean.csv"
            file_a.write_text(
                "Наименование;Артикул;Цена розничная\nКабель UTP cat6;A-1;100\n",
                encoding="utf-8",
            )
            (root / "price17_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nАвтомат 16A;B-2;110\n",
                encoding="utf-8",
            )
            refresh_merged_catalog(root)

            single_bundle = prepare_catalog_snapshot(
                str(file_a),
                merge_all_sources=False,
                public_dir=public_dir,
            )
            merged_bundle = prepare_catalog_snapshot(
                str(file_a),
                merge_all_sources=True,
                public_dir=public_dir,
            )

            self.assertEqual(single_bundle.resolved_csv_path, file_a)
            self.assertEqual(single_bundle.duplicate_stats, {})
            self.assertTrue(merged_bundle.resolved_csv_path.name.endswith("price_clean_merged.csv"))
            self.assertEqual(merged_bundle.duplicate_stats, {})

    def test_prepare_catalog_snapshot_raises_when_merged_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель;A-1;100\n",
                encoding="utf-8",
            )

            with self.assertRaises(FileNotFoundError):
                prepare_catalog_snapshot(str(root))


if __name__ == "__main__":
    unittest.main()
