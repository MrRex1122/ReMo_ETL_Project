import tempfile
import unittest
from pathlib import Path

import pandas as pd

from matcher import ReMoMatcher


class MatcherCatalogSchemaTests(unittest.TestCase):
    @staticmethod
    def _build_matcher(catalog_path: Path) -> ReMoMatcher:
        matcher = object.__new__(ReMoMatcher)
        matcher.db_csv_path = str(catalog_path)
        matcher.catalog = None
        matcher.catalog_dict = None
        matcher.catalog_text = None
        return matcher

    def test_load_catalog_supports_alias_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            catalog_path = tmp / "catalog.csv"
            pd.DataFrame(
                {
                    "Номенклатура": ["Автомат 16A"],
                    "Код товара": ["SKU-16A"],
                    "Цена": ["1 234,56"],
                }
            ).to_csv(catalog_path, sep=";", encoding="utf-8", index=False)

            matcher = self._build_matcher(catalog_path)
            matcher._load_catalog()

            self.assertIn("автомат 16a", matcher.catalog_dict)
            item = matcher.catalog_dict["автомат 16a"]
            self.assertEqual(item["article"], "SKU-16A")
            self.assertAlmostEqual(item["price"], 1234.56, places=2)

    def test_load_catalog_raises_when_name_column_cannot_be_resolved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            catalog_path = tmp / "catalog.csv"
            pd.DataFrame(
                {
                    "Описание": ["Только описание"],
                    "SKU": ["SKU-001"],
                }
            ).to_csv(catalog_path, sep=";", encoding="utf-8", index=False)

            matcher = self._build_matcher(catalog_path)
            with self.assertRaises(ValueError):
                matcher._load_catalog()


if __name__ == "__main__":
    unittest.main()
