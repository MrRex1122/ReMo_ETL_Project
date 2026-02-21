import os
import unittest

from matcher import ReMoMatcher


class MatcherModelsTests(unittest.TestCase):
    def setUp(self):
        self._models_backup = os.environ.get("REMO_MATCHER_MODELS")

    def tearDown(self):
        if self._models_backup is None:
            os.environ.pop("REMO_MATCHER_MODELS", None)
        else:
            os.environ["REMO_MATCHER_MODELS"] = self._models_backup

    def test_candidate_models_uses_config_models_and_dedupes(self):
        os.environ["REMO_MATCHER_MODELS"] = "model-a, model-b, model-a"
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.model_name = "model-b"
        matcher._candidate_models = ReMoMatcher._candidate_models.__get__(matcher, ReMoMatcher)

        models = matcher._candidate_models()

        self.assertEqual(models, ["model-b", "model-a"])


if __name__ == "__main__":
    unittest.main()
