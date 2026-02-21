import unittest

from matcher import ReMoMatcher


class MatcherModelsTests(unittest.TestCase):
    def test_candidate_models_uses_config_models(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.model_name = None
        matcher._candidate_models = ReMoMatcher._candidate_models.__get__(matcher, ReMoMatcher)

        models = matcher._candidate_models()

        self.assertTrue(models)
        self.assertIsInstance(models, list)


if __name__ == "__main__":
    unittest.main()
