import unittest

from matcher import MATCH_MODE_ANALOG, MATCH_MODE_EXACT, ReMoMatcher


class MatchModesTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ReMoMatcher.__new__(ReMoMatcher)
        self.matcher._sanitize_match_mode = ReMoMatcher._sanitize_match_mode.__get__(self.matcher, ReMoMatcher)
        self.matcher._normalize_query_terms = ReMoMatcher._normalize_query_terms.__get__(self.matcher, ReMoMatcher)
        self.matcher._classify_item_type = ReMoMatcher._classify_item_type.__get__(self.matcher, ReMoMatcher)
        self.matcher._is_disallowed_category_substitution = ReMoMatcher._is_disallowed_category_substitution.__get__(
            self.matcher,
            ReMoMatcher,
        )

    def test_patch_cord_aliases_normalized(self):
        normalized = self.matcher._normalize_query_terms("Patch Cord Cat6")
        self.assertIn("патч корд", normalized)

    def test_exact_mode_blocks_cross_type_substitution(self):
        self.matcher.match_mode = MATCH_MODE_EXACT
        blocked = self.matcher._is_disallowed_category_substitution(
            "Медный патч-корд категории 6 (3м)",
            "Витая пара F/UTP 4PR 23AWG CAT6 PVC INDOOR SOLID синий 305м",
        )
        self.assertTrue(blocked)

    def test_analog_mode_still_blocks_patch_cord_to_bulk_cable(self):
        self.matcher.match_mode = MATCH_MODE_ANALOG
        blocked = self.matcher._is_disallowed_category_substitution(
            "Шнур коммутационный Cat6 3м",
            "Витая пара U/UTP кат 5e 4x2xAWG24 Standart Cu PVC IN 305м",
        )
        self.assertTrue(blocked)


if __name__ == "__main__":
    unittest.main()
