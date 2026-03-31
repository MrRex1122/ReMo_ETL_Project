import tempfile
import unittest
from pathlib import Path

import pandas as pd

from catalog_search import SEARCH_BASE_COLUMNS, SEARCH_DERIVED_COLUMNS
from profile_other_catalog import analyze_other_catalog


class ProfileOtherCatalogTests(unittest.TestCase):
    def test_analyze_other_catalog_writes_summary_and_sample(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_path = root / "search_catalog_fixture.csv"
            output_dir = root / "out"

            rows = [
                {
                    "Наименование": "Монтажный комплект нестандартный",
                    "Артикул": "KIT-1",
                    "Цена розничная": 100.0,
                    "Название класса": "Прочие изделия",
                    "Код класса": "CLS-OTHER",
                    "Тип изделия": "Комплект",
                    "Тип исполнения кабельного изделия": "",
                    "Производитель": "ReMo",
                    "search_branch_path": "прочее",
                    "search_branch_leaf": "прочее",
                    "search_normalized_name": "монтажный комплект нестандартный",
                    "search_tokens_json": '["монтажный", "комплект", "нестандартный"]',
                    "search_entity_type": "other",
                    "search_effective_family": "other",
                    "search_effective_entity_type": "other",
                    "search_item_markers_json": "{}",
                },
                {
                    "Наименование": "PDU Zero U 16A",
                    "Артикул": "PDU-1",
                    "Цена розничная": 1200.0,
                    "Название класса": "Шкафы телекоммуникационные",
                    "Код класса": "CLS-PDU",
                    "Тип изделия": "Блок розеток",
                    "Тип исполнения кабельного изделия": "",
                    "Производитель": "ReMo",
                    "search_branch_path": "телеком > питание > pdu",
                    "search_branch_leaf": "pdu",
                    "search_normalized_name": "pdu zero u 16a",
                    "search_tokens_json": '["pdu", "zero", "16a"]',
                    "search_entity_type": "pdu_basic",
                    "search_effective_family": "pdu",
                    "search_effective_entity_type": "pdu",
                    "search_item_markers_json": "{}",
                },
            ]

            frame = pd.DataFrame(rows, columns=SEARCH_BASE_COLUMNS + SEARCH_DERIVED_COLUMNS)
            frame.to_csv(source_path, sep=";", encoding="utf-8", index=False)

            result_dir = analyze_other_catalog(source_path, output_dir=output_dir, sample_size=10, seed=7, chunksize=10)

            self.assertEqual(result_dir, output_dir)
            self.assertTrue((output_dir / "other_sample_random.csv").exists())
            self.assertTrue((output_dir / "other_branch_summary.csv").exists())
            self.assertTrue((output_dir / "other_class_summary.csv").exists())
            self.assertTrue((output_dir / "summary.txt").exists())

            sample = pd.read_csv(output_dir / "other_sample_random.csv", sep=";", encoding="utf-8")
            self.assertEqual(len(sample), 1)
            self.assertEqual(sample.loc[0, "Артикул"], "KIT-1")

            summary_text = (output_dir / "summary.txt").read_text(encoding="utf-8")
            self.assertIn("total_rows=2", summary_text)
            self.assertIn("other_rows=1", summary_text)


if __name__ == "__main__":
    unittest.main()
