import tempfile
import unittest
from pathlib import Path

import pandas as pd

from catalog_merge import build_merged_catalog, merge_catalog_frames


class CatalogMergeTests(unittest.TestCase):
    def test_merge_catalog_frames_dedupes_by_article_then_name(self):
        df1 = pd.DataFrame([
            {"Наименование": "Кабель ВВГ 3x1.5", "Артикул": "A-1", "Цена розничная": 100},
            {"Наименование": "Автомат 16A", "Артикул": "", "Цена розничная": 200},
        ])
        df2 = pd.DataFrame([
            {"Наименование": "Кабель ВВГ 3x1.5", "Артикул": "A-1", "Цена розничная": 110},
            {"Наименование": "Автомат 16A", "Артикул": None, "Цена розничная": 210},
        ])

        merged = merge_catalog_frames([df1, df2])

        self.assertEqual(len(merged), 2)
        cable = merged[merged["Артикул"] == "A-1"].iloc[0]
        self.assertEqual(float(cable["Цена розничная"]), 100)

    def test_build_merged_catalog_from_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель ВВГ 3x1.5;A-1;100\n",
                encoding="utf-8",
            )
            (root / "price17_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nАвтомат 16A;;200\n",
                encoding="utf-8",
            )

            output = build_merged_catalog(root, root / "price_clean_merged.csv")

            self.assertTrue(output.exists())
            merged_df = pd.read_csv(output, sep=';', encoding='utf-8')
            self.assertEqual(len(merged_df), 2)

    def test_build_merged_catalog_skips_malformed_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bad = root / "bad_clean.csv"
            bad.write_text(
                "Наименование;Артикул;Цена розничная\n"
                "Товар1;A1;100\n"
                "Товар2;A2;200;EXTRA\n"
                "Товар3;A3;300\n",
                encoding="utf-8",
            )

            output = build_merged_catalog(root, root / "price_clean_merged.csv")
            merged_df = pd.read_csv(output, sep=';', encoding='utf-8')
            self.assertEqual(len(merged_df), 2)
            self.assertSetEqual(set(merged_df["Артикул"].astype(str)), {"A1", "A3"})


if __name__ == "__main__":
    unittest.main()
