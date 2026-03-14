import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from catalog_coverage_audit import (
    build_catalog_coverage_audit,
    is_catalog_coverage_audit_fresh,
    prepare_catalog_coverage_audit_table,
)
from catalog_schema import CANONICAL_ARTICLE_COLUMN, CANONICAL_NAME_COLUMN


RESULT_QUERY_COLUMN = "Наименование оборудования, материалов и кабелей"


def _write_catalog_csv(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(path, sep=";", index=False, encoding="utf-8")


def _build_result_df(query_text: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                RESULT_QUERY_COLUMN: query_text,
                "Источник решения": "unresolved",
                "Совместимость решения": "unresolved_no_compatible_candidates",
            }
        ]
    )


class CatalogCoverageAuditTests(unittest.TestCase):
    def _first_row(self, payload: dict) -> dict:
        rows = payload.get("rows", [])
        self.assertTrue(rows)
        return rows[0]

    def test_patch_panel_audit_detects_compatible_candidates_in_merged_catalog(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Патч-панель 1U категории 6 UTP 24 порта",
                        CANONICAL_ARTICLE_COLUMN: "PP-24-CAT6",
                        "Название класса": "Патч-панели",
                        "Тип изделия": "Патч-панель",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Панель коммутационная 24 порта категория 6"),
                run_id="run-1",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertEqual(row["diagnosis"], "catalog_has_compatible_candidates")
            self.assertGreaterEqual(row["compatible_candidates_count"], 1)

    def test_optical_cross_audit_detects_missing_family(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Патч-панель 1U категории 6 UTP 24 порта",
                        CANONICAL_ARTICLE_COLUMN: "PP-24-CAT6",
                        "Название класса": "Патч-панели",
                        "Тип изделия": "Патч-панель",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Оптический кросс на 48 волокон 1U"),
                run_id="run-2",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertEqual(row["diagnosis"], "catalog_missing_family")
            self.assertEqual(row["same_family_candidates_count"], 0)

    def test_keystone_group_can_report_family_without_compatible_specs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Модуль Keystone RJ45 категория 5e UTP",
                        CANONICAL_ARTICLE_COLUMN: "KEY-5E-UTP",
                        "Название класса": "Модули RJ45",
                        "Тип изделия": "Keystone модуль",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Розетка RJ45 категория 6a FTP"),
                run_id="run-3",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertEqual(row["diagnosis"], "catalog_has_family_but_no_compatible_specs")
            self.assertGreaterEqual(row["same_family_candidates_count"], 1)
            self.assertEqual(row["compatible_candidates_count"], 0)

    def test_ats_audit_does_not_report_false_compatible_candidates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "АВР для генератора 32А",
                        CANONICAL_ARTICLE_COLUMN: "AVR-32",
                        "Название класса": "АВР",
                        "Тип изделия": "Автоматический ввод резерва",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Статический переключатель ATS/STS 32A"),
                run_id="run-4",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertIn(
                row["diagnosis"],
                {"catalog_missing_family", "catalog_has_family_but_no_compatible_specs"},
            )
            self.assertEqual(row["compatible_candidates_count"], 0)

    def test_search_catalog_uses_precomputed_fields_when_available(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "search_catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "X",
                        CANONICAL_ARTICLE_COLUMN: "PP-PRE",
                        "Название класса": "",
                        "Тип изделия": "",
                        "Тип исполнения кабельного изделия": "",
                        "search_branch_path": "телеком > коммутация > патч панели",
                        "search_normalized_name": "патч панель 24 порта категория 6",
                        "search_entity_type": "patch_panel",
                        "search_item_markers_json": json.dumps({"category": "cat6"}, ensure_ascii=False),
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Панель коммутационная 24 порта категория 6"),
                run_id="run-5",
                catalog_source_path=catalog_path,
                catalog_source_kind="search",
            )

            row = self._first_row(payload)
            self.assertEqual(row["diagnosis"], "catalog_has_compatible_candidates")
            self.assertEqual(row["compatible_candidates_count"], 1)

    def test_coverage_audit_table_and_freshness_work_with_persisted_payload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Патч-панель 1U категории 6 UTP 24 порта",
                        CANONICAL_ARTICLE_COLUMN: "PP-24-CAT6",
                        "Название класса": "Патч-панели",
                        "Тип изделия": "Патч-панель",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Панель коммутационная 24 порта категория 6"),
                run_id="run-6",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            self.assertTrue(
                is_catalog_coverage_audit_fresh(
                    payload,
                    run_id="run-6",
                    catalog_source_path=catalog_path,
                    catalog_source_kind="merged",
                )
            )
            detail_table = prepare_catalog_coverage_audit_table(payload)
            self.assertFalse(detail_table.empty)
            self.assertIn("Примеры кандидатов", detail_table.columns)


if __name__ == "__main__":
    unittest.main()
