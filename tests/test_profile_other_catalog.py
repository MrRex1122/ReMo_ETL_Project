import tempfile
import unittest
from pathlib import Path

import pandas as pd

from catalog_search import SEARCH_BASE_COLUMNS, SEARCH_DERIVED_COLUMNS
from profile_other_catalog import analyze_other_catalog


class ProfileOtherCatalogTests(unittest.TestCase):
    def test_analyze_other_catalog_writes_summary_and_alignment_outputs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_path = root / "search_catalog_fixture.csv"
            output_dir = root / "out"

            rows = [
                {
                    "ÐÐ°Ð¸Ð¼ÐµÐ½Ð¾Ð²Ð°Ð½Ð¸Ðµ": "ÐœÐ¾Ð½Ñ‚Ð°Ð¶Ð½Ñ‹Ð¹ ÐºÐ¾Ð¼Ð¿Ð»ÐµÐºÑ‚ Ð½ÐµÑÑ‚Ð°Ð½Ð´Ð°Ñ€Ñ‚Ð½Ñ‹Ð¹",
                    "ÐÑ€Ñ‚Ð¸ÐºÑƒÐ»": "KIT-1",
                    "Ð¦ÐµÐ½Ð° Ñ€Ð¾Ð·Ð½Ð¸Ñ‡Ð½Ð°Ñ": 100.0,
                    "ÐÐ°Ð·Ð²Ð°Ð½Ð¸Ðµ ÐºÐ»Ð°ÑÑÐ°": "ÐŸÑ€Ð¾Ñ‡Ð¸Ðµ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ",
                    "ÐšÐ¾Ð´ ÐºÐ»Ð°ÑÑÐ°": "CLS-OTHER",
                    "Ð¢Ð¸Ð¿ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ": "ÐšÐ¾Ð¼Ð¿Ð»ÐµÐºÑ‚",
                    "Ð¢Ð¸Ð¿ Ð¸ÑÐ¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ ÐºÐ°Ð±ÐµÐ»ÑŒÐ½Ð¾Ð³Ð¾ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ": "",
                    "ÐŸÑ€Ð¾Ð¸Ð·Ð²Ð¾Ð´Ð¸Ñ‚ÐµÐ»ÑŒ": "ReMo",
                    "search_branch_path": "Ð¿Ñ€Ð¾Ñ‡ÐµÐµ",
                    "search_branch_leaf": "Ð¿Ñ€Ð¾Ñ‡ÐµÐµ",
                    "search_normalized_name": "Ð¼Ð¾Ð½Ñ‚Ð°Ð¶Ð½Ñ‹Ð¹ ÐºÐ¾Ð¼Ð¿Ð»ÐµÐºÑ‚ Ð½ÐµÑÑ‚Ð°Ð½Ð´Ð°Ñ€Ñ‚Ð½Ñ‹Ð¹",
                    "search_tokens_json": '["Ð¼Ð¾Ð½Ñ‚Ð°Ð¶Ð½Ñ‹Ð¹", "ÐºÐ¾Ð¼Ð¿Ð»ÐµÐºÑ‚", "Ð½ÐµÑÑ‚Ð°Ð½Ð´Ð°Ñ€Ñ‚Ð½Ñ‹Ð¹"]',
                    "search_entity_type": "other",
                    "search_effective_family": "other",
                    "search_effective_entity_type": "other",
                    "search_item_markers_json": "{}",
                }
            ]

            frame = pd.DataFrame(rows, columns=SEARCH_BASE_COLUMNS + SEARCH_DERIVED_COLUMNS)
            frame.to_csv(source_path, sep=";", encoding="utf-8", index=False)

            result_dir = analyze_other_catalog(
                source_path,
                output_dir=output_dir,
                sample_size=10,
                seed=7,
                chunksize=10,
                verbose=False,
            )

            self.assertEqual(result_dir, output_dir)
            self.assertTrue((output_dir / "other_sample_random.csv").exists())
            self.assertTrue((output_dir / "other_branch_summary.csv").exists())
            self.assertTrue((output_dir / "other_class_summary.csv").exists())
            self.assertTrue((output_dir / "branch_family_alignment.csv").exists())
            self.assertTrue((output_dir / "other_branch_alignment.csv").exists())
            self.assertTrue((output_dir / "summary.txt").exists())

            sample = pd.read_csv(output_dir / "other_sample_random.csv", sep=";", encoding="utf-8")
            self.assertEqual(len(sample), 1)

            branch_alignment = pd.read_csv(output_dir / "branch_family_alignment.csv", sep=";", encoding="utf-8")
            self.assertEqual(len(branch_alignment), 1)
            self.assertEqual(int(branch_alignment.loc[0, "other_rows"]), 1)
            self.assertEqual(branch_alignment.loc[0, "status"], "all_other")
            self.assertIn("other (1)", branch_alignment.loc[0, "top_families"])

            summary_text = (output_dir / "summary.txt").read_text(encoding="utf-8")
            self.assertIn("total_rows=1", summary_text)
            self.assertIn("other_rows=1", summary_text)


if __name__ == "__main__":
    unittest.main()
