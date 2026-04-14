import ast
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


class AppMatcherCacheUiTests(unittest.TestCase):
    @staticmethod
    def _load_cache_counter():
        app_source = Path("app.py").read_text(encoding="utf-8")
        module = ast.parse(app_source, filename="app.py")

        helper_node = next(
            node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_get_matcher_cache_entry_count"
        )

        isolated_module = ast.Module(body=[helper_node], type_ignores=[])
        ast.fix_missing_locations(isolated_module)

        class DummyLogger:
            def warning(self, *_args, **_kwargs):
                return None

        namespace = {
            "Path": Path,
            "sqlite3": sqlite3,
            "logger": DummyLogger(),
        }
        exec(compile(isolated_module, filename="app.py", mode="exec"), namespace)
        return namespace["_get_matcher_cache_entry_count"]

    def test_cache_count_returns_zero_when_db_exists_without_match_cache_table(self):
        get_matcher_cache_entry_count = self._load_cache_counter()
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS match_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        original_query TEXT
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            self.assertEqual(get_matcher_cache_entry_count(Path(db_path)), 0)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_cache_count_returns_number_of_rows_when_match_cache_exists(self):
        get_matcher_cache_entry_count = self._load_cache_counter()
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS match_cache (
                        query_hash TEXT PRIMARY KEY,
                        original_query TEXT,
                        found_name TEXT,
                        price REAL,
                        article TEXT,
                        similarity_score FLOAT,
                        created_at TIMESTAMP,
                        gemini_raw_response TEXT
                    )
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO match_cache
                    (query_hash, original_query, found_name, price, article, similarity_score, created_at, gemini_raw_response)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ("a", "q1", "n1", None, None, 0.8, "2026-04-14T00:00:00", "raw"),
                        ("b", "q2", "n2", None, None, 0.9, "2026-04-14T00:00:01", "raw"),
                    ],
                )
                conn.commit()
            finally:
                conn.close()

            self.assertEqual(get_matcher_cache_entry_count(Path(db_path)), 2)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


if __name__ == "__main__":
    unittest.main()
