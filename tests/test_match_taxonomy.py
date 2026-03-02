import unittest

from matcher import ReMoMatcher


class MatchTaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ReMoMatcher.__new__(ReMoMatcher)
        self.matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(self.matcher)
        self.matcher._normalize_query_terms = ReMoMatcher._normalize_query_terms.__get__(self.matcher, ReMoMatcher)
        self.matcher._normalize_text = ReMoMatcher._normalize_text.__get__(self.matcher, ReMoMatcher)
        self.matcher._tokenize = ReMoMatcher._tokenize.__get__(self.matcher, ReMoMatcher)
        self.matcher._classify_item_type = ReMoMatcher._classify_item_type.__get__(self.matcher, ReMoMatcher)
        self.matcher._detect_query_row_type = ReMoMatcher._detect_query_row_type.__get__(self.matcher, ReMoMatcher)
        self.matcher._extract_query_features = ReMoMatcher._extract_query_features.__get__(self.matcher, ReMoMatcher)
        self.matcher._rank_branches = ReMoMatcher._rank_branches.__get__(self.matcher, ReMoMatcher)
        self.matcher._rank_candidates = ReMoMatcher._rank_candidates.__get__(self.matcher, ReMoMatcher)
        self.matcher._branch_match_bonus = ReMoMatcher._branch_match_bonus.__get__(self.matcher, ReMoMatcher)
        self.matcher._apply_attribute_score = ReMoMatcher._apply_attribute_score.__get__(self.matcher, ReMoMatcher)
        self.matcher._score_candidates_locally = ReMoMatcher._score_candidates_locally.__get__(self.matcher, ReMoMatcher)
        self.matcher._is_disallowed_category_substitution = ReMoMatcher._is_disallowed_category_substitution.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher.match_mode = "exact"
        self.matcher.branch_index = {
            "телеком > питание > pdu": [],
            "телеком > питание > pdu > zero u": [],
            "телеком > коммутация > патч панели": [],
        }
        self.matcher.branch_prefix_index = {
            "телеком > питание > pdu": [],
            "телеком > питание > pdu > zero u": [],
            "телеком > коммутация > патч панели": [],
        }
        self.matcher.branch_token_index = {
            "pdu": ["телеком > питание > pdu", "телеком > питание > pdu > zero u"],
            "zero": ["телеком > питание > pdu > zero u"],
            "u": ["телеком > питание > pdu > zero u"],
            "блок": ["телеком > питание > pdu"],
        }
        self.matcher.branch_priority_scores = {
            "телеком > питание > pdu > zero u": 0.35,
            "телеком > питание > pdu": 0.25,
        }
        self.matcher.token_idf = {"pdu": 2.0, "zero": 2.5, "блок": 1.5}

    def test_detect_query_row_type_marks_section_rows(self):
        self.assertEqual(self.matcher._detect_query_row_type("Шкафы телекоммуникационные"), "section")

    def test_rank_branches_prefers_zero_u_pdu_path(self):
        features = self.matcher._extract_query_features("Вертикальный блок розеток PDU Zero U")
        ranked = self.matcher._rank_branches(features)

        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["path"], "телеком > питание > pdu > zero u")

    def test_score_candidates_locally_prefers_zero_u_candidate(self):
        features = self.matcher._extract_query_features("Вертикальный блок розеток PDU Zero U")
        features["ranked_branches"] = [
            {"path": "телеком > питание > pdu > zero u", "score": 8.0},
            {"path": "телеком > питание > pdu", "score": 6.0},
        ]

        zero_u = {
            "name": "Вертикальный блок розеток PDU Zero U",
            "name_lc": "вертикальный блок розеток pdu zero u",
            "normalized_name": "вертикальный блок розеток pdu zero u",
            "article": "PDU-ZU",
            "price": 100.0,
            "row_idx": 1,
            "tokens": ["вертикальный", "блок", "розеток", "pdu", "zero", "u"],
            "branch_path": "телеком > питание > pdu > zero u",
            "entity_type": "pdu",
        }
        one_u = {
            "name": "Горизонтальный блок розеток PDU 1U",
            "name_lc": "горизонтальный блок розеток pdu 1u",
            "normalized_name": "горизонтальный блок розеток pdu 1u",
            "article": "PDU-1U",
            "price": 95.0,
            "row_idx": 2,
            "tokens": ["горизонтальный", "блок", "розеток", "pdu", "1u"],
            "branch_path": "телеком > питание > pdu",
            "entity_type": "pdu",
        }
        self.matcher.catalog_items = [zero_u, one_u]
        self.matcher.token_index = {
            "блок": [zero_u, one_u],
            "розеток": [zero_u, one_u],
            "pdu": [zero_u, one_u],
            "zero": [zero_u],
            "u": [zero_u],
        }

        ranked = self.matcher._score_candidates_locally(features, [zero_u, one_u])

        self.assertEqual(ranked[0]["item"]["article"], "PDU-ZU")
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])


if __name__ == "__main__":
    unittest.main()
