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
                "\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435;\u0410\u0440\u0442\u0438\u043a\u0443\u043b;\u0426\u0435\u043d\u0430 \u0440\u043e\u0437\u043d\u0438\u0447\u043d\u0430\u044f\n"
                "\u041a\u0430\u0431\u0435\u043b\u044c \u0412\u0412\u0413 3x1.5;A-1;100\n",
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
                "\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435;\u0410\u0440\u0442\u0438\u043a\u0443\u043b;\u0426\u0435\u043d\u0430 \u0440\u043e\u0437\u043d\u0438\u0447\u043d\u0430\u044f\n"
                "\u041a\u0430\u0431\u0435\u043b\u044c \u0412\u0412\u0413 3x1.5;A-1;100\n",
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
                "\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435;\u0410\u0440\u0442\u0438\u043a\u0443\u043b;\u0426\u0435\u043d\u0430 \u0440\u043e\u0437\u043d\u0438\u0447\u043d\u0430\u044f\n"
                "\u041a\u0430\u0431\u0435\u043b\u044c \u0412\u0412\u0413 3x1.5;A-1;100\n",
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
                "\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435;\u0410\u0440\u0442\u0438\u043a\u0443\u043b;\u0426\u0435\u043d\u0430 \u0440\u043e\u0437\u043d\u0438\u0447\u043d\u0430\u044f\n"
                "\u041a\u0430\u0431\u0435\u043b\u044c \u0412\u0412\u0413 3x1.5;A-1;100\n",
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
                "\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435;\u0410\u0440\u0442\u0438\u043a\u0443\u043b;\u0426\u0435\u043d\u0430 \u0440\u043e\u0437\u043d\u0438\u0447\u043d\u0430\u044f\n"
                "\u041a\u0430\u0431\u0435\u043b\u044c \u0412\u0412\u0413 3x1.5;A-1;100\n",
                encoding="utf-8",
            )
            merged_path = refresh_merged_catalog(root)
            stale_time = merged_path.stat().st_mtime + 10
            os.utime(clean_file, (stale_time, stale_time))
            matcher = ReMoMatcher.__new__(ReMoMatcher)

            with self.assertRaises(RuntimeError):
                ReMoMatcher._resolve_catalog_csv_path(matcher, str(root))

    def test_matcher_duckdb_search_backend_skips_full_catalog_preload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435;\u0410\u0440\u0442\u0438\u043a\u0443\u043b;\u0426\u0435\u043d\u0430 \u0440\u043e\u0437\u043d\u0438\u0447\u043d\u0430\u044f\n"
                "\u041a\u0430\u0431\u0435\u043b\u044c \u0412\u0412\u0413 3x1.5;A-1;100\n",
                encoding="utf-8",
            )
            refresh_merged_catalog(root)
            refresh_search_catalog(root)

            matcher = ReMoMatcher("test-key", str(root))

            self.assertEqual(Path(matcher.db_csv_path), get_search_catalog_path(root))
            self.assertEqual(matcher.retrieval_backend, "duckdb")
            self.assertEqual(matcher.retrieval_mode, "whole_category")
            self.assertEqual(matcher.catalog_storage_backend, "duckdb")
            self.assertEqual(matcher.catalog_items, [])
            self.assertEqual(matcher.catalog_row_count, 1)
            self.assertTrue(matcher.catalog_text)

    def test_duckdb_search_backend_can_lookup_exact_item_without_preload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435;\u0410\u0440\u0442\u0438\u043a\u0443\u043b;\u0426\u0435\u043d\u0430 \u0440\u043e\u0437\u043d\u0438\u0447\u043d\u0430\u044f\n"
                "\u041a\u0430\u0431\u0435\u043b\u044c \u0412\u0412\u0413 3x1.5;A-1;100\n",
                encoding="utf-8",
            )
            refresh_merged_catalog(root)
            refresh_search_catalog(root)

            matcher = ReMoMatcher("test-key", str(root))
            item = matcher._lookup_catalog_item_by_name("\u041a\u0430\u0431\u0435\u043b\u044c \u0412\u0412\u0413 3x1.5")

            self.assertIsNotNone(item)
            self.assertEqual(item["article"], "A-1")
            self.assertEqual(item["name"], "\u041a\u0430\u0431\u0435\u043b\u044c \u0412\u0412\u0413 3x1.5")

    def test_whole_category_duckdb_retrieval_is_not_limited_by_local_recall_pool(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "\n".join(
                    [
                        "\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435;\u0410\u0440\u0442\u0438\u043a\u0443\u043b;\u0426\u0435\u043d\u0430 \u0440\u043e\u0437\u043d\u0438\u0447\u043d\u0430\u044f",
                        "Patch panel 24 port RJ45 Cat6;PP-24-C6;100",
                        "Patch panel 24 port RJ45 Cat5e;PP-24-C5;110",
                        "Patch panel 48 port RJ45 Cat6;PP-48-C6;120",
                    ]
                ),
                encoding="utf-8",
            )
            refresh_merged_catalog(root)
            refresh_search_catalog(root)

            matcher = ReMoMatcher("test-key", str(root))
            query_text = "Patch panel 24 port RJ45 Cat6"
            query_features = matcher._extract_query_features(query_text)

            self.assertTrue(matcher._should_use_whole_category_retrieval(query_features))

            candidates = matcher._typed_candidate_pool(query_text, query_features, 1)

            self.assertGreaterEqual(len(candidates), 3)
            self.assertEqual(
                query_features.get("query_category_key"),
                matcher._default_branch_paths_for_family(query_features)[0],
            )


if __name__ == "__main__":
    unittest.main()
