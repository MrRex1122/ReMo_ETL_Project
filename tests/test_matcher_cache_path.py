import inspect
import unittest

import matcher


class MatcherCachePathWiringTests(unittest.TestCase):
    def test_matcher_module_imports_cache_path_resolver(self):
        resolver = getattr(matcher, "get_matcher_cache_db_path", None)
        self.assertTrue(callable(resolver))

    def test_matcher_init_uses_cache_path_resolver(self):
        source = inspect.getsource(matcher.ReMoMatcher.__init__)
        self.assertIn("get_matcher_cache_db_path", source)


if __name__ == "__main__":
    unittest.main()
