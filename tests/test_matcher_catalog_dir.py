import os
import tempfile
import unittest
from pathlib import Path

from catalog_merge import refresh_merged_catalog
from catalog_search import get_search_catalog_path, refresh_search_catalog
from matcher import ReMoMatcher


class MatcherCatalogDirTests(unittest.TestCase):
    def test_resolve_catalog_csv_path_prefers_search_catalog_when_it_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель ВВГ 3x1.5;A-1;100\n",
                encoding="utf-8",
            )
            refresh_merged_catalog(root)
            refresh_search_catalog(root)
            matcher = ReMoMatcher.__new__(ReMoMatcher)

            resolved = ReMoMatcher._resolve_catalog_csv_path(matcher, str(root))

            self.assertEqual(Path(resolved), get_search_catalog_path(root))
            self.assertTrue(Path(resolved).exists())

    def test_resolve_catalog_csv_path_accepts_directory_with_prepared_merged_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель ВВГ 3x1.5;A-1;100\n",
                encoding="utf-8",
            )
            refresh_merged_catalog(root)
            matcher = ReMoMatcher.__new__(ReMoMatcher)

            resolved = ReMoMatcher._resolve_catalog_csv_path(matcher, str(root))

            self.assertTrue(resolved.endswith("price_clean_merged.csv"))
            self.assertTrue(Path(resolved).exists())

    def test_resolve_catalog_csv_path_falls_back_to_merged_when_search_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель ВВГ 3x1.5;A-1;100\n",
                encoding="utf-8",
            )
            merged_path = refresh_merged_catalog(root)
            search_path = refresh_search_catalog(root)
            newer_time = merged_path.stat().st_mtime + 10
            os.utime(merged_path, (newer_time, newer_time))
            matcher = ReMoMatcher.__new__(ReMoMatcher)

            resolved = ReMoMatcher._resolve_catalog_csv_path(matcher, str(root))

            self.assertEqual(Path(resolved), merged_path)
            self.assertNotEqual(Path(resolved), search_path)

    def test_resolve_catalog_csv_path_rejects_directory_without_prepared_merged_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель ВВГ 3x1.5;A-1;100\n",
                encoding="utf-8",
            )
            matcher = ReMoMatcher.__new__(ReMoMatcher)

            with self.assertRaises(FileNotFoundError):
                ReMoMatcher._resolve_catalog_csv_path(matcher, str(root))

    def test_resolve_catalog_csv_path_rejects_stale_merged_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            clean_file = root / "price14_clean.csv"
            clean_file.write_text(
                "Наименование;Артикул;Цена розничная\nКабель ВВГ 3x1.5;A-1;100\n",
                encoding="utf-8",
            )
            merged_path = refresh_merged_catalog(root)
            stale_time = merged_path.stat().st_mtime + 10
            os.utime(clean_file, (stale_time, stale_time))
            matcher = ReMoMatcher.__new__(ReMoMatcher)

            with self.assertRaises(RuntimeError):
                ReMoMatcher._resolve_catalog_csv_path(matcher, str(root))


if __name__ == "__main__":
    unittest.main()
