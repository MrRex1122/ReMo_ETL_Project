import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

from matcher import MISSING_POSITION_TEXT, ReMoMatcher


class MatcherCacheRetryTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.matcher = ReMoMatcher.__new__(ReMoMatcher)
        self.matcher.cache_db = self.db_path
        self.matcher._hash_query = ReMoMatcher._hash_query.__get__(self.matcher, ReMoMatcher)
        self.matcher._get_from_cache = ReMoMatcher._get_from_cache.__get__(self.matcher, ReMoMatcher)

        conn = sqlite3.connect(self.db_path)
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
        conn.commit()
        conn.close()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def _insert_cache_row(self, query: str, found_name: str, score: float):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT OR REPLACE INTO match_cache
            (query_hash, original_query, found_name, price, article, similarity_score, created_at, gemini_raw_response)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.matcher._hash_query(query),
                query,
                found_name,
                None,
                None,
                score,
                datetime.now().isoformat(),
                "test",
            ),
        )
        conn.commit()
        conn.close()

    def test_cache_hit_with_found_item_is_used(self):
        query = "найденная позиция"
        self._insert_cache_row(query, "Товар 1", 0.9)

        cached = self.matcher._get_from_cache(query)

        self.assertIsNotNone(cached)
        self.assertEqual(cached["found_name"], "Товар 1")
        self.assertTrue(cached["from_cache"])

    def test_cache_hit_with_missing_item_is_ignored_for_retry(self):
        query = "не найденная позиция"
        self._insert_cache_row(query, MISSING_POSITION_TEXT, 0.0)

        cached = self.matcher._get_from_cache(query)

        self.assertIsNone(cached)


if __name__ == "__main__":
    unittest.main()
