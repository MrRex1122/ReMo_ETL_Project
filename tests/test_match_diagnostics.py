import unittest

import pandas as pd

from match_diagnostics import (
    apply_match_diagnostics_summary_to_stats,
    apply_match_diagnostics_to_result_dataframe,
    build_match_diagnostics_payload,
    enrich_match_diagnostics_payload,
    is_match_diagnostics_fresh,
    prepare_match_diagnostics_reason_table,
    prepare_match_diagnostics_resolver_table,
    prepare_match_diagnostics_root_cause_table,
    prepare_match_diagnostics_stage_table,
    prepare_match_diagnostics_table,
    reconstruct_match_diagnostics,
)


class MatchDiagnosticsTests(unittest.TestCase):
    def test_runtime_payload_builds_pipeline_and_root_cause_summary(self):
        payload = build_match_diagnostics_payload(
            [
                {
                    "run_row_number": 2,
                    "query_text": "Патч-панель",
                    "row_type": "item",
                    "entity_type": "patch_panel",
                    "query_family": "patch_panel",
                    "resolution_source": "unresolved",
                    "compatibility_status": "unresolved_no_compatible_candidates",
                    "incompatibility_reason": "no_compatible_candidates",
                    "stage_of_failure": "compatibility_filter",
                    "reason_code": "no_compatible_candidates",
                    "reason_class": "matcher_retrieval_or_ranking",
                    "pipeline_counts": {"local_pool_count": 10, "scored_count": 4, "same_family_count": 2, "compatible_count": 0},
                    "candidate_snapshots": {},
                    "gemini": {"attempted": False},
                    "trace_steps": [],
                }
            ],
            run_id="run-1",
        )

        self.assertEqual(payload["summary"]["rows_total"], 1)
        self.assertEqual(payload["summary"]["rows_unresolved"], 1)
        self.assertEqual(payload["summary"]["pipeline_stage_counts"]["compatibility_filter"], 1)
        self.assertEqual(payload["summary"]["root_cause_class_counts"]["matcher_retrieval_or_ranking"], 1)
        self.assertTrue(is_match_diagnostics_fresh(payload, run_id="run-1"))

    def test_reconstructed_payload_marks_section_like_rows_as_query_input(self):
        df = pd.DataFrame(
            {
                "Наименование оборудования, материалов и кабелей": ["Шкафы телекоммуникационные"],
                "Найденная номенклатура": ["Позиция отсутствует"],
                "Источник решения": ["unresolved"],
                "Совместимость решения": ["unresolved_no_compatible_candidates"],
                "Причина несовместимости": ["section_row_detected"],
                "Gemini shortlist": [0],
                "Gemini visible candidates": [0],
                "Gemini truncated": [0],
            }
        )

        payload = reconstruct_match_diagnostics(df, run_id="run-1")
        row = payload["rows"][0]
        self.assertTrue(payload["reconstructed"])
        self.assertEqual(row["pipeline_stage"], "query_input")
        self.assertEqual(row["pipeline_reason_code"], "section_row_detected")
        self.assertEqual(row["root_cause_code"], "section_row_detected")

    def test_coverage_audit_enrichment_keeps_pipeline_stage_and_sets_catalog_gap_root_cause(self):
        diagnostics = build_match_diagnostics_payload(
            [
                {
                    "run_row_number": 5,
                    "query_text": "Оптический кросс",
                    "row_type": "item",
                    "entity_type": "optical_cross",
                    "query_family": "optical_cross",
                    "resolution_source": "unresolved",
                    "compatibility_status": "unresolved_no_compatible_candidates",
                    "incompatibility_reason": "no_compatible_candidates",
                    "stage_of_failure": "local_recall",
                    "reason_code": "no_compatible_candidates",
                    "reason_class": "matcher_retrieval_or_ranking",
                    "pipeline_counts": {},
                    "candidate_snapshots": {},
                    "gemini": {"attempted": False},
                    "trace_steps": [],
                }
            ],
            run_id="run-1",
        )
        coverage_audit = {
            "rows": [
                {
                    "run_row_number": 5,
                    "diagnosis": "catalog_missing_family",
                    "gap_reason_code": "missing_family",
                    "same_family_candidates_count": 0,
                    "compatible_candidates_count": 0,
                    "candidate_examples": [],
                }
            ]
        }

        enriched = enrich_match_diagnostics_payload(diagnostics, coverage_audit_payload=coverage_audit)
        row = enriched["rows"][0]
        self.assertEqual(row["pipeline_stage"], "local_recall")
        self.assertEqual(row["root_cause_class"], "catalog_gap")
        self.assertEqual(row["root_cause_code"], "missing_family")
        self.assertEqual(row["catalog_audit_diagnosis"], "catalog_missing_family")

    def test_coverage_audit_enrichment_marks_retrieval_when_compatible_candidates_exist(self):
        diagnostics = build_match_diagnostics_payload(
            [
                {
                    "run_row_number": 9,
                    "query_text": "Патч-панель 24 порта",
                    "row_type": "item",
                    "entity_type": "patch_panel",
                    "query_family": "patch_panel",
                    "resolution_source": "unresolved",
                    "compatibility_status": "unresolved_no_compatible_candidates",
                    "incompatibility_reason": "no_compatible_candidates",
                    "stage_of_failure": "local_recall",
                    "reason_code": "no_compatible_candidates",
                    "reason_class": "matcher_retrieval_or_ranking",
                    "pipeline_counts": {},
                    "candidate_snapshots": {},
                    "gemini": {"attempted": False},
                    "trace_steps": [],
                }
            ],
            run_id="run-1",
        )
        coverage_audit = {
            "rows": [
                {
                    "run_row_number": 9,
                    "diagnosis": "catalog_has_compatible_candidates",
                    "same_family_candidates_count": 4,
                    "compatible_candidates_count": 2,
                    "candidate_examples": [{"name": "Патч-панель 24 порта", "article": "PP-24"}],
                }
            ]
        }

        enriched = enrich_match_diagnostics_payload(diagnostics, coverage_audit_payload=coverage_audit)
        row = enriched["rows"][0]
        self.assertEqual(row["pipeline_stage"], "local_recall")
        self.assertEqual(row["root_cause_class"], "matcher_retrieval_or_ranking")
        self.assertEqual(row["coverage_scope"], "audited_family")
        self.assertEqual(row["catalog_audit_diagnosis"], "catalog_has_compatible_candidates")

    def test_reconstructed_unresolved_without_reason_defaults_to_no_compatible_candidates(self):
        df = pd.DataFrame(
            {
                "Наименование оборудования, материалов и кабелей": ["Шкафы телекоммуникационные"],
                "Найденная номенклатура": ["Позиция отсутствует"],
                "Источник решения": ["unresolved"],
                "Совместимость решения": ["unresolved_no_compatible_candidates"],
                "Причина несовместимости": [""],
                "Gemini shortlist": [0],
                "Gemini visible candidates": [0],
                "Gemini truncated": [0],
            }
        )

        payload = reconstruct_match_diagnostics(df, run_id="run-1")
        row = payload["rows"][0]
        self.assertEqual(row["pipeline_stage"], "local_recall")
        self.assertEqual(row["pipeline_reason_code"], "no_compatible_candidates")

    def test_coverage_audit_reclassifies_gemini_rejection_with_no_compatible_specs(self):
        diagnostics = build_match_diagnostics_payload(
            [
                {
                    "run_row_number": 15,
                    "query_text": "Кабель IEC C19-C20",
                    "row_type": "item",
                    "entity_type": "iec_power_cable",
                    "query_family": "iec_power_cable",
                    "resolution_source": "unresolved",
                    "compatibility_status": "rejected_incompatible_gemini",
                    "incompatibility_reason": "connector_mismatch",
                    "stage_of_failure": "gemini_selection",
                    "reason_code": "connector_mismatch",
                    "reason_class": "gemini_or_decision_policy",
                    "pipeline_counts": {"same_family_count": 33, "compatible_count": 0},
                    "candidate_snapshots": {},
                    "gemini": {"attempted": True, "shortlist_count": 3},
                    "trace_steps": [],
                }
            ],
            run_id="run-1",
        )
        coverage_audit = {
            "rows": [
                {
                    "run_row_number": 15,
                    "diagnosis": "catalog_has_family_but_no_compatible_specs",
                    "gap_reason_code": "connector_mismatch",
                    "same_family_candidates_count": 33,
                    "compatible_candidates_count": 0,
                    "candidate_examples": [],
                }
            ]
        }

        enriched = enrich_match_diagnostics_payload(diagnostics, coverage_audit_payload=coverage_audit)
        row = enriched["rows"][0]
        self.assertEqual(row["pipeline_stage"], "gemini_selection")
        self.assertEqual(row["root_cause_class"], "catalog_gap")
        self.assertEqual(row["root_cause_code"], "connector_mismatch")
        self.assertEqual(row["catalog_audit_diagnosis"], "catalog_has_family_but_no_compatible_specs")

    def test_non_target_family_is_marked_as_not_audited(self):
        diagnostics = build_match_diagnostics_payload(
            [
                {
                    "run_row_number": 3,
                    "query_text": "Шкафы телекоммуникационные",
                    "query_family": "rack",
                    "resolution_source": "unresolved",
                    "compatibility_status": "unresolved_no_compatible_candidates",
                    "stage_of_failure": "local_recall",
                    "reason_code": "no_compatible_candidates",
                    "pipeline_counts": {},
                    "candidate_snapshots": {},
                    "gemini": {"attempted": False},
                    "trace_steps": [],
                }
            ],
            run_id="run-1",
        )
        coverage_audit = {
            "rows": [
                {
                    "run_row_number": 3,
                    "diagnosis": "non_target_family",
                    "same_family_candidates_count": 0,
                    "compatible_candidates_count": 0,
                }
            ]
        }

        enriched = enrich_match_diagnostics_payload(diagnostics, coverage_audit_payload=coverage_audit)
        row = enriched["rows"][0]
        self.assertEqual(row["coverage_scope"], "non_target_family")
        self.assertEqual(row["root_cause_class"], "not_audited_family")
        self.assertEqual(row["root_cause_code"], "non_target_family")
        self.assertEqual(row["catalog_gap_reason_code"], "")

    def test_prepare_tables_return_expected_columns(self):
        payload = build_match_diagnostics_payload(
            [
                {
                    "run_row_number": 2,
                    "query_text": "Патч-корд",
                    "row_type": "item",
                    "entity_type": "patch_cord",
                    "query_family": "patch_cord",
                    "resolution_source": "local_tree+gemini",
                    "resolver_name": "local_tree+gemini",
                    "resolver_confidence": 0.87,
                    "family_confidence": 0.78,
                    "article_validation_status": "validated",
                    "gemini_route_used": True,
                    "gemini_validation_used": False,
                    "secondary_filter_rule_set": ["patch_category_preferred"],
                    "compatibility_status": "compatible",
                    "incompatibility_reason": "",
                    "stage_of_failure": "resolved",
                    "reason_code": "resolved",
                    "reason_class": "resolved",
                    "pipeline_counts": {
                        "local_pool_count": 8,
                        "scored_count": 4,
                        "same_family_count": 4,
                        "compatible_count": 2,
                        "secondary_filter_before_count": 6,
                        "secondary_filter_after_count": 2,
                    },
                    "candidate_snapshots": {
                        "display_examples": [{"name": "Патч-корд RJ45", "article": "PC-1"}],
                    },
                    "gemini": {"attempted": True, "shortlist_count": 4},
                    "trace_steps": [],
                }
            ],
            run_id="run-1",
        )

        detail = prepare_match_diagnostics_table(payload)
        stages = prepare_match_diagnostics_stage_table(payload)
        root_causes = prepare_match_diagnostics_root_cause_table(payload)
        reasons = prepare_match_diagnostics_reason_table(payload)
        resolvers = prepare_match_diagnostics_resolver_table(payload)
        self.assertIn("Pipeline stage", detail.columns)
        self.assertIn("Resolver", detail.columns)
        self.assertIn("Secondary filter rules", detail.columns)
        self.assertIn("Root cause code", detail.columns)
        self.assertIn("Coverage scope", detail.columns)
        self.assertIn("Pipeline stage", stages.columns)
        self.assertIn("Root cause class", root_causes.columns)
        self.assertIn("Root cause code", reasons.columns)
        self.assertIn("Resolver", resolvers.columns)

    def test_apply_match_diagnostics_to_result_dataframe_uses_enriched_root_cause_fields(self):
        df = pd.DataFrame(
            {
                "Наименование оборудования, материалов и кабелей": ["Оптический кросс"],
                "Этап отказа": ["local_recall"],
                "Код причины": ["no_compatible_candidates"],
                "Класс причины": ["matcher_retrieval_or_ranking"],
            }
        )
        diagnostics = build_match_diagnostics_payload(
            [
                {
                    "run_row_number": 2,
                    "query_text": "Оптический кросс",
                    "query_family": "optical_cross",
                    "resolver_name": "candidate_tiebreaker_gemini",
                    "resolver_confidence": 0.54,
                    "family_confidence": 0.66,
                    "article_validation_status": "rejected",
                    "gemini_route_used": True,
                    "gemini_validation_used": True,
                    "secondary_filter_rule_set": ["optical_cross_ports_required"],
                    "stage_of_failure": "local_recall",
                    "reason_code": "no_compatible_candidates",
                    "reason_class": "matcher_retrieval_or_ranking",
                    "pipeline_counts": {"same_family_count": 0, "compatible_count": 0},
                    "candidate_snapshots": {},
                    "gemini": {"attempted": False},
                    "trace_steps": [],
                }
            ],
            run_id="run-1",
        )
        coverage_audit = {
            "rows": [
                {
                    "run_row_number": 2,
                    "diagnosis": "catalog_missing_family",
                    "gap_reason_code": "missing_family",
                    "same_family_candidates_count": 0,
                    "compatible_candidates_count": 0,
                }
            ]
        }
        enriched = enrich_match_diagnostics_payload(diagnostics, coverage_audit_payload=coverage_audit)

        updated = apply_match_diagnostics_to_result_dataframe(df, enriched)

        self.assertEqual(updated.at[0, "Этап отказа"], "local_recall")
        self.assertEqual(updated.at[0, "Код причины"], "missing_family")
        self.assertEqual(updated.at[0, "Класс причины"], "catalog_gap")
        self.assertEqual(updated.at[0, "Резолвер"], "candidate_tiebreaker_gemini")
        self.assertEqual(updated.at[0, "Статус article validation"], "rejected")
        self.assertEqual(updated.at[0, "Gemini route"], True)
        self.assertEqual(updated.at[0, "Gemini validation"], True)

    def test_apply_match_diagnostics_summary_to_stats_uses_enriched_summary(self):
        payload = {
            "summary": {
                "pipeline_stage_counts": {"local_recall": 3, "resolved": 1},
                "root_cause_class_counts": {"catalog_gap": 3, "resolved": 1},
                "root_cause_code_counts": {"missing_family": 2, "category_mismatch": 1, "resolved": 1},
            }
        }

        updated = apply_match_diagnostics_summary_to_stats({"total": 4}, payload)

        self.assertEqual(updated["diagnostic_stage_counts"]["local_recall"], 3)
        self.assertEqual(updated["diagnostic_reason_class_counts"]["catalog_gap"], 3)
        self.assertEqual(updated["diagnostic_reason_code_counts"]["missing_family"], 2)


if __name__ == "__main__":
    unittest.main()
