import tempfile
import unittest
from pathlib import Path

import pandas as pd

from catalog_snapshot import build_duplicate_report, prepare_catalog_snapshot


class CatalogSnapshotTests(unittest.TestCase):
    def test_build_duplicate_report_marks_article_and_name_duplicates(self):
        df = pd.DataFrame(
            [
                {"Наименование": "Кабель UTP cat6", "Артикул": "A-1", "Цена розничная": 10},
                {"Наименование": "Кабель UTP cat6", "Артикул": "", "Цена розничная": 11},
                {"Наименование": "Автомат 16A", "Артикул": "A-1", "Цена розничная": 12},
            ]
        )

        stats, duplicate_df = build_duplicate_report(df)

        self.assertEqual(stats["rows_total"], 3)
        self.assertEqual(stats["duplicates_total"], 3)
        self.assertEqual(stats["duplicates_by_article"], 2)
        self.assertEqual(stats["duplicates_by_name"], 2)
        self.assertIn("Дубль по артикулу", duplicate_df.columns)
        self.assertIn("Дубль по наименованию", duplicate_df.columns)

    def test_prepare_catalog_snapshot_merges_directory_and_returns_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель UTP cat6;A-1;100\n",
                encoding="utf-8",
            )
            (root / "price17_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель UTP cat6;;110\n",
                encoding="utf-8",
            )

            snapshot_df, payload, resolved_path = prepare_catalog_snapshot(str(root))

            self.assertTrue(resolved_path.name.endswith("price_clean_merged.csv"))
            self.assertTrue(resolved_path.exists())
            self.assertEqual(len(snapshot_df), 2)
            self.assertIn("stats", payload)


if __name__ == "__main__":
    unittest.main()
