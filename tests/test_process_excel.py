import os
import tempfile
import threading
import unittest

import pandas as pd

from matcher import MISSING_POSITION_TEXT, ReMoMatcher


class DummyMatcher(ReMoMatcher):
    """Test double that bypasses Gemini and returns deterministic matches."""

    def __init__(self):
        # Skip parent initialization (API, catalog, cache).
        self._match_context_local = threading.local()
        self.parallel_requests = 1

    def match(self, query: str, use_cache: bool = True):
        if query == "Позиция 1":
            return {
                "found_name": "Номенклатура 1",
                "price": 100.5,
                "article": "ART-100",
                "similarity_score": 0.99,
                "from_cache": False,
                "success": True,
                "error": None,
            }
        return {
            "found_name": MISSING_POSITION_TEXT,
            "price": None,
            "article": None,
            "similarity_score": 0.0,
            "from_cache": False,
            "success": True,
            "error": None,
        }


class ContextAwareDummyMatcher(DummyMatcher):
    def match(self, query: str, use_cache: bool = True):
        context = self._current_match_input_context()
        query_article = context.get("query_article") or None
        article_source = context.get("article_source") or "none"
        return {
            "found_name": f"FOUND::{query}",
            "price": 42.0,
            "article": query_article,
            "similarity_score": 1.0 if query_article else 0.9,
            "from_cache": False,
            "success": True,
            "error": None,
            "reason": "",
            "category_path": None,
            "confidence_level": "high",
            "requires_review": "нет",
            "alternatives": "",
            "resolution_source": "article_exact" if article_source == "column" else (
                "article_extracted_exact" if article_source == "text" else "name_exact"
            ),
            "compatibility_status": "compatible",
            "incompatibility_reason": "",
            "stage_of_failure": "resolved",
            "reason_code": "resolved",
            "reason_class": "resolved",
            "gemini_shortlist_count": 0,
            "gemini_visible_candidates": 0,
            "gemini_truncated_candidates": 0,
        }


class SectionRowDummyMatcher(DummyMatcher):
    def match(self, query: str, use_cache: bool = True):
        if query == "ОБОРУДОВАНИЕ":
            return {
                "found_name": "",
                "price": None,
                "article": None,
                "similarity_score": 0.0,
                "from_cache": False,
                "success": True,
                "error": None,
                "reason": "Строка-раздел, сопоставление не требуется.",
                "category_path": None,
                "confidence_level": "",
                "requires_review": "нет",
                "alternatives": "",
                "resolution_source": "unresolved",
                "compatibility_status": "unresolved_no_compatible_candidates",
                "incompatibility_reason": "section_row_detected",
                "stage_of_failure": "query_input",
                "reason_code": "section_row_detected",
                "reason_class": "section_row_detected",
                "verifier_decision": "reject",
                "verifier_reason": "reject_non_item_row",
                "auto_accept": False,
                "gemini_shortlist_count": 0,
                "gemini_visible_candidates": 0,
                "gemini_truncated_candidates": 0,
            }
        return super().match(query, use_cache=use_cache)


