import unittest

from matcher import ReMoMatcher


class CandidateSelectionTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ReMoMatcher.__new__(ReMoMatcher)
        self.matcher._normalize_text = ReMoMatcher._normalize_text.__get__(self.matcher, ReMoMatcher)
        self.matcher._tokenize = ReMoMatcher._tokenize.__get__(self.matcher, ReMoMatcher)
        self.matcher._rank_candidates = ReMoMatcher._rank_candidates.__get__(self.matcher, ReMoMatcher)
        self.matcher._select_candidates = ReMoMatcher._select_candidates.__get__(self.matcher, ReMoMatcher)
        self.matcher._build_catalog_context = ReMoMatcher._build_catalog_context.__get__(self.matcher, ReMoMatcher)
        self.matcher._try_local_semantic_match = ReMoMatcher._try_local_semantic_match.__get__(self.matcher, ReMoMatcher)

        catalog = [
            {"name": "Горизонтальный блок розеток PDU 1U", "article": "PDU-1U", "price": 100.0},
            {"name": "Вертикальный блок розеток PDU Zero U", "article": "PDU-ZU", "price": 120.0},
            {"name": "Патч-панель 24 порта Cat6", "article": "PP-24", "price": 55.0},
        ]

        self.matcher.catalog_items = []
        self.matcher.token_index = {}
        for idx, raw in enumerate(catalog):
            normalized_name = self.matcher._normalize_text(raw["name"])
            item = {
                "name": raw["name"],
                "name_lc": raw["name"].lower(),
                "article": raw["article"],
                "price": raw["price"],
                "row_idx": idx,
                "normalized_name": normalized_name,
            }
            self.matcher.catalog_items.append(item)
            for token in self.matcher._tokenize(normalized_name):
                self.matcher.token_index.setdefault(token, []).append(item)

        self.matcher.catalog_text = "fallback-catalog"

        self.matcher.local_confidence_threshold = 0.6
        self.matcher.local_margin_threshold = 0.05

        def _save(*_args, **_kwargs):
            return None

        self.matcher._save_to_cache = _save

    def test_select_candidates_prioritizes_relevant_items(self):
        candidates = self.matcher._select_candidates("блок розеток pdu", limit=2)
        self.assertEqual(len(candidates), 2)
        self.assertIn("блок розеток", candidates[0]["name"].lower())

    def test_build_catalog_context_uses_candidates(self):
        candidates = self.matcher._select_candidates("патч панель", limit=1)
        context = self.matcher._build_catalog_context(candidates)
        self.assertIn("Патч-панель", context)
        self.assertNotEqual(context, "fallback-catalog")

    def test_try_local_semantic_match_returns_result_for_confident_top_hit(self):
        result = self.matcher._try_local_semantic_match("патч панель cat6 24")
        self.assertIsNotNone(result)
        self.assertEqual(result["found_name"], "Патч-панель 24 порта Cat6")
        self.assertGreater(result["similarity_score"], 0.6)

    def test_try_local_semantic_match_skips_ambiguous_hits(self):
        self.matcher.local_margin_threshold = 0.2
        result = self.matcher._try_local_semantic_match("блок розеток pdu")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
