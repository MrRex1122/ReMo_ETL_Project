import inspect
import re
import unittest

import matcher


class MatcherConfigResolverWiringTests(unittest.TestCase):
    def test_matcher_module_imports_cache_path_resolver(self):
        resolver = getattr(matcher, "get_matcher_cache_db_path", None)
        self.assertTrue(callable(resolver))

    def test_matcher_init_referenced_config_helpers_exist(self):
        source = inspect.getsource(matcher.ReMoMatcher.__init__)
        helper_names = set(re.findall(r"(get_matcher_[a-z_]+)", source))
        self.assertTrue(helper_names)
        for name in helper_names:
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(matcher, name, None)))


if __name__ == "__main__":
    unittest.main()
