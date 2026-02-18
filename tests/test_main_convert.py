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


if __name__ == "__main__":
    unittest.main()
