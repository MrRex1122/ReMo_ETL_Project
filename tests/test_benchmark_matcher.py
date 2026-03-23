import unittest
from pathlib import Path

from benchmark_matcher import (
    AUTO_ACCEPT_RESOLVERS,
    DEFAULT_FIXTURE_PATH,
    FIXTURE_COLUMNS,
    build_benchmark_input_dataframe,
    is_auto_accept_result,
    load_golden_cases,
    score_benchmark_case,
)


class BenchmarkFixtureTests(unittest.TestCase):
    def test_fixture_loads_and_has_expected_schema(self):
        fixture_path = Path(DEFAULT_FIXTURE_PATH)
        self.assertTrue(fixture_path.exists(), f"Missing fixture: {fixture_path}")
        cases = load_golden_cases(fixture_path)
        self.assertGreaterEqual(len(cases), 100)
        smoke_count = sum(case["tier"] == "smoke" for case in cases)
        self.assertGreaterEqual(smoke_count, 10)
        suites = {case["suite"] for case in cases}
        self.assertIn("electrical_article", suites)
        self.assertIn("rack_accessory", suites)
        self.assertIn("telecom_semantic", suites)
        self.assertIn("adversarial", suites)
        self.assertIn("catalog_gap", suites)

    def test_input_frame_preserves_article_column_mode(self):
        case = {
            "case_id": "demo_case",
            "suite": "demo",
            "tier": "smoke",
            "input_mode": "article_column",
            "query_text": "Крышка на лоток 100 мм",
            "query_article": "35522",
            "expected_family": "rack_accessory_strict",
            "expected_outcome": "exact",
            "expected_articles": ["35522"],
            "forbidden_articles": [],
            "allowed_resolvers": ["article_exact"],
            "notes": "",
            "source_ref": "",
        }
        frame = build_benchmark_input_dataframe([case])
        self.assertEqual(list(frame.columns), ["Case ID", "Наименование оборудования, материалов и кабелей", "Артикул"])
        self.assertEqual(frame.loc[0, "Артикул"], "35522")


class BenchmarkScoringTests(unittest.TestCase):
    def test_exact_case_passes_only_for_allowed_auto_accept(self):
        case = {
            "expected_outcome": "exact",
            "expected_articles": ["35522"],
            "forbidden_articles": [],
            "allowed_resolvers": ["article_exact"],
        }
        actual = {
            "found_name": "Крышка на лоток 100 мм L=3000мм с заземлением",
            "found_article": "35522",
            "resolver_name": "article_exact",
            "compatibility_status": "compatible",
            "requires_review": "нет",
            "pipeline_stage": "resolved",
            "root_cause_code": "resolved",
        }
        scored = score_benchmark_case(case, actual)
        self.assertTrue(scored["benchmark_pass"])
        self.assertTrue(scored["auto_accept"])

        actual["resolver_name"] = "compatible_local_fallback"
        scored = score_benchmark_case(case, actual)
        self.assertFalse(scored["benchmark_pass"])
        self.assertEqual(scored["failure_bucket"], "false_negative")

    def test_review_case_fails_on_wrong_auto_accept(self):
        case = {
            "expected_outcome": "review",
            "expected_articles": [],
            "forbidden_articles": ["35262"],
            "allowed_resolvers": [],
        }
        actual = {
            "found_name": "Светильник светодиодный",
            "found_article": "35262",
            "resolver_name": "article_exact",
            "compatibility_status": "compatible",
            "requires_review": "нет",
            "pipeline_stage": "resolved",
            "root_cause_code": "resolved",
        }
        scored = score_benchmark_case(case, actual)
        self.assertFalse(scored["benchmark_pass"])
        self.assertTrue(scored["auto_accept"])
        self.assertTrue(scored["forbidden_article_hit"])

    def test_catalog_gap_requires_unresolved(self):
        case = {
            "expected_outcome": "catalog_gap",
            "expected_articles": [],
            "forbidden_articles": [],
            "allowed_resolvers": [],
        }
        actual = {
            "found_name": "Позиция отсутствует",
            "found_article": "",
            "resolver_name": "unresolved",
            "compatibility_status": "unresolved_no_compatible_candidates",
            "requires_review": "да",
            "pipeline_stage": "compatibility_filter",
            "root_cause_code": "no_compatible_candidates",
        }
        scored = score_benchmark_case(case, actual)
        self.assertTrue(scored["benchmark_pass"])
        self.assertFalse(scored["auto_accept"])

    def test_non_target_requires_input_rejection(self):
        case = {
            "expected_outcome": "non_target",
            "expected_articles": [],
            "forbidden_articles": [],
            "allowed_resolvers": [],
        }
        actual = {
            "found_name": "Позиция отсутствует",
            "found_article": "",
            "resolver_name": "unresolved",
            "compatibility_status": "unresolved_no_compatible_candidates",
            "requires_review": "да",
            "pipeline_stage": "query_input",
            "root_cause_code": "section_row_detected",
        }
        scored = score_benchmark_case(case, actual)
        self.assertTrue(scored["benchmark_pass"])

    def test_article_series_is_not_auto_accept_without_explicit_case_permission(self):
        case = {
            "expected_outcome": "review",
            "expected_articles": [],
            "forbidden_articles": [],
            "allowed_resolvers": [],
        }
        actual = {
            "found_name": "Никелированная пластина для заземления PTCE",
            "found_article": "37501R",
            "resolver_name": "article_series_local",
            "compatibility_status": "compatible",
            "requires_review": "нет",
            "pipeline_stage": "resolved",
            "root_cause_code": "resolved",
        }
        self.assertNotIn("article_series_local", AUTO_ACCEPT_RESOLVERS)
        self.assertFalse(is_auto_accept_result(case, actual))

    def test_verifier_decision_takes_precedence_for_auto_accept(self):
        case = {
            "expected_outcome": "review",
            "expected_articles": [],
            "forbidden_articles": [],
            "allowed_resolvers": [],
        }
        actual = {
            "found_name": "Крышка на лоток 100 мм L=3000мм с заземлением",
            "found_article": "35522",
            "resolver_name": "article_exact",
            "verifier_decision": "review",
            "compatibility_status": "compatible",
            "requires_review": "нет",
            "pipeline_stage": "resolved",
            "root_cause_code": "resolved",
        }
        self.assertFalse(is_auto_accept_result(case, actual))


if __name__ == "__main__":
    unittest.main()
