import unittest

from matcher import ReMoMatcher


class CandidateSelectionTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ReMoMatcher.__new__(ReMoMatcher)
        self.matcher._normalize_text = ReMoMatcher._normalize_text.__get__(self.matcher, ReMoMatcher)
        self.matcher._tokenize = ReMoMatcher._tokenize.__get__(self.matcher, ReMoMatcher)
        self.matcher._select_candidates = ReMoMatcher._select_candidates.__get__(self.matcher, ReMoMatcher)
        self.matcher._build_catalog_context = ReMoMatcher._build_catalog_context.__get__(self.matcher, ReMoMatcher)

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

    def test_select_candidates_prioritizes_relevant_items(self):
        candidates = self.matcher._select_candidates("блок розеток pdu", limit=2)
        self.assertEqual(len(candidates), 2)
        self.assertIn("блок розеток", candidates[0]["name"].lower())

    def test_build_catalog_context_uses_candidates(self):
        candidates = self.matcher._select_candidates("патч панель", limit=1)
        context = self.matcher._build_catalog_context(candidates)
        self.assertIn("Патч-панель", context)
        self.assertNotEqual(context, "fallback-catalog")


if __name__ == "__main__":
    unittest.main()
