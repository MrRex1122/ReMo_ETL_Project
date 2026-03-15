import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from catalog_merge import refresh_merged_catalog
from catalog_search import (
    DUCKDB_AVAILABLE,
    build_search_catalog_from_merged,
    classify_item_type,
    derive_branch_from_text,
    extract_item_markers,
    get_search_catalog_path,
    get_search_catalog_csv_path,
    get_search_catalog_duckdb_path,
    get_search_catalog_readiness,
    is_search_catalog_path,
    refresh_search_catalog,
)


class CatalogSearchTests(unittest.TestCase):
    def test_build_search_catalog_from_merged_creates_projected_storage(self):
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

            self.assertEqual(search_path, get_search_catalog_path(root))
            self.assertTrue(is_search_catalog_path(search_path))
            self.assertTrue(search_path.exists())

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

            built = pd.read_csv(
                build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root)),
                sep=";",
                encoding="utf-8",
            )
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

            built = pd.read_csv(
                build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root)),
                sep=";",
                encoding="utf-8",
            )
            markers = built.loc[0, "search_item_markers_json"]

            self.assertIn("shielding", markers)
            self.assertIn("cable_environment", markers)
            self.assertIn("cat6a", markers)

    def test_classify_item_type_marks_optical_cross_and_not_patch_cord(self):
        self.assertEqual(classify_item_type("Оптический кросс на 48 волокон 1U"), "optical_cross")
        self.assertEqual(classify_item_type("Оптический патч-корд LC-LC duplex OS2 2м"), "optical_patch_cord")
        self.assertEqual(derive_branch_from_text("Оптический кросс на 48 волокон 1U"), "телеком > оптика > кроссы")

    def test_classify_item_type_marks_soft_starter_and_airflow_blanking_panel(self):
        self.assertEqual(classify_item_type("Устройство плавного пуска STS22 30 кВт"), "soft_starter")
        self.assertEqual(classify_item_type("Заглушка для управления потоком воздуха 1U"), "airflow_blanking_panel")
        self.assertEqual(
            derive_branch_from_text("Заглушка для управления потоком воздуха 1U"),
            "телеком > аксессуары > шкафные аксессуары > заглушки",
        )

    def test_classify_item_type_prefers_iec_power_cable_over_pdu_reference(self):
        self.assertEqual(
            classify_item_type(
                "Кабель электрический соединительный 230VAC 16A IEC320 C19-C20, "
                "с механизмом фиксации в розетках PDU"
            ),
            "iec_power_cable",
        )

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
            self.assertTrue(is_search_catalog_path(search_path))
            self.assertIn(ready.search_format, {"csv", "duckdb"})

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
            self.assertTrue(is_search_catalog_path(search_path))

    def test_classify_item_type_does_not_treat_ups_with_iec_ports_as_power_cable(self):
        self.assertNotEqual(
            classify_item_type(
                "Ð˜ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº Ð±ÐµÑÐ¿ÐµÑ€ÐµÐ±Ð¾Ð¹Ð½Ð¾Ð³Ð¾ Ð¿Ð¸Ñ‚Ð°Ð½Ð¸Ñ Online 2000Ð’Ð, Ð²Ñ…Ð¾Ð´ IEC-320-C20, "
                "Ð²Ñ‹Ñ…Ð¾Ð´ IEC-320-C13 (3 ÑˆÑ‚.), IEC-320-C19 (1 ÑˆÑ‚.)"
            ),
            "iec_power_cable",
        )

    def test_classify_item_type_does_not_treat_sts_connector_as_ats_device(self):
        self.assertNotEqual(
            classify_item_type("ÐšÐ¾Ð½Ð½ÐµÐºÑ‚Ð¾Ñ€ HIP-GERM-MONO-8-2pin-STS"),
            "ats_sts",
        )

    def test_classify_item_type_marks_ascii_power_cord_as_iec_power_cable(self):
        self.assertEqual(
            classify_item_type("power cord IEC320 C19-C20 1.8m"),
            "iec_power_cable",
        )

    def test_classify_item_type_does_not_treat_ascii_ups_ports_as_iec_power_cable(self):
        self.assertNotEqual(
            classify_item_type("online ups 2000va input IEC-320-C20 output IEC-320-C13 IEC-320-C19"),
            "iec_power_cable",
        )

    def test_classify_item_type_does_not_treat_tc200_blank_panel_as_iec_power_cable(self):
        self.assertNotEqual(
            classify_item_type("Заглушка TC200x80 горячеоцинкованная"),
            "iec_power_cable",
        )

    def test_classify_item_type_does_not_treat_pdu_with_cable_length_as_iec_power_cable(self):
        self.assertEqual(
            classify_item_type("Блок розеток PDU 8xSchuko C20 кабель длиной 1.8 м с разъемом C20"),
            "pdu_basic",
        )

    def test_classify_item_type_does_not_treat_fastener_pdu_series_as_pdu(self):
        self.assertNotEqual(
            classify_item_type("Дюбель универсальный нейлоновый PDU N 8x40 с шурупом"),
            "pdu_basic",
        )

    def test_classify_item_type_does_not_treat_generic_socket_strip_as_pdu(self):
        self.assertNotEqual(
            classify_item_type("Блок розеток тройной с заземлением 16А белый"),
            "pdu_basic",
        )

    def test_classify_item_type_does_not_treat_non_telecom_commutation_panel_as_patch_panel(self):
        self.assertNotEqual(
            classify_item_type("Панель коммутационная Ridan WD на 8 каналов и 14 приводов"),
            "patch_panel",
        )

    def test_classify_item_type_separates_keystone_adapters_from_modules(self):
        self.assertEqual(
            classify_item_type("Avanti Адаптер для Keystone белое облако 1 модульный"),
            "keystone_adapter",
        )
        self.assertEqual(
            classify_item_type("Модуль Keystone экранированный категория 6A RJ45"),
            "keystone_module",
        )

    def test_classify_item_type_does_not_treat_keystone_patch_panel_as_module(self):
        self.assertEqual(
            classify_item_type("TITAN 5 Патч-панель на 12 модулей типа Keystone"),
            "patch_panel",
        )

    def test_classify_item_type_does_not_treat_ups_with_rj45_ports_as_outlet(self):
        self.assertNotEqual(
            classify_item_type(
                "Источник бесперебойного питания Value 2200E line interactive 2200VA USB RJ11 RJ45 4 Schuko"
            ),
            "rj45_outlet",
        )

    def test_classify_item_type_does_not_treat_optical_cable_for_patch_cords_as_patch_cord(self):
        self.assertNotEqual(
            classify_item_type(
                "Кабель волоконно-оптический многомодовый для патч кордов и кабельных сборок с коннекторами MPO/MTP"
            ),
            "optical_patch_cord",
        )

    def test_extract_item_markers_normalizes_category_and_panel_markers(self):
        markers = extract_item_markers("Патч-панель категория 5е UTP 24 порта")
        self.assertEqual(markers.get("category"), "cat5e")
        self.assertEqual(markers.get("port_count"), "24")

        markers = extract_item_markers("Модуль Keystone экранированный категория 6а")
        self.assertEqual(markers.get("category"), "cat6a")
        self.assertEqual(markers.get("component_kind"), "module")

    def test_extract_item_markers_marks_keystone_adapters_and_faceplates(self):
        adapter_markers = extract_item_markers("Avanti Адаптер для Keystone 1 модуль")
        faceplate_markers = extract_item_markers("Лицевая панель для информационных розеток Keystone 2 модуля")

        self.assertEqual(adapter_markers.get("component_kind"), "adapter")
        self.assertEqual(faceplate_markers.get("component_kind"), "faceplate")

    def test_extract_item_markers_marks_rj45_outlet_assemblies_and_port_counts(self):
        floor_box_markers = extract_item_markers(
            "Конструктив сетевой розетки для одного порта RJ-45 в лючок напольный в сборе"
        )
        cable_channel_markers = extract_item_markers(
            "Конструктив сетевой розетки для двух портов RJ-45 в кабель-канал, в сборе"
        )
        single_outlet_markers = extract_item_markers(
            "Розетка компьютерная 1-местная RJ-45"
        )
        cover_markers = extract_item_markers(
            "Накладка для информационных функций типа Keystone"
        )

        self.assertEqual(floor_box_markers.get("component_kind"), "assembly")
        self.assertEqual(floor_box_markers.get("installation_kind"), "floor_box")
        self.assertEqual(floor_box_markers.get("port_count"), "1")
        self.assertEqual(cable_channel_markers.get("component_kind"), "assembly")
        self.assertEqual(cable_channel_markers.get("installation_kind"), "cable_channel")
        self.assertEqual(cable_channel_markers.get("port_count"), "2")
        self.assertEqual(single_outlet_markers.get("port_count"), "1")
        self.assertEqual(cover_markers.get("component_kind"), "adapter")

    def test_build_search_catalog_can_write_csv_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "PDU Zero U 16A;PDU-1;1200;Шкафы телекоммуникационные;CLS-1;Блок розеток;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            self.assertEqual(search_path, get_search_catalog_csv_path(root))
            self.assertIn("search_branch_path", built.columns)
            self.assertEqual(len(built), 1)
            self.assertEqual(built.loc[0, "search_entity_type"], "pdu_basic")

    def test_build_search_catalog_can_write_duckdb_explicitly(self):
        if not DUCKDB_AVAILABLE:
            self.skipTest("duckdb package is not installed")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "PDU Zero U 16A;PDU-1;1200;Шкафы телекоммуникационные;CLS-1;Блок розеток;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_duckdb_path(root))

            self.assertEqual(search_path, get_search_catalog_duckdb_path(root))
            self.assertTrue(search_path.exists())
            readiness = get_search_catalog_readiness(root)
            self.assertEqual(readiness.search_path, search_path)
            self.assertEqual(readiness.search_format, "duckdb")


if __name__ == "__main__":
    unittest.main()