class ProcessExcelExistingColumnsTests(unittest.TestCase):
    def setUp(self):
        self.matcher = DummyMatcher()

    def _run_process(self, df: pd.DataFrame):
        fd, input_path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        output_path = input_path.replace(".xlsx", "_out.xlsx")
        try:
            df.to_excel(input_path, index=False)
            result_df, stats = self.matcher.process_excel(input_path, output_path)
            return result_df, stats
        finally:
            for path in (input_path, output_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_process_excel_does_not_duplicate_existing_result_columns(self):
        df = pd.DataFrame(
            {
                "A": [1, 2, 3, 4],
                "Наименование оборудования, материалов и кабелей": [
                    "Наименование оборудования, материалов и кабелей",
                    "Позиция 1",
                    "",
                    "Позиция 2",
                ],
                "Цена": [10, 20, 30, 40],
                "Найденная номенклатура": ["old1", "old2", "old3", "old4"],
                "Артикул": ["A1", "A2", "A3", "A4"],
            }
        )

        result_df, stats = self._run_process(df)

        for col in ("Цена", "Найденная номенклатура", "Артикул"):
            self.assertEqual(list(result_df.columns).count(col), 1)

        for col in (
            "Совместимость решения",
            "Причина несовместимости",
            "Этап отказа",
            "Код причины",
            "Класс причины",
            "Gemini shortlist",
            "Gemini visible candidates",
            "Gemini truncated",
        ):
            self.assertIn(col, result_df.columns)

        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["found"], 1)
        self.assertEqual(stats["not_found"], 1)
        self.assertEqual(stats["errors"], 0)
        self.assertIn("gemini_rows_total", stats)
        self.assertIn("diagnostic_stage_counts", stats)
        self.assertIn("diagnostic_reason_code_counts", stats)

    def test_process_excel_overwrites_existing_result_cells(self):
        df = pd.DataFrame(
            {
                "A": [1, 2],
                "Наименование оборудования, материалов и кабелей": ["Позиция 1", "Позиция 2"],
                "Цена": [999, 888],
                "Найденная номенклатура": ["OLD_NAME_1", "OLD_NAME_2"],
                "Артикул": ["OLD_1", "OLD_2"],
            }
        )

        result_df, _stats = self._run_process(df)

        self.assertEqual(result_df.loc[0, "Цена"], 100.5)
        self.assertEqual(result_df.loc[0, "Найденная номенклатура"], "Номенклатура 1")
        self.assertEqual(result_df.loc[0, "Артикул"], "ART-100")
        self.assertEqual(result_df.loc[0, "Этап отказа"], "resolved")
        self.assertEqual(result_df.loc[0, "Код причины"], "resolved")

        self.assertTrue(pd.isna(result_df.loc[1, "Цена"]))
        self.assertEqual(result_df.loc[1, "Найденная номенклатура"], MISSING_POSITION_TEXT)
        self.assertTrue(pd.isna(result_df.loc[1, "Артикул"]))
        self.assertIn("Позиция 2", str(result_df.loc[1, "Причина отсутствия"]))
        self.assertIn("не найдена", str(result_df.loc[1, "Причина отсутствия"]).lower())
        self.assertEqual(result_df.loc[1, "Этап отказа"], "local_recall")

    def test_process_excel_can_return_interrupted_partial_result(self):
        df = pd.DataFrame(
            {
                "A": [1, 2],
                "Наименование оборудования, материалов и кабелей": ["Позиция 1", "Позиция 2"],
            }
        )
        cancel_state = {"calls": 0}

        def cancel_requested() -> bool:
            cancel_state["calls"] += 1
            return cancel_state["calls"] > 1

        fd, input_path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        output_path = input_path.replace(".xlsx", "_out.xlsx")
        try:
            df.to_excel(input_path, index=False)
            result_df, stats = self.matcher.process_excel(
                input_path,
                output_path,
                cancel_requested=cancel_requested,
            )
        finally:
            for path in (input_path, output_path):
                if os.path.exists(path):
                    os.unlink(path)

        self.assertTrue(stats.get("_interrupted"))
        self.assertEqual(stats.get("processed"), 1)
        self.assertEqual(result_df.loc[0, "Найденная номенклатура"], "Номенклатура 1")
        self.assertTrue(pd.isna(result_df.loc[1, "Найденная номенклатура"]))

    def test_process_excel_promotes_embedded_header_row_and_detects_article_column(self):
        self.matcher = ContextAwareDummyMatcher()
        df = pd.DataFrame(
            [
                ["№", "Наименование", "Артикул", "Ед. изм"],
                [1, "Кабель силовой", "ART-100", "м"],
            ],
            columns=["Unnamed: 0", "Unnamed: 1", "Unnamed: 2", "Unnamed: 3"],
        )

        result_df, stats = self._run_process(df)

        self.assertEqual(stats["input_query_column"], "Наименование")
        self.assertEqual(stats["input_article_column"], "Артикул")
        self.assertEqual(result_df.loc[0, "Найденная номенклатура"], "FOUND::Кабель силовой")
        self.assertEqual(result_df.loc[0, "Артикул"], "ART-100")
        self.assertEqual(result_df.loc[0, "Источник решения"], "article_exact")

    def test_process_excel_extracts_article_from_text_when_article_column_is_missing(self):
        self.matcher = ContextAwareDummyMatcher()
        df = pd.DataFrame(
            {
                "Наименование": ["Кабель, артикул ART-200"],
            }
        )

        result_df, stats = self._run_process(df)

        self.assertEqual(stats["input_query_column"], "Наименование")
        self.assertEqual(stats["input_article_column"], "")
        self.assertEqual(result_df.loc[0, "Артикул"], "ART-200")
        self.assertEqual(result_df.loc[0, "Источник решения"], "article_extracted_exact")

    def test_process_excel_leaves_section_rows_blank_in_found_name(self):
        self.matcher = SectionRowDummyMatcher()
        df = pd.DataFrame(
            {
                "Наименование оборудования, материалов и кабелей": ["ОБОРУДОВАНИЕ", "Позиция 2"],
            }
        )

        result_df, stats = self._run_process(df)

        self.assertEqual(result_df.loc[0, "Найденная номенклатура"], "")
        self.assertEqual(result_df.loc[0, "Требует проверки"], "нет")
        self.assertEqual(result_df.loc[0, "Код причины"], "section_row_detected")
        self.assertEqual(
            result_df.loc[0, "Причина отсутствия"],
            "Строка-раздел, сопоставление не требуется.",
        )
        self.assertEqual(stats["skipped_non_item"], 1)
        self.assertEqual(stats["found"], 0)
        self.assertEqual(stats["not_found"], 1)


if __name__ == "__main__":
    unittest.main()
