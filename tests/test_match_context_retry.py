import time
import unittest

from matcher import MISSING_POSITION_TEXT, ReMoMatcher


class MatchContextRetryTests(unittest.TestCase):
    def test_match_with_gemini_retries_next_context_chunk(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {
            "нужный товар": {
                "name": "Нужный товар",
                "article": "ART-1",
                "price": 123.0,
            }
        }
        matcher.model_name = None
        matcher._candidate_models = lambda: ["gemini-2.5-flash"]
        matcher._build_context_chunks = lambda query, max_chunks=None: ["chunk-one", "chunk-two"]

        calls = {"count": 0}

        def fake_generate(prompt: str, model_name: str) -> str:
            calls["count"] += 1
            if "chunk-one" in prompt:
                return '{"found_name": null, "article": null, "confidence": 0}'
            return '{"found_name": "Нужный товар", "article": "ART-1", "confidence": 0.91}'

        matcher._generate_gemini_text = fake_generate

        saved = {"count": 0}

        def fake_save(*args, **kwargs):
            saved["count"] += 1

        matcher._save_to_cache = fake_save

        result = ReMoMatcher._match_with_gemini(matcher, "тест")

        self.assertEqual(calls["count"], 2)
        self.assertEqual(saved["count"], 1)
        self.assertEqual(result["found_name"], "Нужный товар")
        self.assertEqual(result["price"], 123.0)
        self.assertEqual(result["article"], "ART-1")

    def test_match_with_gemini_returns_missing_after_all_chunks(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.model_name = None
        matcher._candidate_models = lambda: ["gemini-2.5-flash"]
        matcher._build_context_chunks = lambda query, max_chunks=None: ["chunk-one", "chunk-two"]
        matcher._generate_gemini_text = lambda prompt, model: '{"found_name": null, "article": null, "confidence": 0}'
        matcher._save_to_cache = lambda *args, **kwargs: None

        result = ReMoMatcher._match_with_gemini(matcher, "тест")

        self.assertEqual(result["found_name"], MISSING_POSITION_TEXT)
        self.assertTrue(result["success"])

    def test_match_with_gemini_keeps_chunk_priority_when_later_chunk_finishes_first(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {
            "товар a": {"name": "Товар A", "article": "A-1", "price": 10.0},
            "товар b": {"name": "Товар B", "article": "B-1", "price": 20.0},
        }
        matcher.model_name = None
        matcher.parallel_requests = 4
        matcher.gemini_max_chunks = 4
        matcher.gemini_chunk_parallelism = 2
        matcher._candidate_models = lambda: ["gemini-2.5-flash"]
        matcher._build_context_chunks = lambda query, max_chunks=None: ["chunk-one", "chunk-two"]

        def fake_generate(prompt: str, model_name: str) -> str:
            if "chunk-one" in prompt:
                time.sleep(0.15)
                return '{"found_name": "Товар A", "article": "A-1", "confidence": 0.91}'
            time.sleep(0.01)
            return '{"found_name": "Товар B", "article": "B-1", "confidence": 0.93}'

        matcher._generate_gemini_text = fake_generate
        matcher._save_to_cache = lambda *args, **kwargs: None

        result = ReMoMatcher._match_with_gemini(matcher, "тест")

        self.assertEqual(result["found_name"], "Товар A")
        self.assertEqual(result["article"], "A-1")


if __name__ == "__main__":
    unittest.main()
