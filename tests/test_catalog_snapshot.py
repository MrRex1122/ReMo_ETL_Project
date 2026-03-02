import tempfile
import unittest
from pathlib import Path

from catalog_snapshot import prepare_catalog_snapshot


class CatalogSnapshotTests(unittest.TestCase):
    def test_prepare_catalog_snapshot_merges_directory_and_returns_bundle(self):
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

            bundle = prepare_catalog_snapshot(str(root), public_dir=public_dir)

            self.assertTrue(bundle.resolved_csv_path.name.endswith("price_clean_merged.csv"))
            self.assertTrue(bundle.resolved_csv_path.exists())
            self.assertTrue(bundle.public_csv_path.exists())
            self.assertEqual(bundle.duplicate_stats["rows_total"], 2)
            self.assertEqual(bundle.duplicate_stats["duplicates_total"], 2)
            self.assertIsNotNone(bundle.duplicate_csv_path)
            self.assertTrue(bundle.duplicate_csv_path.exists())
            self.assertEqual(bundle.xlsx_status, "idle")
            self.assertIsNone(bundle.public_xlsx_url)

    def test_prepare_catalog_snapshot_file_path_can_merge_all_sources(self):
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
            self.assertEqual(single_bundle.duplicate_stats["rows_total"], 1)
            self.assertTrue(merged_bundle.resolved_csv_path.name.endswith("price_clean_merged.csv"))
            self.assertEqual(merged_bundle.duplicate_stats["rows_total"], 2)


if __name__ == "__main__":
    unittest.main()
