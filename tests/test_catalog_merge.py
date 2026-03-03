import tempfile
import unittest
from pathlib import Path

import pandas as pd

from catalog_merge import (
    CANONICAL_ARTICLE_COLUMN,
    CANONICAL_NAME_COLUMN,
    CANONICAL_PRICE_COLUMN,
    build_merged_catalog,
    merge_catalog_frames,
)


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
            self.assertFalse((root / "price_clean_merged.csv.lock").exists())
            self.assertEqual(list(root.glob("price_clean_merged.csv.*.part")), [])

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

    def test_build_merged_catalog_prefers_valid_price_and_keeps_union_columns(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            extra_column = "Тип изделия"
            (root / "price14_clean.csv").write_text(
                f"{CANONICAL_NAME_COLUMN};{CANONICAL_ARTICLE_COLUMN};{CANONICAL_PRICE_COLUMN}\n"
                "PDU 19;PDU-1;\n",
                encoding="utf-8",
            )
            (root / "price17_clean.csv").write_text(
                f"{CANONICAL_NAME_COLUMN};{CANONICAL_ARTICLE_COLUMN};{CANONICAL_PRICE_COLUMN};{extra_column}\n"
                "PDU 19;PDU-1;150;PDU\n",
                encoding="utf-8",
            )

            output = build_merged_catalog(root, root / "price_clean_merged.csv")
            merged_df = pd.read_csv(output, sep=";", encoding="utf-8")

            self.assertEqual(len(merged_df), 1)
            self.assertIn(extra_column, merged_df.columns)
            self.assertEqual(float(merged_df.iloc[0][CANONICAL_PRICE_COLUMN]), 150.0)
            self.assertEqual(merged_df.iloc[0][extra_column], "PDU")


if __name__ == "__main__":
    unittest.main()
