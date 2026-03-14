import unittest

import pandas as pd

from match_diagnostics import (
    build_match_diagnostics_payload,
    enrich_match_diagnostics_payload,
    is_match_diagnostics_fresh,
    prepare_match_diagnostics_reason_table,
    prepare_match_diagnostics_stage_table,
    prepare_match_diagnostics_table,
    reconstruct_match_diagnostics,
)


class MatchDiagnosticsTests(unittest.TestCase):
    def test_runtime_payload_builds_summary(self):
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
        self.assertEqual(payload["summary"]["stage_counts"]["compatibility_filter"], 1)
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
        self.assertEqual(row["stage_of_failure"], "query_input")
        self.assertEqual(row["reason_code"], "section_row_detected")

    def test_coverage_audit_enrichment_promotes_catalog_gap(self):
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
                    "same_family_candidates_count": 0,
                    "compatible_candidates_count": 0,
                    "candidate_examples": [],
                }
            ]
        }

        enriched = enrich_match_diagnostics_payload(diagnostics, coverage_audit_payload=coverage_audit)
        row = enriched["rows"][0]
        self.assertEqual(row["stage_of_failure"], "catalog_gap")
        self.assertEqual(row["reason_class"], "catalog_gap")
        self.assertEqual(row["catalog_audit_diagnosis"], "catalog_missing_family")

    def test_coverage_audit_enrichment_keeps_matcher_class_when_compatible_candidates_exist(self):
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
        self.assertEqual(row["reason_class"], "matcher_retrieval_or_ranking")
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
        self.assertEqual(row["stage_of_failure"], "local_recall")
        self.assertEqual(row["reason_code"], "no_compatible_candidates")

    def test_coverage_audit_reclassifies_gemini_rejection_without_compatible_candidates_as_catalog_gap(self):
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
                    "same_family_candidates_count": 33,
                    "compatible_candidates_count": 0,
                    "candidate_examples": [],
                }
            ]
        }

        enriched = enrich_match_diagnostics_payload(diagnostics, coverage_audit_payload=coverage_audit)
        row = enriched["rows"][0]
        self.assertEqual(row["stage_of_failure"], "catalog_gap")
        self.assertEqual(row["reason_class"], "catalog_gap")
        self.assertEqual(row["catalog_audit_diagnosis"], "catalog_has_family_but_no_compatible_specs")

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
                    "compatibility_status": "compatible",
                    "incompatibility_reason": "",
                    "stage_of_failure": "resolved",
                    "reason_code": "resolved",
                    "reason_class": "resolved",
                    "pipeline_counts": {"local_pool_count": 8, "scored_count": 4, "same_family_count": 4, "compatible_count": 2},
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
        reasons = prepare_match_diagnostics_reason_table(payload)
        self.assertIn("Этап отказа", detail.columns)
        self.assertIn("Код причины", detail.columns)
        self.assertIn("Этап отказа", stages.columns)
        self.assertIn("Код причины", reasons.columns)


if __name__ == "__main__":
    unittest.main()
