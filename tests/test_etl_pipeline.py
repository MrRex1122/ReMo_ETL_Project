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


if __name__ == "__main__":
    unittest.main()
