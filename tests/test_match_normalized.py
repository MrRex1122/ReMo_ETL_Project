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

    def test_match_uses_article_designation_exact_for_cable_signature(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {}
        matcher.catalog_article_dict = {}
        matcher.catalog_items = []
        matcher.parallel_requests = 1
        matcher.retrieval_backend = "memory"
        matcher.retrieval_mode = "legacy_limited"
        matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(matcher)
        matcher.match_mode = "exact"
        matcher.branch_index = {}
        matcher.branch_prefix_index = {}
        matcher.branch_token_index = {}
        matcher.branch_priority_scores = {}
        matcher.token_idf = {}
        matcher._match_context_local = threading.local()
        matcher._match_context_local.payload = {
            "input_article": "",
            "extracted_article": "ВВГнг(A)-LS 4x4",
            "query_article": "ВВГнг(A)-LS 4x4",
        }

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._uses_duckdb_query_backend = lambda: False
        matcher._typed_candidate_pool = lambda _query_text, _query_features, limit: []
        matcher._select_candidates = lambda _query_text, limit: []
        matcher._collect_branch_candidates = lambda _branches, limit=None, query_features=None: [
            {
                "name": "Кабель ВВГнг(А)-LS 4x4 ок(N)-1",
                "article": "4582",
                "price": 250.0,
                "row_idx": 7,
                "branch_path": "электрика > кабели",
                "entity_type": "cable",
                "item_markers": {},
                "normalized_name": "кабель ввгнг а ls 4x4 ок n 1",
                "tokens": ["кабель", "ввгнг", "ls", "4x4"],
            }
        ]

        result = ReMoMatcher.match(matcher, "Кабель, артикул ВВГнг(A)-LS 4x4", use_cache=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["article"], "4582")
        self.assertEqual(result["resolution_source"], "article_designation_exact")
        self.assertEqual(result["compatibility_status"], "compatible")

    def test_match_uses_article_series_local_after_article_conflict(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {}
        matcher.catalog_article_dict = {
            "37501": {
                "name": "Светильник светодиодный",
                "article": "37501",
                "price": 100.0,
                "row_idx": 1,
                "branch_path": "свет > светильники",
                "entity_type": "other",
                "item_markers": {},
            }
        }
        matcher.catalog_items = []
        matcher.parallel_requests = 1
        matcher.retrieval_backend = "memory"
        matcher.retrieval_mode = "legacy_limited"
        matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(matcher)
        matcher.match_mode = "exact"
        matcher.branch_index = {}
        matcher.branch_prefix_index = {}
        matcher.branch_token_index = {}
        matcher.branch_priority_scores = {}
        matcher.token_idf = {}
        matcher._match_context_local = threading.local()
        matcher._match_context_local.payload = {
            "input_article": "",
            "extracted_article": "37501",
            "query_article": "37501",
        }

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._uses_duckdb_query_backend = lambda: False
        series_item = {
            "name": "Пластина для заземления PTCE",
            "article": "37501R",
            "price": 250.0,
            "row_idx": 2,
            "branch_path": "аксессуары вспомогательные",
            "entity_type": "other",
            "item_markers": {},
            "normalized_name": "пластина для заземления ptce",
            "tokens": ["пластина", "заземления", "ptce"],
        }
        matcher._lookup_catalog_items_by_article_series = lambda _article, _features: [series_item]
        matcher._best_article_series_match = lambda _features, _candidates, article="": series_item

        result = ReMoMatcher.match(matcher, "Пластина для заземления PTCE, артикул 37501", use_cache=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["article"], "37501R")
        self.assertEqual(result["resolution_source"], "article_series_local")
        self.assertEqual(result["compatibility_status"], "compatible")


if __name__ == "__main__":
    unittest.main()
