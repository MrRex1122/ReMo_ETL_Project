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


if __name__ == "__main__":
    unittest.main()
