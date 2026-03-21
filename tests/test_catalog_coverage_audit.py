import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from catalog_coverage_audit import (
    build_catalog_coverage_audit,
    is_catalog_coverage_audit_fresh,
    prepare_catalog_coverage_audit_table,
    prepare_catalog_gap_reason_table,
)
from catalog_search import DUCKDB_AVAILABLE, build_search_catalog_from_merged, get_search_catalog_duckdb_path
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

    def test_patch_cord_is_included_as_target_family(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Патч-корд медный категория 6 1м",
                        CANONICAL_ARTICLE_COLUMN: "PC-1M-CAT6",
                        "Название класса": "Патч-корды",
                        "Тип изделия": "Патч-корд",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Медный патч-корд категории 6 (1м)"),
                run_id="run-patch-cord",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertEqual(row["query_family"], "patch_cord")
            self.assertEqual(row["query_family_group"], "patch_cord")
            self.assertEqual(row["diagnosis"], "catalog_has_compatible_candidates")

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
            self.assertEqual(row["gap_reason_code"], "missing_family")

    def test_non_target_rows_do_not_get_gap_reason_and_are_hidden_from_detail_table(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Шкаф настенный 19 дюймов",
                        CANONICAL_ARTICLE_COLUMN: "RACK-1",
                        "Название класса": "Шкафы телекоммуникационные",
                        "Тип изделия": "Шкаф",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Шкафы телекоммуникационные"),
                run_id="run-non-target",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertEqual(row["diagnosis"], "non_target_family")
            self.assertEqual(row["gap_reason_code"], "")

            detail_table = prepare_catalog_coverage_audit_table(payload)
            self.assertTrue(detail_table.empty)

    def test_runtime_diagnostics_family_is_used_for_audit_scope(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Консоль универсальная осн. 200 мм",
                        CANONICAL_ARTICLE_COLUMN: "BBN5020",
                        "Название класса": "Шкафные аксессуары",
                        "Тип изделия": "Консоль",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            diagnostics_payload = {
                "rows": [
                    {
                        "run_row_number": 2,
                        "row_type": "item",
                        "entity_type": "rack_accessory_strict",
                        "query_family": "rack_accessory_strict",
                    }
                ]
            }

            payload = build_catalog_coverage_audit(
                _build_result_df("Консоль универсальная осн. 200 мм, артикул BBN5020"),
                run_id="run-rack-runtime-family",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
                diagnostics_payload=diagnostics_payload,
            )

            row = self._first_row(payload)
            self.assertEqual(row["query_family"], "rack_accessory_strict")
            self.assertEqual(row["query_family_group"], "rack_accessories")
            self.assertNotEqual(row["diagnosis"], "non_target_family")
            self.assertEqual(payload["summary"]["rows_analyzed"], 1)

    def test_iec_power_cable_is_included_as_target_family(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Кабель электрический соединительный IEC320 C19-C20 1.8м",
                        CANONICAL_ARTICLE_COLUMN: "IEC-C19-C20-18",
                        "Название класса": "Кабели",
                        "Тип изделия": "Кабель",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df(
                    "Кабель электрический соединительный 230VAC 16A IEC320 C19-C20, "
                    "с механизмом фиксации в розетках PDU (1,8м)"
                ),
                run_id="run-iec",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertEqual(row["query_family"], "iec_power_cable")
            self.assertEqual(row["query_family_group"], "iec_power_cable")
            self.assertEqual(row["diagnosis"], "catalog_has_compatible_candidates")

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
            self.assertEqual(row["gap_reason_code"], "category_mismatch")

    def test_catalog_gap_reason_uses_multiple_spec_mismatches_when_top_reasons_tie(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Патч-панель 1U категории 5E UTP 24 порта",
                        CANONICAL_ARTICLE_COLUMN: "PP-C5E",
                        "Название класса": "Патч-панели",
                        "Тип изделия": "Патч-панель",
                        "Тип исполнения кабельного изделия": "",
                    },
                    {
                        CANONICAL_NAME_COLUMN: "Патч-панель 1U категории 6 UTP 48 портов",
                        CANONICAL_ARTICLE_COLUMN: "PP-48",
                        "Название класса": "Патч-панели",
                        "Тип изделия": "Патч-панель",
                        "Тип исполнения кабельного изделия": "",
                    },
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Панель коммутационная неэкранированная 24 порта, категория 6"),
                run_id="run-multi-gap",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertEqual(row["diagnosis"], "catalog_has_family_but_no_compatible_specs")
            self.assertEqual(row["gap_reason_code"], "multiple_spec_mismatches")
            self.assertTrue(row["top_gap_reasons"])

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
                        CANONICAL_NAME_COLUMN: "Патч-панель 24 порта cat6",
                        CANONICAL_ARTICLE_COLUMN: "PP-PRE",
                        "???????? ??????": "patch panels",
                        "??? ???????": "patch panel",
                        "??? ?????????? ?????????? ???????": "",
                        "search_branch_path": "телеком > коммутация > патч панели",
                        "search_normalized_name": "патч панель 24 порта категория 6",
                        "search_entity_type": "patch_panel",
                        "search_item_markers_json": json.dumps(
                            {"category": "cat6", "port_count": "24"},
                            ensure_ascii=False,
                        ),
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

    def test_search_catalog_recomputes_family_when_precomputed_type_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "search_catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: (
                            "Ð˜ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº Ð±ÐµÑÐ¿ÐµÑ€ÐµÐ±Ð¾Ð¹Ð½Ð¾Ð³Ð¾ Ð¿Ð¸Ñ‚Ð°Ð½Ð¸Ñ Online 2000Ð’Ð, "
                            "Ð²Ñ…Ð¾Ð´ IEC-320-C20, Ð²Ñ‹Ñ…Ð¾Ð´ IEC-320-C13 (3 ÑˆÑ‚.), IEC-320-C19 (1 ÑˆÑ‚.)"
                        ),
                        CANONICAL_ARTICLE_COLUMN: "UPS-IEC",
                        "ÐÐ°Ð·Ð²Ð°Ð½Ð¸Ðµ ÐºÐ»Ð°ÑÑÐ°": "Ð˜Ð‘ÐŸ",
                        "Ð¢Ð¸Ð¿ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ": "Ð˜ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº Ð±ÐµÑÐ¿ÐµÑ€ÐµÐ±Ð¾Ð¹Ð½Ð¾Ð³Ð¾ Ð¿Ð¸Ñ‚Ð°Ð½Ð¸Ñ",
                        "Ð¢Ð¸Ð¿ Ð¸ÑÐ¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ ÐºÐ°Ð±ÐµÐ»ÑŒÐ½Ð¾Ð³Ð¾ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ": "",
                        "search_branch_path": "Ñ‚ÐµÐ»ÐµÐºÐ¾Ð¼ > Ð¿Ð¸Ñ‚Ð°Ð½Ð¸Ðµ > pdu",
                        "search_normalized_name": "Ð¸Ð±Ð¿ iec c20 c13 c19",
                        "search_entity_type": "iec_power_cable",
                        "search_item_markers_json": json.dumps({"connector_pair": "c19-c20"}, ensure_ascii=False),
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("power cord IEC320 C19-C20 1.8m"),
                run_id="run-search-stale-iec",
                catalog_source_path=catalog_path,
                catalog_source_kind="search",
            )

            row = self._first_row(payload)
            self.assertIn(row["diagnosis"], {"catalog_missing_family", "catalog_has_family_but_no_compatible_specs"})
            self.assertEqual(row["compatible_candidates_count"], 0)

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
            stale_payload = dict(payload)
            stale_payload["audit_version"] = 0
            self.assertFalse(
                is_catalog_coverage_audit_fresh(
                    stale_payload,
                    run_id="run-6",
                    catalog_source_path=catalog_path,
                    catalog_source_kind="merged",
                )
            )
            detail_table = prepare_catalog_coverage_audit_table(payload)
            gap_reason_table = prepare_catalog_gap_reason_table(payload)
            self.assertFalse(detail_table.empty)
            self.assertIn("Gap reason", detail_table.columns)
            self.assertIn("Top mismatch reasons", detail_table.columns)
            self.assertIn("Примеры кандидатов", detail_table.columns)
            self.assertIn("Gap reason", gap_reason_table.columns if not gap_reason_table.empty else ["Gap reason"])

    def test_airflow_audit_does_not_count_generic_blank_panels_as_same_family(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Панель-заглушка 19 1U",
                        CANONICAL_ARTICLE_COLUMN: "BLANK-1U",
                        "Название класса": "Шкафные аксессуары",
                        "Тип изделия": "Панель-заглушка",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Заглушка для управления потоком воздуха"),
                run_id="run-airflow",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertEqual(row["query_family"], "airflow_blanking_panel")
            self.assertEqual(row["diagnosis"], "catalog_missing_family")
            self.assertEqual(row["same_family_candidates_count"], 0)

    def test_iec_audit_does_not_count_ups_with_iec_ports_as_compatible_cable(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: (
                            "Ð˜ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº Ð±ÐµÑÐ¿ÐµÑ€ÐµÐ±Ð¾Ð¹Ð½Ð¾Ð³Ð¾ Ð¿Ð¸Ñ‚Ð°Ð½Ð¸Ñ Online 2000Ð’Ð, "
                            "Ð²Ñ…Ð¾Ð´ IEC-320-C20, Ð²Ñ‹Ñ…Ð¾Ð´ IEC-320-C13 (3 ÑˆÑ‚.), IEC-320-C19 (1 ÑˆÑ‚.)"
                        ),
                        CANONICAL_ARTICLE_COLUMN: "UPS-IEC",
                        "ÐÐ°Ð·Ð²Ð°Ð½Ð¸Ðµ ÐºÐ»Ð°ÑÑÐ°": "Ð˜Ð‘ÐŸ",
                        "Ð¢Ð¸Ð¿ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ": "Ð˜ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº Ð±ÐµÑÐ¿ÐµÑ€ÐµÐ±Ð¾Ð¹Ð½Ð¾Ð³Ð¾ Ð¿Ð¸Ñ‚Ð°Ð½Ð¸Ñ",
                        "Ð¢Ð¸Ð¿ Ð¸ÑÐ¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ ÐºÐ°Ð±ÐµÐ»ÑŒÐ½Ð¾Ð³Ð¾ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("power cord IEC320 C19-C20 1.8m"),
                run_id="run-iec-noise",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertIn(row["diagnosis"], {"catalog_missing_family", "catalog_has_family_but_no_compatible_specs"})
            self.assertEqual(row["compatible_candidates_count"], 0)

    def test_ats_audit_does_not_count_sts_connector_suffix_as_same_family(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Connector HIP-GERM-MONO-8-2pin-STS",
                        CANONICAL_ARTICLE_COLUMN: "STS-CONN",
                        "ÐÐ°Ð·Ð²Ð°Ð½Ð¸Ðµ ÐºÐ»Ð°ÑÑÐ°": "ÐšÐ¾Ð½Ð½ÐµÐºÑ‚Ð¾Ñ€Ñ‹",
                        "Ð¢Ð¸Ð¿ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ": "ÐšÐ¾Ð½Ð½ÐµÐºÑ‚Ð¾Ñ€",
                        "Ð¢Ð¸Ð¿ Ð¸ÑÐ¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ ÐºÐ°Ð±ÐµÐ»ÑŒÐ½Ð¾Ð³Ð¾ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("static transfer switch ATS/STS 32A"),
                run_id="run-ats-noise",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertEqual(row["same_family_candidates_count"], 0)
            self.assertEqual(row["compatible_candidates_count"], 0)

    def test_patch_panel_audit_does_not_count_non_telecom_commutation_panels_as_compatible(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Панель коммутационная Ridan WD на 8 каналов и 14 приводов",
                        CANONICAL_ARTICLE_COLUMN: "RIDAN-PANEL",
                        "Название класса": "Панели управления",
                        "Тип изделия": "Панель коммутационная",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Панель коммутационная неэкранированной 24 порта, блочная, категория 6"),
                run_id="run-patch-panel-noise",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertIn(row["diagnosis"], {"catalog_missing_family", "catalog_has_family_but_no_compatible_specs"})
            self.assertEqual(row["compatible_candidates_count"], 0)

    def test_search_catalog_keeps_precomputed_family_when_recomputed_family_is_broad(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "search_catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Консоль универсальная осн. 200 мм",
                        CANONICAL_ARTICLE_COLUMN: "BBN5020",
                        "Название класса": "Кабельные аксессуары",
                        "Тип изделия": "Консоль",
                        "Тип исполнения кабельного изделия": "",
                        "search_branch_path": "электрика > аксессуары > консоли",
                        "search_normalized_name": "консоль универсальная осн 200 мм",
                        "search_entity_type": "other",
                        "search_item_markers_json": json.dumps({}, ensure_ascii=False),
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Консоль универсальная осн. 200 мм, артикул BBN5020"),
                run_id="run-search-precomputed-broad",
                catalog_source_path=catalog_path,
                catalog_source_kind="search",
            )

            row = self._first_row(payload)
            self.assertEqual(row["diagnosis"], "catalog_missing_family")
            self.assertEqual(row["same_family_candidates_count"], 0)

    def test_keystone_audit_does_not_count_adapters_as_compatible_modules(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Avanti Адаптер для Keystone 1 модуль",
                        CANONICAL_ARTICLE_COLUMN: "KEY-ADAPTER",
                        "Название класса": "Адаптеры",
                        "Тип изделия": "Адаптер для Keystone",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Модуль Keystone, экранированный, категория 6a"),
                run_id="run-keystone-adapter",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertEqual(row["compatible_candidates_count"], 0)
            self.assertEqual(row["diagnosis"], "catalog_has_family_but_no_compatible_specs")

    def test_rj45_outlet_audit_does_not_count_floor_box_faceplates_as_compatible_assembly(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Накладка для информационных функций типа Keystone",
                        CANONICAL_ARTICLE_COLUMN: "RJ45-COVER",
                        "Название класса": "Накладки",
                        "Тип изделия": "Накладка для Keystone",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Конструктив сетевой розетки для одного порта RJ-45 в лючок напольный в сборе"),
                run_id="run-rj45-floorbox-assembly",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertEqual(row["compatible_candidates_count"], 0)
            self.assertEqual(row["diagnosis"], "catalog_has_family_but_no_compatible_specs")

    def test_rj45_outlet_audit_does_not_count_single_port_outlet_as_two_port_cable_channel_assembly(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            catalog_path = Path(tmp_dir) / "catalog.csv"
            _write_catalog_csv(
                catalog_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Розетка компьютерная 1-местная RJ-45",
                        CANONICAL_ARTICLE_COLUMN: "RJ45-1PORT",
                        "Название класса": "Розетки компьютерные",
                        "Тип изделия": "Розетка компьютерная",
                        "Тип исполнения кабельного изделия": "",
                    }
                ],
            )

            payload = build_catalog_coverage_audit(
                _build_result_df("Конструктив сетевой розетки для двух портов RJ-45 в кабель-канал, в сборе"),
                run_id="run-rj45-cable-channel-assembly",
                catalog_source_path=catalog_path,
                catalog_source_kind="merged",
            )

            row = self._first_row(payload)
            self.assertEqual(row["compatible_candidates_count"], 0)
            self.assertEqual(row["diagnosis"], "catalog_has_family_but_no_compatible_specs")

    def test_search_duckdb_catalog_is_supported_by_audit(self):
        if not DUCKDB_AVAILABLE:
            self.skipTest("duckdb package is not installed")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            _write_catalog_csv(
                merged_path,
                [
                    {
                        CANONICAL_NAME_COLUMN: "Патч-панель 1U категории 6 UTP 24 порта",
                        CANONICAL_ARTICLE_COLUMN: "PP-24-CAT6",
                        "Название класса": "Патч-панели",
                        "Код класса": "CLS-1",
                        "Тип изделия": "Патч-панель",
                        "Тип исполнения кабельного изделия": "",
                        "Производитель": "ReMo",
                        "Цена розничная": "1000",
                    }
                ],
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_duckdb_path(root))
            payload = build_catalog_coverage_audit(
                _build_result_df("Панель коммутационная 24 порта категория 6"),
                run_id="run-search-duckdb",
                catalog_source_path=search_path,
                catalog_source_kind="search",
            )

            row = self._first_row(payload)
            self.assertEqual(row["diagnosis"], "catalog_has_compatible_candidates")
            self.assertGreaterEqual(row["compatible_candidates_count"], 1)


if __name__ == "__main__":
    unittest.main()
