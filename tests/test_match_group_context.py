import unittest

from matcher import ReMoMatcher


class GroupContextTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ReMoMatcher.__new__(ReMoMatcher)
        self.matcher._tokenize = ReMoMatcher._tokenize.__get__(self.matcher, ReMoMatcher)
        self.matcher._build_context_for_query = ReMoMatcher._build_context_for_query.__get__(self.matcher, ReMoMatcher)

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


if __name__ == "__main__":
    unittest.main()
