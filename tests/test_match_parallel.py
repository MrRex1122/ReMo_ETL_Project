import unittest

from matcher import MISSING_POSITION_TEXT, ReMoMatcher


class MatchParallelTests(unittest.TestCase):
    def test_run_matches_parallel_uses_configured_workers(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)

        def fake_match(query, use_cache=True):
            return {
                "found_name": query,
                "price": None,
                "article": None,
                "similarity_score": 1.0,
                "from_cache": False,
                "success": True,
                "error": None,
            }

        matcher.match = fake_match
        matcher._run_matches_parallel = ReMoMatcher._run_matches_parallel.__get__(matcher, ReMoMatcher)

        matcher.parallel_requests = 3
        tasks = [(0, "a"), (1, "b"), (2, "c")]
        results = matcher._run_matches_parallel(tasks)

        self.assertEqual(len(results), 3)
        by_idx = {idx: result for idx, result in results}
        self.assertEqual(by_idx[0]["found_name"], "a")
        self.assertEqual(by_idx[1]["found_name"], "b")
        self.assertEqual(by_idx[2]["found_name"], "c")

    def test_run_matches_parallel_wraps_worker_errors(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)

        def fake_match(query, use_cache=True):
            if query == "boom":
                raise RuntimeError("fail")
            return {
                "found_name": query,
                "price": None,
                "article": None,
                "similarity_score": 1.0,
                "from_cache": False,
                "success": True,
                "error": None,
            }

        matcher.match = fake_match
        matcher._run_matches_parallel = ReMoMatcher._run_matches_parallel.__get__(matcher, ReMoMatcher)

        matcher.parallel_requests = 2
        results = matcher._run_matches_parallel([(0, "ok"), (1, "boom")])

        by_idx = {idx: result for idx, result in results}
        self.assertEqual(by_idx[0]["found_name"], "ok")
        self.assertEqual(by_idx[1]["found_name"], MISSING_POSITION_TEXT)
        self.assertFalse(by_idx[1]["success"])


if __name__ == "__main__":
    unittest.main()
