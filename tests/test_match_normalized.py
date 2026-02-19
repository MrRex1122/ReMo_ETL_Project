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

        def _no_cache(_query):
            return None

        def _save(*_args, **_kwargs):
            return None

        matcher._get_from_cache = _no_cache
        matcher._save_to_cache = _save
        matcher._normalize_text = ReMoMatcher._normalize_text.__get__(matcher, ReMoMatcher)

        result = ReMoMatcher.match(matcher, "Кабель ВВГнг LS 3x2.5", use_cache=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["found_name"], "Кабель ВВГнг-LS 3x2,5")
        self.assertEqual(result["article"], "CAB-001")
        self.assertEqual(result["price"], 123.45)


if __name__ == "__main__":
    unittest.main()
