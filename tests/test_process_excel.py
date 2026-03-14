import os
import tempfile
import unittest

import pandas as pd

from matcher import MISSING_POSITION_TEXT, ReMoMatcher


class DummyMatcher(ReMoMatcher):
    """Test double that bypasses Gemini and returns deterministic matches."""

    def __init__(self):
        # Skip parent initialization (API, catalog, cache).
        pass

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


if __name__ == "__main__":
    unittest.main()
