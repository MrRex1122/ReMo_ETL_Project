import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from matcher import DEFAULT_MATCH_PROMPT_TEMPLATE, ReMoMatcher


class PromptTemplateTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ReMoMatcher.__new__(ReMoMatcher)

    def test_default_prompt_template_used_without_env(self):
        with patch("matcher.os.getenv", return_value=None):
            template = ReMoMatcher._load_prompt_template(self.matcher)
        self.assertEqual(template, DEFAULT_MATCH_PROMPT_TEMPLATE)

    def test_custom_prompt_template_loaded_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = Path(tmpdir) / "prompt.txt"
            custom_path.write_text("Q={query}\nC={catalog_context}", encoding="utf-8")

            with patch("matcher.os.getenv", return_value=str(custom_path)):
                template = ReMoMatcher._load_prompt_template(self.matcher)

            self.assertEqual(template, "Q={query}\nC={catalog_context}")

    def test_template_without_placeholders_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = Path(tmpdir) / "prompt.txt"
            custom_path.write_text("just text", encoding="utf-8")

            with patch("matcher.os.getenv", return_value=str(custom_path)):
                template = ReMoMatcher._load_prompt_template(self.matcher)

            self.assertEqual(template, DEFAULT_MATCH_PROMPT_TEMPLATE)


if __name__ == "__main__":
    unittest.main()
