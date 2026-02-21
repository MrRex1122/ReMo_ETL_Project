import tempfile
import unittest
from pathlib import Path

from matcher import ReMoMatcher


class MatcherCatalogDirTests(unittest.TestCase):
    def test_resolve_catalog_csv_path_accepts_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель ВВГ 3x1.5;A-1;100\n",
                encoding="utf-8",
            )
            matcher = ReMoMatcher.__new__(ReMoMatcher)

            resolved = ReMoMatcher._resolve_catalog_csv_path(matcher, str(root))

            self.assertTrue(resolved.endswith("price_clean_merged.csv"))
            self.assertTrue(Path(resolved).exists())


if __name__ == "__main__":
    unittest.main()
