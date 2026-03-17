import threading
import unittest

from matcher import ReMoMatcher


class NormalizedMatchTests(unittest.TestCase):
    def test_match_uses_normalized_dictionary_before_gemini(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {
            "кабель ввгнг ls 3x2 5": {
                "name": "Кабель ВВГнг-LS 3x2,5",
                "article": "CAB-001",
                "price": 123.45,
                "row_idx": 0,
            }
        }

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._normalize_text = ReMoMatcher._normalize_text.__get__(matcher, ReMoMatcher)
        matcher._match_with_gemini = lambda _query: {"success": False}

        result = ReMoMatcher.match(matcher, "Кабель ВВГнг LS 3x2.5", use_cache=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["found_name"], "Кабель ВВГнг-LS 3x2,5")
        self.assertEqual(result["article"], "CAB-001")
        self.assertEqual(result["price"], 123.45)

    def test_match_handles_missing_normalized_dict_attribute(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._normalize_text = ReMoMatcher._normalize_text.__get__(matcher, ReMoMatcher)
        matcher._match_with_gemini = lambda _query: {
            "found_name": "Позиция отсутствует",
            "price": None,
            "article": None,
            "similarity_score": 0,
            "from_cache": False,
            "success": True,
            "error": None,
        }

        result = ReMoMatcher.match(matcher, "тест", use_cache=True)
        self.assertTrue(result["success"])

    def test_match_prefers_input_article_over_semantic_path(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {}
        matcher.catalog_article_dict = {
            "art-100": {
                "name": "Кабель ВВГнг-LS 3x2,5",
                "article": "ART-100",
                "price": 321.0,
                "row_idx": 1,
                "branch_path": "электрика > кабели",
                "entity_type": "cable",
                "item_markers": {},
            }
        }
        matcher.catalog_items = []
        matcher.parallel_requests = 1
        matcher.retrieval_backend = "memory"
        matcher.retrieval_mode = "legacy_limited"
        matcher._match_context_local = threading.local()
        matcher._match_context_local.payload = {
            "input_article": "ART-100",
            "extracted_article": "WRONG-200",
            "query_article": "ART-100",
        }

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._match_with_gemini = lambda _query: {"success": False}
        matcher._article_match_sanity_reason = lambda *_args, **_kwargs: ""
        matcher._extract_query_features = lambda query: {
            "row_type": "item",
            "entity_type": "cable",
            "attributes": {},
            "markers": {},
            "original_text": query,
            "normalized_text": ReMoMatcher._normalize_text(matcher, query),
            "tokens": [],
        }

        result = ReMoMatcher.match(matcher, "Кабель, артикул WRONG-200", use_cache=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["found_name"], "Кабель ВВГнг-LS 3x2,5")
        self.assertEqual(result["article"], "ART-100")
        self.assertEqual(result["resolution_source"], "article_exact")
        self.assertTrue(result["diagnostic_trace"]["article_lookup_hit"])
        self.assertTrue(result["diagnostic_trace"]["article_lookup_conflict"])
        self.assertEqual(result["diagnostic_trace"]["query_article"], "ART-100")


if __name__ == "__main__":
    unittest.main()
