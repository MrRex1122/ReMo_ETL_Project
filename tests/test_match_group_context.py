import unittest

import pandas as pd

from matcher import (
    CANONICAL_ARTICLE_COLUMN,
    CANONICAL_NAME_COLUMN,
    CANONICAL_PRICE_COLUMN,
    ReMoMatcher,
)


class GroupContextTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ReMoMatcher.__new__(ReMoMatcher)
        self.matcher._tokenize = ReMoMatcher._tokenize.__get__(self.matcher, ReMoMatcher)
        self.matcher._rank_group_candidates = ReMoMatcher._rank_group_candidates.__get__(self.matcher, ReMoMatcher)
        self.matcher._build_context_for_query = ReMoMatcher._build_context_for_query.__get__(self.matcher, ReMoMatcher)
        self.matcher._build_context_chunks = ReMoMatcher._build_context_chunks.__get__(self.matcher, ReMoMatcher)

        item1 = {
            "name": "Медный патч-корд категории 6 3м",
            "name_lc": "медный патч-корд категории 6 3м",
            "article": "PC-3",
            "price": 100,
            "row_idx": 1,
        }
        item2 = {
            "name": "Медный патч-корд категории 6 5м",
            "name_lc": "медный патч-корд категории 6 5м",
            "article": "PC-5",
            "price": 120,
            "row_idx": 2,
        }
        item3 = {
            "name": "Оптический кросс 24 волокна",
            "name_lc": "оптический кросс 24 волокна",
            "article": "OX-24",
            "price": 900,
            "row_idx": 10,
        }

        self.matcher.group_index = {
            "патч": [item1, item2],
            "корд": [item1, item2],
            "cat6": [item1, item2],
            "оптический": [item3],
        }
        self.matcher.catalog_text = "fallback"

    def test_build_context_for_query_uses_group_items(self):
        context = self.matcher._build_context_for_query("патч корд cat6")
        self.assertIn("патч-корд", context.lower())
        self.assertNotEqual(context, "fallback")

    def test_build_context_for_query_falls_back_when_no_group_match(self):
        context = self.matcher._build_context_for_query("шкаф серверный")
        self.assertEqual(context, "fallback")

    def test_prepare_catalog_text_uses_canonical_columns(self):
        self.matcher.catalog = pd.DataFrame(
            [
                {
                    CANONICAL_NAME_COLUMN: "Кабель UTP cat6",
                    CANONICAL_ARTICLE_COLUMN: "UTP-6",
                    CANONICAL_PRICE_COLUMN: 50,
                }
            ]
        )
        self.matcher._prepare_catalog_text = ReMoMatcher._prepare_catalog_text.__get__(self.matcher, ReMoMatcher)

        self.matcher._prepare_catalog_text(max_items=1)

        self.assertIn("Кабель UTP cat6", self.matcher.catalog_text)
        self.assertIn("UTP-6", self.matcher.catalog_text)

    def test_build_context_chunks_splits_large_groups(self):
        many_items = []
        for idx in range(650):
            many_items.append(
                {
                    "name": f"Кабель cat6 позиция {idx}",
                    "name_lc": f"кабель cat6 позиция {idx}",
                    "article": f"A-{idx}",
                    "price": idx,
                    "row_idx": idx,
                }
            )
        self.matcher.group_index = {"кабель": many_items, "cat6": many_items}

        chunks = self.matcher._build_context_chunks("кабель cat6", chunk_size=300, max_chunks=4)

        self.assertEqual(len(chunks), 3)
        self.assertIn("позиция 0", chunks[0])
        self.assertIn("позиция 600", chunks[2])


if __name__ == "__main__":
    unittest.main()
