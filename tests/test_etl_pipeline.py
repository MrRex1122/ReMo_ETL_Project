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

    def test_run_chunked_keeps_stable_csv_schema_when_chunk_has_empty_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_csv = tmp / "input_chunked.csv"
            output_csv = tmp / "clean_chunked.csv"

            source_df = pd.DataFrame(
                {
                    "Номенклатура": ["A", "B", "C", "D"],
                    "Код товара": ["A1", "B1", "C1", "D1"],
                    "Цена": ["100", "200", "300", "400"],
                    # 1-й чанк полностью пустой по этой колонке,
                    # 2-й чанк содержит значения.
                    "ДопПоле": [None, None, "x", "y"],
                }
            )
            source_df.to_csv(input_csv, sep=";", encoding="utf-8", index=False)

            etl = PriceETL(str(input_csv), str(output_csv))
            etl.run_chunked(chunksize=2)

            out_df = pd.read_csv(output_csv, sep=";", encoding="utf-8")
            self.assertIn("ДопПоле", out_df.columns)
            self.assertEqual(len(out_df), 4)

    def test_run_chunked_overwrites_previous_output_instead_of_appending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            first_input_csv = tmp / "input_first.csv"
            second_input_csv = tmp / "input_second.csv"
            output_csv = tmp / "clean_chunked.csv"

            first_df = pd.DataFrame(
                {
                    "name": ["A", "B"],
                    "sku": ["A1", "B1"],
                    "price": ["100", "200"],
                }
            )
            second_df = pd.DataFrame(
                {
                    "name": ["C"],
                    "sku": ["C1"],
                    "price": ["300"],
                }
            )

            first_df.to_csv(first_input_csv, sep=";", encoding="utf-8", index=False)
            second_df.to_csv(second_input_csv, sep=";", encoding="utf-8", index=False)

            PriceETL(str(first_input_csv), str(output_csv)).run_chunked(chunksize=1)
            PriceETL(str(second_input_csv), str(output_csv)).run_chunked(chunksize=1)

            out_df = pd.read_csv(output_csv, sep=";", encoding="utf-8")
            self.assertEqual(len(out_df), 1)
            row_text = " ".join(out_df.astype(str).iloc[0].tolist())
            self.assertIn("C1", row_text)
            self.assertNotIn("A1", row_text)
            self.assertNotIn("B1", row_text)

    def test_transform_keeps_identified_rows_with_zero_numeric_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_csv = tmp / "input_zero_values.csv"
            output_csv = tmp / "clean.csv"

            source_df = pd.DataFrame(
                [
                    {"Наименование": "Кабель UTP", "Артикул": "A-1", "Цена розничная": 0},
                    {"Наименование": "", "Артикул": "", "Цена розничная": 0},
                ]
            )
            source_df.to_csv(input_csv, sep=";", encoding="utf-8", index=False)

            out_df = PriceETL(str(input_csv), str(output_csv)).run()

            self.assertEqual(len(out_df), 1)
            self.assertEqual(out_df.iloc[0]["Артикул"], "A-1")
            self.assertEqual(out_df.iloc[0]["Наименование"], "Кабель UTP")
            self.assertEqual(float(out_df.iloc[0]["Цена розничная"]), 0.0)

    def test_transform_keeps_identified_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_csv = tmp / "input_duplicates.csv"
            output_csv = tmp / "clean.csv"

            source_df = pd.DataFrame(
                [
                    {"Наименование": "Кабель UTP", "Артикул": "A-1", "Цена розничная": 100, "Комментарий": "dup"},
                    {"Наименование": "Кабель UTP", "Артикул": "A-1", "Цена розничная": 100, "Комментарий": "dup"},
                    {"Наименование": "", "Артикул": "", "Цена розничная": 50, "Комментарий": "anon"},
                    {"Наименование": "", "Артикул": "", "Цена розничная": 50, "Комментарий": "anon"},
                ]
            )
            source_df.to_csv(input_csv, sep=";", encoding="utf-8", index=False)

            out_df = PriceETL(str(input_csv), str(output_csv)).run()

            self.assertEqual(len(out_df), 3)
            self.assertEqual(int((out_df["Артикул"] == "A-1").sum()), 2)
            self.assertEqual(int((out_df["Комментарий"] == "anon").sum()), 1)


if __name__ == "__main__":
    unittest.main()
