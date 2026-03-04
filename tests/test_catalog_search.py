import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from catalog_merge import refresh_merged_catalog
from catalog_search import (
    build_search_catalog_from_merged,
    classify_item_type,
    derive_branch_from_text,
    get_search_catalog_path,
    get_search_catalog_readiness,
    refresh_search_catalog,
)


class CatalogSearchTests(unittest.TestCase):
    def test_build_search_catalog_from_merged_creates_projected_csv(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель;Лишняя колонка\n"
                    "PDU Zero U 16A;PDU-1;1200;Шкафы телекоммуникационные;CLS-1;Блок розеток;;ReMo;X\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path)

            self.assertEqual(search_path, root / "price_clean_search.csv")
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            self.assertIn("search_branch_path", built.columns)
            self.assertIn("search_tokens_json", built.columns)
            self.assertIn("search_item_markers_json", built.columns)
            self.assertNotIn("Лишняя колонка", built.columns)
            self.assertEqual(len(built), 1)
            self.assertEqual(built.loc[0, "Артикул"], "PDU-1")
            self.assertEqual(built.loc[0, "search_entity_type"], "pdu_basic")

    def test_build_search_catalog_extracts_richer_markers(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Оптический патч-корд LC-LC duplex OS2 2м;OPT-2;900;Коммутация;CLS-2;Патч-корд;;ReMo\n"
                ),
                encoding="utf-8",
            )

            built = pd.read_csv(build_search_catalog_from_merged(merged_path), sep=";", encoding="utf-8")
            markers = built.loc[0, "search_item_markers_json"]

            self.assertIn("connector_pair", markers)
            self.assertIn("fiber_mode", markers)
            self.assertIn("duplex", markers)

    def test_build_search_catalog_extracts_twisted_pair_shielding_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Кабель витая пара, LSZH, экранированный, категория 6а, внешний;TP-1;500;Кабели;CLS-3;Кабель;;ReMo\n"
                ),
                encoding="utf-8",
            )

            built = pd.read_csv(build_search_catalog_from_merged(merged_path), sep=";", encoding="utf-8")
            markers = built.loc[0, "search_item_markers_json"]

            self.assertIn("shielding", markers)
            self.assertIn("cable_environment", markers)
            self.assertIn("cat6a", markers)

    def test_classify_item_type_marks_optical_cross_and_not_patch_cord(self):
        self.assertEqual(classify_item_type("Оптический кросс на 48 волокон 1U"), "optical_cross")
        self.assertEqual(classify_item_type("Оптический патч-корд LC-LC duplex OS2 2м"), "optical_patch_cord")
        self.assertEqual(derive_branch_from_text("Оптический кросс на 48 волокон 1U"), "телеком > оптика > кроссы")

    def test_search_catalog_readiness_tracks_missing_ready_and_stale_states(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            clean_file = root / "price14_clean.csv"
            clean_file.write_text(
                "Наименование;Артикул;Цена розничная\nКабель ВВГ 3x1.5;A-1;100\n",
                encoding="utf-8",
            )

            invalid = get_search_catalog_readiness(root)
            self.assertEqual(invalid.state, "invalid")

            merged_path = refresh_merged_catalog(root)

            missing = get_search_catalog_readiness(root)
            self.assertEqual(missing.state, "missing")

            search_path = refresh_search_catalog(root)
            ready = get_search_catalog_readiness(root)
            self.assertEqual(ready.state, "ready")
            self.assertEqual(ready.search_path, search_path)

            newer_time = merged_path.stat().st_mtime + 10
            os.utime(merged_path, (newer_time, newer_time))
            stale = get_search_catalog_readiness(root)
            self.assertEqual(stale.state, "stale")

    def test_refresh_search_catalog_writes_default_search_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель ВВГ 3x1.5;A-1;100\n",
                encoding="utf-8",
            )
            refresh_merged_catalog(root)

            search_path = refresh_search_catalog(root)

            self.assertEqual(search_path, get_search_catalog_path(root))
            self.assertTrue(search_path.exists())


if __name__ == "__main__":
    unittest.main()
