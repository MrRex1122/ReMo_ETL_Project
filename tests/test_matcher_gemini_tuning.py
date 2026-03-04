import unittest

from matcher import ReMoMatcher


class MatcherGeminiTuningTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ReMoMatcher.__new__(ReMoMatcher)
        self.matcher._build_narrow_candidate_chunks = ReMoMatcher._build_narrow_candidate_chunks.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._clean_text_value = ReMoMatcher._clean_text_value
        self.matcher._top_branch_gap = ReMoMatcher._top_branch_gap
        self.matcher._is_weak_shortlist = ReMoMatcher._is_weak_shortlist.__get__(self.matcher, ReMoMatcher)
        self.matcher.gemini_chunk_size = 12
        self.matcher.gemini_max_chunks = 3

    def test_build_narrow_candidate_chunks_respects_chunk_and_max_chunk_limits(self):
        candidates = [
            {
                "name": f"Candidate {idx}",
                "article": f"A-{idx}",
                "price": idx,
                "branch_path": "test > branch",
            }
            for idx in range(40)
        ]

        chunks = self.matcher._build_narrow_candidate_chunks(
            branches=["test > branch"],
            candidates=candidates,
            query_features={"attributes": {"category": "cat6"}},
            query="sample query",
        )

        self.assertEqual(len(chunks), 3)
        joined = "\n".join(chunks)
        self.assertIn("Candidate 35", joined)
        self.assertNotIn("Candidate 36", joined)

    def test_is_weak_shortlist_identifies_small_low_confidence_shortlist(self):
        weak_entries = [
            {"score": 0.40, "item": {}},
            {"score": 0.32, "item": {}},
        ]
        self.assertTrue(self.matcher._is_weak_shortlist(weak_entries, []))

        stronger_entries = [
            {"score": 0.52, "item": {}},
            {"score": 0.45, "item": {}},
        ]
        ranked_branches = [{"path": "branch", "score": 1.0}]
        self.assertFalse(self.matcher._is_weak_shortlist(stronger_entries, ranked_branches))


if __name__ == "__main__":
    unittest.main()
