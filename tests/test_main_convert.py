import tempfile
import unittest
from pathlib import Path

import pandas as pd

from main import convert_csv


class MainConvertTests(unittest.TestCase):
    def test_convert_csv_removes_trailing_unnamed_column(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "input.csv"
            target = tmp / "out" / "converted.csv"

            df = pd.DataFrame(
                {
                    "name": ["товар 1", "товар 2"],
                    "price": [10.5, 20.0],
                    "Unnamed: 2": ["", ""],
                }
            )
            df.to_csv(source, sep=";", encoding="cp1251", index=False)

            convert_csv(source, target)

            self.assertTrue(target.exists())
            out_df = pd.read_csv(target, sep=";", encoding="utf-8")
            self.assertEqual(list(out_df.columns), ["name", "price"])
            self.assertEqual(len(out_df), 2)

    def test_convert_csv_reads_utf8_input_too(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "input_utf8.csv"
            target = tmp / "converted.csv"

            df = pd.DataFrame({"name": ["позиция"], "price": [99.9]})
            df.to_csv(source, sep=";", encoding="utf-8", index=False)

            convert_csv(source, target)

            out_df = pd.read_csv(target, sep=";", encoding="utf-8")
            self.assertEqual(out_df.loc[0, "name"], "позиция")
            self.assertEqual(float(out_df.loc[0, "price"]), 99.9)

    def test_convert_csv_removes_any_unnamed_and_blank_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "input_noise_cols.csv"
            target = tmp / "converted.csv"

            df = pd.DataFrame(
                {
                    "name": ["товар"],
                    "Unnamed: 1": [""],
                    " ": [""],
                    "price": [15.0],
                }
            )
            df.to_csv(source, sep=";", encoding="utf-8", index=False)

            convert_csv(source, target)

            out_df = pd.read_csv(target, sep=";", encoding="utf-8")
            self.assertEqual(list(out_df.columns), ["name", "price"])
            self.assertEqual(float(out_df.loc[0, "price"]), 15.0)

    def test_convert_csv_reads_comma_delimited_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "input_comma.csv"
            target = tmp / "converted.csv"

            df = pd.DataFrame({"name": ["позиция"], "price": [42.0]})
            df.to_csv(source, sep=",", encoding="utf-8", index=False)

            convert_csv(source, target)

            out_df = pd.read_csv(target, sep=";", encoding="utf-8")
            self.assertEqual(list(out_df.columns), ["name", "price"])
            self.assertEqual(out_df.loc[0, "name"], "позиция")
            self.assertEqual(float(out_df.loc[0, "price"]), 42.0)


if __name__ == "__main__":
    unittest.main()
