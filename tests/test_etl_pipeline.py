import tempfile
import unittest
from pathlib import Path

import pandas as pd

from etl_pipeline import PriceETL


class PriceETLTests(unittest.TestCase):
    def test_load_creates_output_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_csv = tmp / "input.csv"
            output_csv = tmp / "nested" / "dir" / "clean.csv"

            df = pd.DataFrame({"Артикул": ["A1"], "Цена": [100]})
            df.to_csv(input_csv, sep=";", encoding="utf-8", index=False)

            etl = PriceETL(str(input_csv), str(output_csv))
            etl.extract().transform().load()

            self.assertTrue(output_csv.exists())

    def test_transform_maps_alias_columns_to_canonical_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_csv = tmp / "input_alias.csv"
            output_csv = tmp / "clean.csv"

            source_df = pd.DataFrame(
                {
                    "Номенклатура": ["Кабель ВВГ", "Щиток", "Розетка"],
                    "Код товара": ["ART-1", None, ""],
                    "Цена": ["1 200,50", "2300", "150"],
                }
            )
            source_df.to_csv(input_csv, sep=";", encoding="utf-8", index=False)

            etl = PriceETL(str(input_csv), str(output_csv))
            clean_df = etl.run()

            self.assertIn("Наименование", clean_df.columns)
            self.assertIn("Артикул", clean_df.columns)
            self.assertIn("Цена розничная", clean_df.columns)

            self.assertEqual(clean_df.loc[0, "Наименование"], "Кабель ВВГ")
            self.assertEqual(clean_df.loc[0, "Артикул"], "ART-1")
            self.assertAlmostEqual(float(clean_df.loc[0, "Цена розничная"]), 1200.50, places=2)
            self.assertEqual(clean_df.loc[1, "Артикул"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
