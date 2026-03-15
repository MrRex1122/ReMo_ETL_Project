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
        results = list(matcher._run_matches_parallel(tasks))

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
        results = list(matcher._run_matches_parallel([(0, "ok"), (1, "boom")]))

        by_idx = {idx: result for idx, result in results}
        self.assertEqual(by_idx[0]["found_name"], "ok")
        self.assertEqual(by_idx[1]["found_name"], MISSING_POSITION_TEXT)
        self.assertFalse(by_idx[1]["success"])

    def test_prioritize_match_tasks_prefers_cache_hits_and_narrow_families(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher._clean_text_value = ReMoMatcher._clean_text_value
        matcher._prioritize_match_tasks = ReMoMatcher._prioritize_match_tasks.__get__(matcher, ReMoMatcher)
        matcher._get_from_cache = lambda query: {"found_name": "cached"} if query == "cached-item" else None
        matcher._extract_query_features = lambda query: {
            "row_type": "item",
            "entity_type": "rack" if "rack" in query else "patch_panel",
        }
        matcher._entity_family = lambda entity_type: entity_type
        matcher.parallel_requests = 1

        tasks = [(0, "heavy rack item"), (1, "cached-item"), (2, "narrow panel")]
        prioritized = matcher._prioritize_match_tasks(tasks)

        self.assertEqual(prioritized[0], (1, "cached-item"))
        self.assertEqual(prioritized[1], (2, "narrow panel"))
        self.assertEqual(prioritized[2], (0, "heavy rack item"))


if __name__ == "__main__":
    unittest.main()
