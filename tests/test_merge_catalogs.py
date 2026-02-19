import tempfile
import unittest
from pathlib import Path

import pandas as pd

from merge_catalogs import merge_catalogs


class MergeCatalogsTests(unittest.TestCase):
    def test_merge_catalogs_deduplicates_by_key_and_fills_missing_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "first.csv"
            second = tmp / "second.csv"

            pd.DataFrame(
                {
                    "Код ЭТМ": ["1001", "1002"],
                    "Наименование": ["Позиция A", "Позиция B"],
                    "Артикул": ["", "ART-2"],
                    "Цена розничная": [100, 200],
                }
            ).to_csv(first, sep=";", encoding="utf-8", index=False)

            pd.DataFrame(
                {
                    "Код ЭТМ": ["1001", "1003"],
                    "Наименование": ["Позиция A уточненная", "Позиция C"],
                    "Артикул": ["ART-1", "ART-3"],
                    "Цена розничная": [110, 300],
                }
            ).to_csv(second, sep=";", encoding="utf-8", index=False)

            merged = merge_catalogs([first, second], key_col="Код ЭТМ", encoding="utf-8")

            self.assertEqual(len(merged), 3)
            self.assertEqual(merged["Код ЭТМ"].nunique(), 3)

            row_1001 = merged.loc[merged["Код ЭТМ"] == "1001"].iloc[0]
            self.assertEqual(row_1001["Артикул"], "ART-1")
            self.assertIn(row_1001["Наименование"], {"Позиция A", "Позиция A уточненная"})

    def test_merge_catalogs_supports_alias_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first = tmp / "supplier.csv"

            pd.DataFrame(
                {
                    "Код ЭТМ": ["2001"],
                    "Номенклатура": ["Щит"],
                    "Код товара": ["SKU-2001"],
                    "Цена": ["1 500,50"],
                }
            ).to_csv(first, sep=";", encoding="utf-8", index=False)

            merged = merge_catalogs([first], key_col="Код ЭТМ", encoding="utf-8")

            self.assertIn("Наименование", merged.columns)
            self.assertIn("Артикул", merged.columns)
            self.assertIn("Цена розничная", merged.columns)
            self.assertEqual(merged.loc[0, "Наименование"], "Щит")
            self.assertEqual(merged.loc[0, "Артикул"], "SKU-2001")


if __name__ == "__main__":
    unittest.main()
