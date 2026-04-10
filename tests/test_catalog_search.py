import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import skipUnless

import pandas as pd

from catalog_merge import refresh_merged_catalog
from catalog_search import (
    DUCKDB_AVAILABLE,
    build_search_catalog_from_merged,
    build_search_taxonomy_bootstrap_draft,
    build_search_taxonomy_branch_probe,
    build_search_taxonomy_preview,
    classify_item_type,
    derive_branch_from_text,
    ensure_search_taxonomy_snapshot,
    extract_item_markers,
    get_search_catalog_path,
    get_search_taxonomy_preview_audit_path,
    get_search_taxonomy_preview_branch_summary_path,
    get_search_taxonomy_preview_tree_path,
    get_search_taxonomy_branch_summary_path,
    get_search_taxonomy_tree_path,
    get_search_catalog_csv_path,
    get_search_catalog_duckdb_path,
    get_search_catalog_readiness,
    get_search_taxonomy_bootstrap_draft_csv_path,
    get_search_taxonomy_bootstrap_draft_json_path,
    get_search_taxonomy_probe_audit_path,
    get_search_taxonomy_probe_branch_summary_path,
    get_search_taxonomy_probe_report_path,
    get_search_taxonomy_probe_tree_path,
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

    @skipUnless(DUCKDB_AVAILABLE, "duckdb package is not installed")
    def test_duckdb_search_catalog_rebuild_logs_final_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная\n"
                    "Кабель ВВГ 3x1.5;A-1;100\n"
                ),
                encoding="utf-8",
            )

            with self.assertLogs("catalog_search", level="INFO") as captured:
                search_path = build_search_catalog_from_merged(
                    merged_path,
                    get_search_catalog_duckdb_path(root),
                )

            joined_logs = "\n".join(captured.output)
            self.assertTrue(search_path.exists())
            self.assertIn("Search catalog rebuild complete", joined_logs)
            self.assertIn(str(search_path), joined_logs)
            self.assertIn("format=duckdb", joined_logs)

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

    def test_classify_item_type_splits_other_into_lighting_and_tray_sheet(self):
        self.assertEqual(
            classify_item_type("Светильник светодиодный аварийный 595x595"),
            "lighting_fixture",
        )
        self.assertEqual(
            derive_branch_from_text("Светильник светодиодный аварийный 595x595"),
            "свет > светильники",
        )
        self.assertEqual(
            classify_item_type("Лоток листовой перфорированный 200х50"),
            "tray_sheet",
        )
        self.assertEqual(
            derive_branch_from_text("Лоток листовой перфорированный 200х50"),
            "листовые лотки оцинкованные (метод сендзимира)",
        )

    def test_classify_item_type_splits_other_into_contactor_relay_and_signage(self):
        self.assertEqual(
            classify_item_type("Контактор магнитный 25А"),
            "contactor_starter",
        )
        self.assertEqual(
            derive_branch_from_text("Контактор магнитный 25А"),
            "контакторы магнитные",
        )
        self.assertEqual(
            classify_item_type("Реле промежуточное 24В"),
            "control_relay",
        )
        self.assertEqual(
            classify_item_type("Световое табло ВЫХОД аварийное"),
            "light_signage",
        )
        self.assertEqual(
            derive_branch_from_text("Свето-звуковое табло ВЫХОД"),
            "свето-звуковое табло",
        )
        self.assertEqual(
            classify_item_type("Знак безопасности Направление эвакуации"),
            "safety_sign",
        )
        self.assertEqual(
            derive_branch_from_text("Знак безопасности Направление эвакуации"),
            "знаки безопасности",
        )

    def test_classify_item_type_splits_other_into_fire_alarm_control_software_power_and_firestop(self):
        self.assertEqual(
            classify_item_type("Извещатель пожарный дымовой адресный"),
            "fire_detector",
        )
        self.assertEqual(
            derive_branch_from_text("Извещатель пожарный дымовой адресный"),
            "извещатели пожарные",
        )
        self.assertEqual(
            classify_item_type("Оповещатель световой стробоскопический"),
            "fire_annunciator",
        )
        self.assertEqual(
            derive_branch_from_text("Оповещатель световой стробоскопический"),
            "световой оповещатель",
        )
        self.assertEqual(
            classify_item_type("Пульт контроля и управления"),
            "security_control_panel",
        )
        self.assertEqual(
            derive_branch_from_text("Пульт контроля и управления"),
            "приборы приёмно-контрольные для опс",
        )
        self.assertEqual(
            classify_item_type("Преобразователь интерфейса RS485 в Modbus RTU"),
            "security_interface_device",
        )
        self.assertEqual(
            derive_branch_from_text("Преобразователь интерфейса RS485 в Modbus RTU"),
            "дополнительное оборудование для пс",
        )
        self.assertEqual(
            classify_item_type("Модуль подключения нагрузки"),
            "security_module_device",
        )
        self.assertEqual(
            classify_item_type("ПО Сервер Орион Про"),
            "security_software",
        )
        self.assertEqual(
            classify_item_type("Аккумуляторная батарея 26 Ач"),
            "power_backup",
        )
        self.assertEqual(
            classify_item_type("Герметик огнезащитный терморасширяющийся"),
            "firestop_material",
        )

    def test_build_search_catalog_cleans_ops_branch_and_family_contamination(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;Тип исполнения кабельного изделия;Производитель\n"
                    "Извещатель пожарный тепловой адресный без кабельных вводов;DET-1;10;Извещатели Пожарные;CLS-1;Извещатель пожарный;;ReMo\n"
                    "Кабель интерфейсный RS-485 2х2х0,75;IFC-1;10;Кабели Интерфейсные;CLS-2;Кабель интерфейса;;ReMo\n"
                    "Устройство плавного пуска 15кВт со съемным пультом управления;SS-1;10;Устройства Плавного Пуска;CLS-3;Устройство плавного пуска;;ReMo\n"
                    "Блок управления внешний АВР-ATSE1-100R100/3F 100А;AVR-1;10;Моноблочные АВР На Базе Ва;CLS-4;Автоматический ввод резерва (АВР);;ReMo\n"
                    "Блок резервного питания 12В 2.5А в компактном корпусе под АКБ 1.2Ач;PWR-1;10;Приборы Приёмно-Контрольные Для Опс;CLS-5;Блок резервного питания;;Ритм\n"
                    "Блок реле ВЭРС-БРУ 16 версия 3.1, 16 реле с тремя контактами перекидного типа;REL-1;10;Приборы Приёмно-Контрольные Для Опс;CLS-6;Блок реле;;ВЭРС\n"
                    "Прибор приемно-контрольный охранно-пожарный Гранит-5А GSM;PNL-1;10;Приборы Приёмно-Контрольные Для Опс;CLS-7;ППКОП;;Гранит\n"
                    "Блок питания универсальный 12В 3А;PSU-1;10;Дополнительное оборудование для ос;CLS-8;Блок питания;;Ритм\n"
                    "Блок расширения адресных шлейфов;MOD-1;10;Дополнительное оборудование для ос;CLS-9;Блок расширения;;Болид\n"
                    "Конвертер интерфейсов RS485/Ethernet;CNV-1;10;Дополнительное оборудование для пс;CLS-10;Конвертер;;Болид\n"
                    "Блок выносной индикации на 32 ППКОП;IND-1;10;Дополнительное оборудование для ос;CLS-11;Блок выносной индикации;;Риф\n"
                    "Модуль передачи сообщений Ethernet;MSG-1;10;Дополнительное оборудование для ос;CLS-12;Модуль передачи сообщений;;Риф\n"
                    "Прибор объектовый Риф Стринг;OBJ-1;10;Дополнительное оборудование для ос;CLS-13;Устройство объектовое;;Риф\n"
                    "Блок бесперебойного питания 12В;BPS-1;10;Дополнительное оборудование для пс;CLS-14;Блок питания;;Аякс\n"
                    "Блок искрозащиты шлейфа;ISO-1;10;Дополнительное оборудование для пс;CLS-15;Барьер искрозащиты;;Аякс\n"
                    "Метка адресная пожарная со встроенным изолятором короткого замыкания;TAG-1;10;Дополнительное оборудование для пс;CLS-16;Метка адресная;;Аякс\n"
                    "Брелок радиоканальный для охранной системы;KEY-1;10;Дополнительное оборудование для ос;CLS-17;Брелок;;Риф\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            detector = built.loc[built["Артикул"] == "DET-1"].iloc[0]
            interface_cable = built.loc[built["Артикул"] == "IFC-1"].iloc[0]
            soft_starter = built.loc[built["Артикул"] == "SS-1"].iloc[0]
            avr = built.loc[built["Артикул"] == "AVR-1"].iloc[0]
            backup_block = built.loc[built["Артикул"] == "PWR-1"].iloc[0]
            relay_block = built.loc[built["Артикул"] == "REL-1"].iloc[0]
            panel = built.loc[built["Артикул"] == "PNL-1"].iloc[0]
            power_supply = built.loc[built["Артикул"] == "PSU-1"].iloc[0]
            module = built.loc[built["Артикул"] == "MOD-1"].iloc[0]
            converter = built.loc[built["Артикул"] == "CNV-1"].iloc[0]
            indicator = built.loc[built["Артикул"] == "IND-1"].iloc[0]
            message_module = built.loc[built["Артикул"] == "MSG-1"].iloc[0]
            object_device = built.loc[built["Артикул"] == "OBJ-1"].iloc[0]
            backup_ps = built.loc[built["Артикул"] == "BPS-1"].iloc[0]
            barrier = built.loc[built["Артикул"] == "ISO-1"].iloc[0]
            address_marker = built.loc[built["Артикул"] == "TAG-1"].iloc[0]
            keyfob = built.loc[built["Артикул"] == "KEY-1"].iloc[0]

            self.assertEqual(detector["search_branch_path"], "извещатели пожарные")
            self.assertEqual(detector["search_effective_family"], "fire_detector")

            self.assertEqual(interface_cable["search_branch_path"], "электрика > кабели")
            self.assertEqual(interface_cable["search_effective_family"], "cable")
            self.assertEqual(interface_cable["search_effective_entity_type"], "cable")

            self.assertEqual(soft_starter["search_effective_family"], "soft_starter")
            self.assertEqual(soft_starter["search_effective_entity_type"], "soft_starter")

            self.assertEqual(avr["search_effective_family"], "breaker")
            self.assertEqual(avr["search_effective_entity_type"], "breaker")

            self.assertEqual(backup_block["search_branch_path"], "приборы приёмно-контрольные для опс")
            self.assertEqual(backup_block["search_effective_family"], "power_backup")
            self.assertEqual(backup_block["search_effective_entity_type"], "power_backup")

            self.assertEqual(relay_block["search_branch_path"], "приборы приёмно-контрольные для опс")
            self.assertEqual(relay_block["search_effective_family"], "security_module_device")
            self.assertEqual(relay_block["search_effective_entity_type"], "security_module_device")

            self.assertEqual(panel["search_branch_path"], "приборы приёмно-контрольные для опс")
            self.assertEqual(panel["search_effective_family"], "security_control_panel")
            self.assertEqual(panel["search_effective_entity_type"], "security_control_panel")

            self.assertEqual(power_supply["search_branch_path"], "дополнительное оборудование для ос")
            self.assertEqual(power_supply["search_effective_family"], "power_backup")
            self.assertEqual(power_supply["search_effective_entity_type"], "power_backup")

            self.assertEqual(module["search_branch_path"], "дополнительное оборудование для ос")
            self.assertEqual(module["search_effective_family"], "security_module_device")
            self.assertEqual(module["search_effective_entity_type"], "security_module_device")

            self.assertEqual(converter["search_branch_path"], "дополнительное оборудование для пс")
            self.assertEqual(converter["search_effective_family"], "security_interface_device")
            self.assertEqual(converter["search_effective_entity_type"], "security_interface_device")

            self.assertEqual(indicator["search_branch_path"], "дополнительное оборудование для ос")
            self.assertEqual(indicator["search_effective_family"], "security_control_panel")
            self.assertEqual(indicator["search_effective_entity_type"], "security_control_panel")

            self.assertEqual(message_module["search_branch_path"], "дополнительное оборудование для ос")
            self.assertEqual(message_module["search_effective_family"], "security_interface_device")
            self.assertEqual(message_module["search_effective_entity_type"], "security_interface_device")

            self.assertEqual(object_device["search_branch_path"], "дополнительное оборудование для ос")
            self.assertEqual(object_device["search_effective_family"], "security_control_device")
            self.assertEqual(object_device["search_effective_entity_type"], "security_control_device")

            self.assertEqual(backup_ps["search_branch_path"], "дополнительное оборудование для пс")
            self.assertEqual(backup_ps["search_effective_family"], "power_backup")
            self.assertEqual(backup_ps["search_effective_entity_type"], "power_backup")

            self.assertEqual(barrier["search_branch_path"], "дополнительное оборудование для пс")
            self.assertEqual(barrier["search_effective_family"], "security_module_device")
            self.assertEqual(barrier["search_effective_entity_type"], "security_module_device")

            self.assertEqual(address_marker["search_branch_path"], "дополнительное оборудование для пс")
            self.assertEqual(address_marker["search_effective_family"], "security_module_device")
            self.assertEqual(address_marker["search_effective_entity_type"], "security_module_device")

            self.assertEqual(keyfob["search_branch_path"], "дополнительное оборудование для ос")
            self.assertEqual(keyfob["search_effective_family"], "security_control_device")
            self.assertEqual(keyfob["search_effective_entity_type"], "security_control_device")

    def test_build_search_catalog_assigns_signage_families(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;Тип исполнения кабельного изделия;Производитель\n"
                    "Свето-звуковое табло ВЫХОД 12В;SGN-1;10;Свето-Звуковое Табло;CLS-1;Световое Табло;;ReMo\n"
                    "Знак безопасности Направление эвакуации;SGN-2;10;Знаки Безопасности;CLS-2;Знак Безопасности;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            light_sign = built.loc[built["Артикул"] == "SGN-1"].iloc[0]
            safety_sign = built.loc[built["Артикул"] == "SGN-2"].iloc[0]

            self.assertEqual(light_sign["search_branch_path"], "свето-звуковое табло")
            self.assertEqual(light_sign["search_effective_family"], "light_signage")
            self.assertEqual(light_sign["search_effective_entity_type"], "light_signage")

            self.assertEqual(safety_sign["search_branch_path"], "знаки безопасности")
            self.assertEqual(safety_sign["search_effective_family"], "safety_sign")
            self.assertEqual(safety_sign["search_effective_entity_type"], "safety_sign")

    def test_build_search_catalog_cleans_breaker_and_lighting_branch_contamination(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;Тип исполнения кабельного изделия;Производитель\n"
                    "Выключатель автоматический модульный 1P 16A;BR-1;10;Автоматические выключатели модульные;CLS-1;Выключатель автоматический;;ReMo\n"
                    "Светильник светодиодный консольный 100Вт;LGT-1;10;Светильники наружные;CLS-2;Светильник;;ReMo\n"
                    "Светильник аварийный с держателем и кронштейном;LGT-2;10;Светильники аварийные;CLS-3;Светильник;;ReMo\n"
                    "Светильник аварийный с RJ45 интерфейсом;LGT-3;10;Светильники аварийные;CLS-4;Светильник;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            breaker = built.loc[built["Артикул"] == "BR-1"].iloc[0]
            lighting_console = built.loc[built["Артикул"] == "LGT-1"].iloc[0]
            lighting_holder = built.loc[built["Артикул"] == "LGT-2"].iloc[0]
            lighting_rj45 = built.loc[built["Артикул"] == "LGT-3"].iloc[0]

            self.assertTrue(str(breaker["search_branch_path"]).startswith("электрика > автоматы"))
            self.assertEqual(breaker["search_effective_family"], "breaker")
            self.assertEqual(breaker["search_effective_entity_type"], "breaker")

            self.assertEqual(lighting_console["search_branch_path"], "свет > светильники")
            self.assertEqual(lighting_console["search_effective_family"], "lighting_fixture")

            self.assertEqual(lighting_holder["search_branch_path"], "свет > светильники")
            self.assertEqual(lighting_holder["search_effective_family"], "lighting_fixture")

            self.assertEqual(lighting_rj45["search_branch_path"], "свет > светильники")
            self.assertEqual(lighting_rj45["search_effective_family"], "lighting_fixture")

    def test_build_search_catalog_cleans_cable_branch_contamination(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;Тип исполнения кабельного изделия;Производитель\n"
                    "Угол внутренний 25x17 коричневый AIM;CC-1;10;Углы Для Кабель-Каналов;CLS-1;Угол внутренний;;ReMo\n"
                    "Ввод кабельный для бронированного кабеля с двойным уплотнением;CG-1;10;Дополнительное Оборудование Для Пс;CLS-2;Ввод кабельный;;ReMo\n"
                    "Оптический кабель HDMI 2.1 19М на 19М, 20 м.;OPT-1;10;Видеокабель;CLS-3;Кабель HDMI;;ReMo\n"
                    "Лента LED герметичная в силиконовой оболочке 220В 13х8мм IP65 60 диодов/метр (бухта 50м);LED-1;10;Ленты Светодиодные 220В;CLS-4;Лента светодиодная;;ReMo\n"
                    "Кабельная лестница, 3 м KS20-600 L=3000 PG;TRAY-1;10;Лестничные Лотки Оцинкованные (Метод Сендзимира);CLS-5;Лоток лестничный;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            cable_channel_angle = built.loc[built["Артикул"] == "CC-1"].iloc[0]
            cable_gland = built.loc[built["Артикул"] == "CG-1"].iloc[0]
            optical_hdmi = built.loc[built["Артикул"] == "OPT-1"].iloc[0]
            led_strip = built.loc[built["Артикул"] == "LED-1"].iloc[0]
            tray = built.loc[built["Артикул"] == "TRAY-1"].iloc[0]

            self.assertEqual(cable_channel_angle["search_branch_path"], "углы для кабель-каналов")
            self.assertEqual(cable_channel_angle["search_effective_family"], "rack_accessory_strict")

            self.assertEqual(cable_gland["search_effective_family"], "cable")
            self.assertEqual(cable_gland["search_effective_entity_type"], "cable")
            self.assertEqual(cable_gland["search_branch_path"], "электрика > кабели")

            self.assertEqual(optical_hdmi["search_effective_family"], "cable")
            self.assertEqual(optical_hdmi["search_effective_entity_type"], "cable")
            self.assertEqual(optical_hdmi["search_branch_path"], "электрика > кабели")

            self.assertEqual(led_strip["search_effective_family"], "lighting_fixture")
            self.assertEqual(led_strip["search_branch_path"], "свет > светильники")

            self.assertEqual(
                tray["search_branch_path"],
                "лестничные лотки оцинкованные (метод сендзимира)",
            )
            self.assertEqual(tray["search_effective_family"], "tray_sheet")

    def test_build_search_catalog_aligns_cable_tray_leaf_branches_with_effective_family(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;Тип исполнения кабельного изделия;Производитель\n"
                    "Лоток листовой 100х50 оцинкованный;TR-1;10;Кабельные Лотки Оцинкованные (Метод Сендзимира);CLS-1;Аксессуар для кабельной трассы;;ReMo\n"
                    "Переходник левый 200/100 для кабельного лотка;TR-2;10;Переходники Для Кабельных Лотков Оцинкованные (Метод Сендзимира);CLS-2;Переходник;;ReMo\n"
                    "Подвес потолочный для кабельного лотка;TR-3;10;Подвесы И Крепления Для Кабельных Лотков Оцинкованные (Метод Сендзимира);CLS-3;Подвес;;ReMo\n"
                    "Перегородка продольная для кабельного лотка;TR-4;10;Разделители И Перегородки Для Кабельных Лотков Оцинкованные (Метод Сендзимира);CLS-4;Перегородка;;ReMo\n"
                    "Пластина для заземления PTCE;TR-5;10;Аксессуары Вспомогательные Для Кабеленесущих Систем;CLS-5;Пластина;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            tray = built.loc[built["Артикул"] == "TR-1"].iloc[0]
            adapter = built.loc[built["Артикул"] == "TR-2"].iloc[0]
            hanger = built.loc[built["Артикул"] == "TR-3"].iloc[0]
            divider = built.loc[built["Артикул"] == "TR-4"].iloc[0]
            helper_accessory = built.loc[built["Артикул"] == "TR-5"].iloc[0]

            self.assertEqual(
                tray["search_branch_path"],
                "кабельные лотки оцинкованные (метод сендзимира)",
            )
            self.assertEqual(tray["search_effective_family"], "tray_sheet")

            self.assertEqual(
                adapter["search_branch_path"],
                "переходники для кабельных лотков оцинкованные (метод сендзимира)",
            )
            self.assertEqual(adapter["search_effective_family"], "rack_accessory_strict")

            self.assertEqual(
                hanger["search_branch_path"],
                "подвесы и крепления для кабельных лотков оцинкованные (метод сендзимира)",
            )
            self.assertEqual(hanger["search_effective_family"], "rack_accessory_strict")

            self.assertEqual(
                divider["search_branch_path"],
                "разделители и перегородки для кабельных лотков оцинкованные (метод сендзимира)",
            )
            self.assertEqual(divider["search_effective_family"], "tray_sheet")

            self.assertEqual(
                helper_accessory["search_branch_path"],
                "аксессуары вспомогательные для кабеленесущих систем",
            )
            self.assertEqual(helper_accessory["search_effective_family"], "rack_accessory_strict")

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

    def test_classify_item_type_does_not_treat_without_pdu_battery_block_as_pdu(self):
        self.assertNotEqual(
            classify_item_type("Блок батарейный BAT VGD 240V RM for VRT 6000 240V 7.2Ah without PDU and without charger"),
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

    def test_classify_item_type_does_not_treat_ups_or_bypass_with_pdu_model_as_pdu(self):
        self.assertNotEqual(
            classify_item_type("Источник бесперебойного питания KEOR PDU 800ВА 8 IEC"),
            "pdu_basic",
        )
        self.assertNotEqual(
            classify_item_type("Байпас ручной 19 inch 1U с PDU для ИБП"),
            "pdu_basic",
        )

    def test_classify_item_type_does_not_treat_non_telecom_commutation_panel_as_patch_panel(self):
        self.assertNotEqual(
            classify_item_type("Панель коммутационная Ridan WD на 8 каналов и 14 приводов"),
            "patch_panel",
        )

    def test_classify_item_type_does_not_treat_generic_19inch_panel_as_patch_panel(self):
        self.assertNotEqual(
            classify_item_type('Панель 19" 1U Коммутационные панели'),
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

    def test_classify_item_type_does_not_treat_rj45_faceplate_as_outlet(self):
        self.assertNotEqual(
            classify_item_type("Celiane лицевая панель для розетки компьютерной RJ45 белая"),
            "rj45_outlet",
        )

    def test_classify_item_type_does_not_treat_rj45_assembly_as_pure_connector(self):
        self.assertNotEqual(
            classify_item_type("Connect Влагостойкая основа IP66 с розеткой и коннектором RJ45"),
            "rj45_connector",
        )

    def test_classify_item_type_does_not_treat_optical_cable_for_patch_cords_as_patch_cord(self):
        self.assertNotEqual(
            classify_item_type(
                "Кабель волоконно-оптический многомодовый для патч кордов и кабельных сборок с коннекторами MPO/MTP"
            ),
            "optical_patch_cord",
        )

    def test_classify_item_type_does_not_treat_non_network_patch_cord_as_patch_cord(self):
        self.assertNotEqual(
            classify_item_type("CX3 EMS Патч корд 250мм"),
            "patch_cord",
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

    def test_extract_item_markers_marks_tray_accessories_and_designation_family(self):
        accessory_markers = extract_item_markers(
            "Угол CD 90 вертикальный внеш. 100x50, артикул 36782K"
        )
        designation_markers = extract_item_markers(
            "Кабель, артикул КИПЭнг-HF 2х2х0,6"
        )

        self.assertEqual(accessory_markers.get("accessory_kind"), "corner")
        self.assertEqual(accessory_markers.get("orientation_kind"), "vertical")
        self.assertEqual(accessory_markers.get("position_kind"), "outer")
        self.assertEqual(designation_markers.get("designation_family"), "кипэнг hf")

    def test_classify_item_type_detects_tray_accessory_queries(self):
        self.assertEqual(
            classify_item_type("Консоль универсальная осн. 200 мм, артикул BBN5020"),
            "rack_accessory_strict",
        )

    def test_extract_item_markers_detects_clamp_as_holder(self):
        clamp_markers = extract_item_markers("Скоба однолапковая d=20-21")

        self.assertEqual(clamp_markers.get("accessory_kind"), "holder")
        self.assertEqual(classify_item_type("Скоба однолапковая d=20-21"), "rack_accessory_strict")

    def test_classify_item_type_detects_fastener_queries(self):
        fastener_markers = extract_item_markers("Анкер-клин 6х35 потолочный")

        self.assertEqual(fastener_markers.get("accessory_kind"), "fastener")
        self.assertEqual(classify_item_type("Анкер-клин 6х35 потолочный"), "fastener")

    def test_classify_item_type_does_not_treat_firestop_items_as_rack(self):
        self.assertEqual(
            classify_item_type("Огнестойкая монтажная пена ОГНЕЗА EI240, 750 мл"),
            "firestop_material",
        )
        self.assertEqual(
            classify_item_type("ОГНЕСТОЙКАЯ КАБЕЛЬНАЯ ЛИНИЯ"),
            "cable",
        )

    def test_classify_item_type_detects_cable_channel_box_rows(self):
        query = "Короб с крышкой 80x40 (3 м.)"
        markers = extract_item_markers(query)

        self.assertEqual(classify_item_type(query), "cable_channel")
        self.assertEqual(markers.get("installation_kind"), "cable_channel")
        self.assertEqual(markers.get("length_m"), "3")
        self.assertEqual(
            derive_branch_from_text(query),
            "электрика > кабели > кабель-каналы",
        )

    def test_classify_item_type_detects_industrial_valve_queries(self):
        self.assertEqual(
            classify_item_type("Затвор дисковый поворотный DN100"),
            "industrial_valve",
        )
        self.assertEqual(
            derive_branch_from_text("Затвор дисковый поворотный DN100"),
            "затворы поворотные дисковые стальные",
        )
        self.assertEqual(
            classify_item_type("Кран шаровой стальной DN50"),
            "industrial_valve",
        )
        self.assertEqual(
            derive_branch_from_text("Кран шаровой стальной DN50"),
            "краны шаровые стальные",
        )
        self.assertEqual(
            classify_item_type("Кран шаровой латунный для воды DN20"),
            "industrial_valve",
        )
        self.assertEqual(
            derive_branch_from_text("Кран шаровой латунный для воды DN20"),
            "краны шаровые латунные для воды",
        )
        self.assertEqual(
            classify_item_type("Кран шаровой ПНД 32 мм"),
            "industrial_valve",
        )
        self.assertEqual(
            derive_branch_from_text("Кран шаровой ПНД 32 мм"),
            "краны шаровые пнд",
        )
        self.assertEqual(
            classify_item_type("Затвор дисковый поворотный чугунный DN80"),
            "industrial_valve",
        )
        self.assertEqual(
            derive_branch_from_text("Затвор дисковый поворотный чугунный DN80"),
            "затворы поворотные дисковые чугунные",
        )
        self.assertEqual(
            classify_item_type("Клапан электромагнитный соленоидный 1/2"),
            "industrial_valve",
        )
        self.assertEqual(
            derive_branch_from_text("Клапан электромагнитный соленоидный 1/2"),
            "клапаны электромагнитные (соленоидные)",
        )

    def test_classify_item_type_detects_bearing_queries(self):
        self.assertEqual(
            classify_item_type("Подшипник роликовый цилиндрический 22210"),
            "bearing",
        )
        self.assertEqual(
            derive_branch_from_text("Подшипник роликовый цилиндрический 22210"),
            "подшипники роликовые цилиндрические",
        )
        self.assertEqual(
            classify_item_type("Подшипник роликовый сферический 22212"),
            "bearing",
        )
        self.assertEqual(
            derive_branch_from_text("Подшипник роликовый сферический 22212"),
            "подшипники роликовые сферические",
        )
        self.assertEqual(
            classify_item_type("Подшипник роликовый конический 30205"),
            "bearing",
        )
        self.assertEqual(
            derive_branch_from_text("Подшипник роликовый конический 30205"),
            "подшипники роликовые конические",
        )
        self.assertEqual(
            classify_item_type("Подшипник шариковый радиальный 6205"),
            "bearing",
        )
        self.assertEqual(
            derive_branch_from_text("Подшипник шариковый радиальный 6205"),
            "подшипники шариковые радиальные",
        )
        self.assertEqual(
            classify_item_type("Подшипник шариковый радиально-упорный 7205"),
            "bearing",
        )
        self.assertEqual(
            derive_branch_from_text("Подшипник шариковый радиально-упорный 7205"),
            "подшипники шариковые радиально-упорные",
        )
        self.assertEqual(
            classify_item_type("Подшипник упорный 51105"),
            "bearing",
        )
        self.assertEqual(
            derive_branch_from_text("Подшипник упорный 51105"),
            "упорные подшипники",
        )
        self.assertEqual(
            classify_item_type("Подшипник самоустанавливающийся шариковый 1205"),
            "bearing",
        )
        self.assertEqual(
            derive_branch_from_text("Подшипник самоустанавливающийся шариковый 1205"),
            "самоустанавливающиеся шарикоподшипники",
        )
        self.assertEqual(
            classify_item_type("Подшипник игольчатый HK1210"),
            "bearing",
        )
        self.assertEqual(
            derive_branch_from_text("Подшипник игольчатый HK1210"),
            "игольчатые подшипники",
        )

    def test_classify_item_type_detects_radiator_queries(self):
        self.assertEqual(
            classify_item_type("Радиатор стальной панельный 22 500x1000"),
            "radiator",
        )
        self.assertEqual(
            derive_branch_from_text("Радиатор стальной панельный 22 500x1000"),
            "радиаторы стальные панельные",
        )

    def test_classify_item_type_detects_floor_convector_queries(self):
        self.assertEqual(
            classify_item_type("Конвектор внутрипольный с вентилятором 2000мм"),
            "floor_convector",
        )
        self.assertEqual(
            derive_branch_from_text("Конвектор внутрипольный с вентилятором 2000мм"),
            "конвекторы внутрипольные",
        )

    def test_classify_item_type_detects_heat_shrink_queries(self):
        self.assertEqual(
            classify_item_type("Термоусаживаемая трубка 12/6 черная"),
            "heat_shrink",
        )
        self.assertEqual(
            derive_branch_from_text("Термоусаживаемая трубка 12/6 черная"),
            "термоусаживаемые изделия",
        )

    def test_classify_item_type_detects_transformer_queries(self):
        self.assertEqual(
            classify_item_type("Трансформатор напряжения понижающий низковольтный 220/24В"),
            "transformer",
        )
        self.assertEqual(
            derive_branch_from_text("Трансформатор напряжения понижающий низковольтный 220/24В"),
            "трансформаторы напряжения понижающие низковольтные",
        )
        self.assertEqual(
            derive_branch_from_text("Трансформатор тока низковольтный 100/5А"),
            "трансформаторы тока низковольтные",
        )

    def test_classify_item_type_detects_pressure_gauge_queries(self):
        self.assertEqual(
            classify_item_type("Манометр радиальный 0-10 бар"),
            "pressure_gauge",
        )
        self.assertEqual(
            derive_branch_from_text("Манометр радиальный 0-10 бар"),
            "манометры",
        )

    def test_classify_item_type_detects_multimeter_queries(self):
        self.assertEqual(
            classify_item_type("Мультиметр цифровой TRUE RMS 600В"),
            "multimeter",
        )
        self.assertEqual(
            derive_branch_from_text("Мультиметр цифровой TRUE RMS 600В"),
            "мультиметры",
        )
        self.assertNotEqual(
            classify_item_type("Кабельный тестер RJ45"),
            "multimeter",
        )

    def test_classify_item_type_detects_clamp_meter_queries(self):
        self.assertEqual(
            classify_item_type("Клещи токоизмерительные цифровые 600А"),
            "clamp_meter",
        )
        self.assertEqual(
            derive_branch_from_text("Клещи токоизмерительные цифровые 600А"),
            "клещи токоизмерительные",
        )
        self.assertNotEqual(
            classify_item_type("Клещи обжимные для наконечников"),
            "clamp_meter",
        )

    def test_classify_item_type_detects_voltage_indicator_queries(self):
        self.assertEqual(
            classify_item_type("Индикатор напряжения двухполюсный 12-690В"),
            "voltage_indicator",
        )
        self.assertEqual(
            derive_branch_from_text("Индикатор напряжения двухполюсный 12-690В"),
            "индикаторы напряжения",
        )
        self.assertNotEqual(
            classify_item_type("Арматура светосигнальная зеленая 24В"),
            "voltage_indicator",
        )

    def test_classify_item_type_detects_pressure_regulator_queries(self):
        self.assertEqual(
            classify_item_type("Регулятор давления воды DN20"),
            "pressure_regulator",
        )
        self.assertEqual(
            derive_branch_from_text("Регулятор давления воды DN20"),
            "регулятор давления",
        )

    def test_classify_item_type_detects_voltage_stabilizer_queries(self):
        self.assertEqual(
            classify_item_type("Стабилизатор напряжения 10 кВА 220В"),
            "voltage_stabilizer",
        )
        self.assertEqual(
            derive_branch_from_text("Стабилизатор напряжения 10 кВА 220В"),
            "стабилизаторы напряжения",
        )

    def test_classify_item_type_detects_frequency_drive_queries(self):
        self.assertEqual(
            classify_item_type("Преобразователь частоты 5,5 кВт 380В"),
            "frequency_drive",
        )
        self.assertEqual(
            derive_branch_from_text("Преобразователь частоты 5,5 кВт 380В"),
            "преобразователи частоты, приводы",
        )
        self.assertEqual(
            classify_item_type("Устройство плавного пуска 5,5 кВт"),
            "soft_starter",
        )

    def test_classify_item_type_detects_electric_motor_queries(self):
        self.assertEqual(
            classify_item_type("Электродвигатель асинхронный трехфазный 5,5 кВт"),
            "electric_motor",
        )
        self.assertEqual(
            derive_branch_from_text("Электродвигатель асинхронный трехфазный 5,5 кВт"),
            "электродвигатели общепромышленные",
        )
        self.assertNotEqual(
            classify_item_type("Преобразователь частоты для электродвигателя 5,5 кВт"),
            "electric_motor",
        )

    def test_classify_item_type_detects_industrial_pump_queries(self):
        self.assertEqual(
            classify_item_type("Насос промышленный вертикальный центробежный 5,5 кВт"),
            "industrial_pump",
        )
        self.assertEqual(
            derive_branch_from_text("Насос промышленный вертикальный центробежный 5,5 кВт"),
            "промышленные вертикальные центробежные насосы",
        )
        self.assertNotEqual(
            classify_item_type("Электродвигатель для насоса 5,5 кВт"),
            "industrial_pump",
        )

    def test_classify_item_type_detects_thread_tap_queries(self):
        self.assertEqual(
            classify_item_type("Метчик машинно-ручной М8"),
            "thread_tap",
        )
        self.assertEqual(
            derive_branch_from_text("Метчик машинно-ручной М8"),
            "метчики",
        )
        self.assertNotEqual(
            classify_item_type("Сверло по металлу 8 мм"),
            "thread_tap",
        )

    def test_classify_item_type_detects_thread_die_queries(self):
        self.assertEqual(
            classify_item_type("Плашка круглая М8"),
            "thread_die",
        )

    def test_classify_item_type_detects_socket_head_drive_belt_and_brass_fitting_queries(self):
        self.assertEqual(
            classify_item_type("Набор торцевых головок 1/2 10-24 мм"),
            "socket_head_set",
        )
        self.assertEqual(
            classify_item_type("Ремень узкоклиновой SPC 2240"),
            "drive_belt",
        )
        self.assertEqual(
            classify_item_type("Фитинг резьбовой латунный угольник 1/2"),
            "brass_threaded_fitting",
        )

    def test_classify_item_type_detects_workwear_gloves_polypropylene_fitting_and_turning_tool_queries(self):
        self.assertEqual(
            classify_item_type("Костюм летний рабочий мужской"),
            "workwear",
        )
        self.assertEqual(
            classify_item_type("Перчатки защитные антипорезные размер 10"),
            "protective_gloves",
        )
        self.assertEqual(
            classify_item_type("Фитинг полипропиленовый муфта 25 мм"),
            "polypropylene_fitting",
        )
        self.assertEqual(
            classify_item_type("Резец по металлу токарный проходной 16x16"),
            "metal_turning_tool",
        )

    def test_classify_item_type_detects_wrench_caliper_and_blade_queries(self):
        self.assertEqual(
            classify_item_type("Ключ комбинированный 17 мм"),
            "combination_wrench",
        )
        self.assertEqual(
            classify_item_type("Штангенциркуль цифровой 150 мм"),
            "caliper",
        )
        self.assertEqual(
            classify_item_type("Пильный диск по дереву 190x30x24T"),
            "wood_saw_blade",
        )
        self.assertEqual(
            classify_item_type("Алмазный диск 125 мм по бетону"),
            "diamond_blade",
        )

    def test_classify_item_type_detects_cartridge_and_screwdriver_queries(self):
        self.assertEqual(
            classify_item_type("Картридж для принтера HP 85A"),
            "printer_cartridge",
        )
        self.assertEqual(
            classify_item_type("Отвертка крестовая PH2x100"),
            "phillips_screwdriver",
        )

    def test_classify_item_type_detects_thread_gauge_bits_wrenches_and_fitting_queries(self):
        self.assertEqual(
            classify_item_type("Резьбомер метрический М60"),
            "thread_gauge",
        )
        self.assertEqual(
            derive_branch_from_text("Резьбомер метрический М60"),
            "резьбомеры",
        )
        self.assertEqual(
            classify_item_type("Бита TORX T25 25 мм"),
            "torx_bit",
        )
        self.assertEqual(
            derive_branch_from_text("Бита TORX T25 25 мм"),
            "биты TORX",
        )
        self.assertEqual(
            classify_item_type("Бита крест PH2 50 мм"),
            "phillips_bit",
        )
        self.assertEqual(
            derive_branch_from_text("Бита крест PH2 50 мм"),
            "биты крест PH (Phillips)",
        )
        self.assertEqual(
            classify_item_type("Отвертка шлицевая SL6x100"),
            "slotted_screwdriver",
        )
        self.assertEqual(
            derive_branch_from_text("Отвертка шлицевая SL6x100"),
            "шлицевые отвертки",
        )
        self.assertEqual(
            classify_item_type("Ключ рожковый 17x19 мм"),
            "open_end_wrench",
        )
        self.assertEqual(
            derive_branch_from_text("Ключ рожковый 17x19 мм"),
            "рожковые ключи",
        )
        self.assertEqual(
            classify_item_type("Ключ имбусовый шестигранный HEX 6 мм"),
            "hex_key",
        )
        self.assertEqual(
            derive_branch_from_text("Ключ имбусовый шестигранный HEX 6 мм"),
            "ключи имбусовые шестигранные (HEX)",
        )
        self.assertEqual(
            classify_item_type("Фитинг аксиальный для PEX 16x1/2"),
            "axial_pex_fitting",
        )
        self.assertEqual(
            derive_branch_from_text("Фитинг аксиальный для PEX 16x1/2"),
            "фитинги аксиальные для PEX, PERT",
        )
        self.assertEqual(
            classify_item_type("Фитинг компрессионный ПНД 32x1 наружная резьба"),
            "pnd_compression_fitting",
        )
        self.assertEqual(
            derive_branch_from_text("Фитинг компрессионный ПНД 32x1 наружная резьба"),
            "фитинги компрессионные для ПНД труб пластиковые",
        )

    def test_classify_item_type_detects_self_tapping_screw_queries(self):
        self.assertEqual(
            classify_item_type("Саморез универсальный 4.2x32"),
            "self_tapping_screw",
        )
        self.assertEqual(
            derive_branch_from_text("Плашка круглая М8"),
            "плашки",
        )
        self.assertNotEqual(
            classify_item_type("Метчик машинно-ручной М8"),
            "thread_die",
        )

    def test_classify_item_type_detects_drill_bit_metal_queries(self):
        self.assertEqual(
            classify_item_type("Сверло по металлу HSS 8 мм"),
            "drill_bit_metal",
        )
        self.assertEqual(
            derive_branch_from_text("Сверло по металлу HSS 8 мм"),
            "сверла по металлу",
        )
        self.assertNotEqual(
            classify_item_type("Метчик машинно-ручной М8"),
            "drill_bit_metal",
        )

    def test_classify_item_type_detects_masonry_drill_bit_queries(self):
        self.assertEqual(
            classify_item_type("Бур SDS-Plus 8x160 мм"),
            "masonry_drill_bit",
        )
        self.assertEqual(
            derive_branch_from_text("Бур SDS-Plus 8x160 мм"),
            "буры sds-plus",
        )
        self.assertNotEqual(
            classify_item_type("Коронка алмазная по бетону 68 мм"),
            "masonry_drill_bit",
        )

    def test_classify_item_type_detects_concrete_hole_saw_queries(self):
        self.assertEqual(
            classify_item_type("Коронка по бетону алмазная 68 мм"),
            "concrete_hole_saw",
        )
        self.assertEqual(
            derive_branch_from_text("Коронка по бетону алмазная 68 мм"),
            "коронки по бетону",
        )
        self.assertNotEqual(
            classify_item_type("Бур SDS-Plus 8x160 мм"),
            "concrete_hole_saw",
        )

    def test_classify_item_type_detects_sds_chisel_queries(self):
        self.assertEqual(
            classify_item_type("Зубило SDS-Plus плоское 20x250 мм"),
            "sds_chisel",
        )
        self.assertEqual(
            derive_branch_from_text("Зубило SDS-Plus плоское 20x250 мм"),
            "зубила sds-plus",
        )
        self.assertNotEqual(
            classify_item_type("Бур SDS-Plus 8x160 мм"),
            "sds_chisel",
        )

    def test_classify_item_type_detects_distribution_enclosure_queries(self):
        self.assertEqual(
            classify_item_type("Щит распределительный встраиваемый металлический на 36 модулей"),
            "distribution_enclosure",
        )
        self.assertEqual(
            derive_branch_from_text("Щит распределительный встраиваемый металлический на 36 модулей"),
            "корпуса учетно-распределительные встраиваемые металлические",
        )
        self.assertEqual(
            classify_item_type("Корпус распределительный встраиваемый пластиковый на 24 модуля"),
            "distribution_enclosure",
        )
        self.assertEqual(
            derive_branch_from_text("Корпус распределительный встраиваемый пластиковый на 24 модуля"),
            "корпуса распределительные встраиваемые пластиковые",
        )
        self.assertEqual(
            classify_item_type("Щит распределительный навесной металлический ЩРН-36"),
            "distribution_enclosure",
        )
        self.assertEqual(
            derive_branch_from_text("Щит распределительный навесной металлический ЩРН-36"),
            "корпуса учетно-распределительные навесные металлические",
        )
        self.assertEqual(
            classify_item_type("Корпус распределительный навесной пластиковый ЩРН-П 24"),
            "distribution_enclosure",
        )
        self.assertEqual(
            derive_branch_from_text("Корпус распределительный навесной пластиковый ЩРН-П 24"),
            "корпуса распределительные навесные пластиковые",
        )
        self.assertEqual(
            classify_item_type("Встраиваемый силовой щит Nova 12 модулей с пластиковой дверью IP41"),
            "distribution_enclosure",
        )
        self.assertEqual(
            classify_item_type("Щит с монтажной панелью ЩМП-30.25.15 IP66"),
            "distribution_enclosure",
        )
        self.assertEqual(
            classify_item_type("Козырек защитный ЩМП 300х150мм"),
            "switchboard_accessory",
        )
        self.assertEqual(
            derive_branch_from_text("Козырек защитный ЩМП 300х150мм"),
            "вспомогательные щитовые аксессуары",
        )

    def test_classify_item_type_detects_power_accessory_queries(self):
        self.assertEqual(
            classify_item_type("Удлинитель силовой на 4 розетки 3м"),
            "power_accessory",
        )
        self.assertEqual(
            derive_branch_from_text("Удлинитель силовой на 4 розетки 3м"),
            "удлинители, сетевые фильтры, переходники, штепсельные вилки",
        )
        self.assertEqual(
            classify_item_type("Штепсельная вилка прямая 16А 220В"),
            "power_accessory",
        )
        self.assertEqual(
            derive_branch_from_text("Штепсельная вилка прямая 16А 220В"),
            "удлинители, сетевые фильтры, переходники, штепсельные вилки",
        )

    def test_classify_item_type_detects_cable_conduit_queries(self):
        self.assertEqual(
            classify_item_type("Металлорукав в ПВХ изоляции 20 мм"),
            "cable_conduit",
        )
        self.assertEqual(
            derive_branch_from_text("Металлорукав в ПВХ изоляции 20 мм"),
            "металлорукав с изоляцией",
        )
        self.assertEqual(
            classify_item_type("Труба гофрированная для прокладки кабеля 25 мм"),
            "cable_conduit",
        )
        self.assertEqual(
            derive_branch_from_text("Труба гофрированная для прокладки кабеля 25 мм"),
            "гофрированные трубы для прокладки кабеля",
        )
        self.assertEqual(
            classify_item_type("Труба жесткая двустенная 110 мм"),
            "cable_conduit",
        )
        self.assertEqual(
            derive_branch_from_text("Труба жесткая двустенная 110 мм"),
            "трубы жесткие двустенные",
        )

    def test_classify_item_type_detects_fuse_queries(self):
        self.assertEqual(
            classify_item_type("Предохранитель плавкий 10А"),
            "fuse",
        )
        self.assertEqual(
            derive_branch_from_text("Предохранитель плавкий 10А"),
            "плавкие предохранители",
        )

    def test_classify_item_type_detects_ups_queries(self):
        self.assertEqual(
            classify_item_type("Источник бесперебойного питания Line Interactive 2000VA"),
            "ups",
        )
        self.assertEqual(
            derive_branch_from_text("Источник бесперебойного питания Line Interactive 2000VA"),
            "источники бесперебойного питания (ибп)",
        )

    def test_classify_item_type_detects_push_button_queries(self):
        self.assertEqual(
            classify_item_type("Кнопка управления красная 22мм"),
            "push_button",
        )
        self.assertEqual(
            derive_branch_from_text("Кнопка управления красная 22мм"),
            "кнопки",
        )
        self.assertEqual(
            classify_item_type("Кнопочный пост ПКЕ 2 кнопки"),
            "push_button",
        )

    def test_classify_item_type_detects_terminal_block_and_signal_indicator_queries(self):
        self.assertEqual(
            classify_item_type("Клеммный блок на DIN-рейку 2,5мм серый"),
            "terminal_block",
        )
        self.assertEqual(
            derive_branch_from_text("Клеммный блок на DIN-рейку 2,5мм серый"),
            "клеммные блоки зажимов на din-рейку",
        )
        self.assertEqual(
            classify_item_type("Проходная клемма на DIN-рейку 4мм"),
            "terminal_block",
        )
        self.assertEqual(
            derive_branch_from_text("Проходная клемма на DIN-рейку 4мм"),
            "проходные клеммы на din-рейку",
        )
        self.assertEqual(
            classify_item_type("Миниклемма на DIN-рейку 2,5мм"),
            "terminal_block",
        )
        self.assertEqual(
            derive_branch_from_text("Миниклемма на DIN-рейку 2,5мм"),
            "миниклеммы на din-рейку",
        )
        self.assertEqual(
            classify_item_type("Арматура светосигнальная зеленая 24В"),
            "signal_indicator",
        )
        self.assertEqual(
            derive_branch_from_text("Арматура светосигнальная зеленая 24В"),
            "светосигнальная арматура",
        )

    def test_classify_item_type_detects_neutral_busbar_queries(self):
        self.assertEqual(
            classify_item_type("Нулевая шина на DIN-рейку 12 групп"),
            "neutral_busbar",
        )
        self.assertEqual(
            derive_branch_from_text("Нулевая шина на DIN-рейку 12 групп"),
            "нулевые шины на din-рейку",
        )
        self.assertNotEqual(
            classify_item_type("Шина заземления медная"),
            "neutral_busbar",
        )

    def test_classify_item_type_detects_wire_ferrule_queries(self):
        self.assertEqual(
            classify_item_type("Наконечник штыревой втулочный НШВИ 1,5-8"),
            "wire_ferrule",
        )
        self.assertEqual(
            derive_branch_from_text("Наконечник штыревой втулочный НШВИ 1,5-8"),
            "штыревые втулочные наконечники (ншв и ншви)",
        )

    def test_classify_item_type_detects_breaker_load_switch_queries(self):
        self.assertEqual(
            classify_item_type("Выключатель нагрузки 3P 63A"),
            "breaker",
        )
        self.assertEqual(
            derive_branch_from_text("Выключатель нагрузки 3P 63A"),
            "рубильники",
        )
        self.assertEqual(
            classify_item_type("Выключатель разъединитель 3P 125A"),
            "breaker",
        )
        self.assertEqual(
            derive_branch_from_text("Выключатель разъединитель 3P 125A"),
            "рубильники",
        )

    def test_classify_item_type_detects_surge_protector_queries(self):
        self.assertEqual(
            classify_item_type("Ограничитель импульсного перенапряжения SPD тип 2 40кА"),
            "surge_protector",
        )
        self.assertEqual(
            derive_branch_from_text("Ограничитель импульсного перенапряжения SPD тип 2 40кА"),
            "ограничители импульсного перенапряжения силовые модульные",
        )
        self.assertEqual(
            derive_branch_from_text("Кнопочный пост ПКЕ 2 кнопки"),
            "кнопочные посты",
        )

    def test_build_search_catalog_maps_perforated_cable_channels_to_cable_channel_family(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Короб перфорированный 40x40 серый;DUCT-1;120;Перфорированные Кабель-Каналы;CLS-1;"
                    "Короб перфорированный;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            cable_channel = built.loc[built["Артикул"] == "DUCT-1"].iloc[0]

            self.assertEqual(cable_channel["search_branch_path"], "перфорированные кабель-каналы")
            self.assertEqual(cable_channel["search_entity_type"], "cable_channel")
            self.assertEqual(cable_channel["search_effective_entity_type"], "cable_channel")
            self.assertEqual(cable_channel["search_effective_family"], "cable_channel")

    def test_build_search_catalog_maps_industrial_valves_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Затвор дисковый поворотный DN100;VALVE-1;10;Затворы Поворотные Дисковые Стальные;CLS-1;Затвор дисковый поворотный;;ReMo\n"
                    "Затвор дисковый поворотный чугунный DN80;VALVE-3;10;Затворы Поворотные Дисковые Чугунные;CLS-3;Затвор дисковый поворотный чугунный;;ReMo\n"
                    "Кран шаровой стальной DN50;VALVE-2;10;Краны Шаровые Стальные;CLS-2;Кран шаровой стальной;;ReMo\n"
                    "Кран шаровой латунный для воды DN20;VALVE-5;10;Краны Шаровые Латунные Для Воды;CLS-5;Кран шаровой латунный;;ReMo\n"
                    "Кран шаровой ПНД 32 мм;VALVE-4;10;Краны Шаровые ПНД;CLS-4;Кран шаровой ПНД;;ReMo\n"
                    "Клапан электромагнитный соленоидный 1/2;VALVE-6;10;Клапаны Электромагнитные (Соленоидные);CLS-6;Клапан электромагнитный;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            disc_valve = built.loc[built["Артикул"] == "VALVE-1"].iloc[0]
            cast_iron_valve = built.loc[built["Артикул"] == "VALVE-3"].iloc[0]
            ball_valve = built.loc[built["Артикул"] == "VALVE-2"].iloc[0]
            brass_valve = built.loc[built["Артикул"] == "VALVE-5"].iloc[0]
            pnd_valve = built.loc[built["Артикул"] == "VALVE-4"].iloc[0]
            solenoid_valve = built.loc[built["Артикул"] == "VALVE-6"].iloc[0]

            self.assertEqual(disc_valve["search_branch_path"], "затворы поворотные дисковые стальные")
            self.assertEqual(disc_valve["search_entity_type"], "industrial_valve")
            self.assertEqual(disc_valve["search_effective_entity_type"], "industrial_valve")
            self.assertEqual(disc_valve["search_effective_family"], "industrial_valve")

            self.assertEqual(cast_iron_valve["search_branch_path"], "затворы поворотные дисковые чугунные")
            self.assertEqual(cast_iron_valve["search_entity_type"], "industrial_valve")
            self.assertEqual(cast_iron_valve["search_effective_entity_type"], "industrial_valve")
            self.assertEqual(cast_iron_valve["search_effective_family"], "industrial_valve")

            self.assertEqual(ball_valve["search_branch_path"], "краны шаровые стальные")
            self.assertEqual(ball_valve["search_entity_type"], "industrial_valve")
            self.assertEqual(ball_valve["search_effective_entity_type"], "industrial_valve")
            self.assertEqual(ball_valve["search_effective_family"], "industrial_valve")

            self.assertEqual(brass_valve["search_branch_path"], "краны шаровые латунные для воды")
            self.assertEqual(brass_valve["search_entity_type"], "industrial_valve")
            self.assertEqual(brass_valve["search_effective_entity_type"], "industrial_valve")
            self.assertEqual(brass_valve["search_effective_family"], "industrial_valve")

            self.assertEqual(pnd_valve["search_branch_path"], "краны шаровые пнд")
            self.assertEqual(pnd_valve["search_entity_type"], "industrial_valve")
            self.assertEqual(pnd_valve["search_effective_entity_type"], "industrial_valve")
            self.assertEqual(pnd_valve["search_effective_family"], "industrial_valve")

            self.assertEqual(solenoid_valve["search_branch_path"], "клапаны электромагнитные (соленоидные)")
            self.assertEqual(solenoid_valve["search_entity_type"], "industrial_valve")
            self.assertEqual(solenoid_valve["search_effective_entity_type"], "industrial_valve")
            self.assertEqual(solenoid_valve["search_effective_family"], "industrial_valve")

    def test_build_search_catalog_maps_bearings_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Подшипник роликовый цилиндрический 22210;BEARING-1;10;Подшипники Роликовые Цилиндрические;CLS-1;Подшипник роликовый цилиндрический;;ReMo\n"
                    "Подшипник роликовый сферический 22212;BEARING-4;10;Подшипники Роликовые Сферические;CLS-4;Подшипник роликовый сферический;;ReMo\n"
                    "Подшипник роликовый конический 30205;BEARING-6;10;Подшипники Роликовые Конические;CLS-6;Подшипник роликовый конический;;ReMo\n"
                    "Подшипник шариковый радиальный 6205;BEARING-2;10;Подшипники Шариковые Радиальные;CLS-2;Подшипник шариковый радиальный;;ReMo\n"
                    "Подшипник шариковый радиально-упорный 7205;BEARING-3;10;Подшипники Шариковые Радиально-Упорные;CLS-3;Подшипник шариковый радиально-упорный;;ReMo\n"
                    "Подшипник упорный 51105;BEARING-7;10;Упорные Подшипники;CLS-7;Подшипник упорный;;ReMo\n"
                    "Подшипник самоустанавливающийся шариковый 1205;BEARING-8;10;Самоустанавливающиеся Шарикоподшипники;CLS-8;Подшипник самоустанавливающийся шариковый;;ReMo\n"
                    "Подшипник игольчатый HK1210;BEARING-5;10;Игольчатые Подшипники;CLS-5;Подшипник игольчатый;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            roller_bearing = built.loc[built["Артикул"] == "BEARING-1"].iloc[0]
            spherical_bearing = built.loc[built["Артикул"] == "BEARING-4"].iloc[0]
            tapered_bearing = built.loc[built["Артикул"] == "BEARING-6"].iloc[0]
            ball_bearing = built.loc[built["Артикул"] == "BEARING-2"].iloc[0]
            thrust_bearing = built.loc[built["Артикул"] == "BEARING-3"].iloc[0]
            axial_bearing = built.loc[built["Артикул"] == "BEARING-7"].iloc[0]
            self_aligning_bearing = built.loc[built["Артикул"] == "BEARING-8"].iloc[0]
            needle_bearing = built.loc[built["Артикул"] == "BEARING-5"].iloc[0]

            self.assertEqual(roller_bearing["search_branch_path"], "подшипники роликовые цилиндрические")
            self.assertEqual(roller_bearing["search_entity_type"], "bearing")
            self.assertEqual(roller_bearing["search_effective_entity_type"], "bearing")
            self.assertEqual(roller_bearing["search_effective_family"], "bearing")

            self.assertEqual(spherical_bearing["search_branch_path"], "подшипники роликовые сферические")
            self.assertEqual(spherical_bearing["search_entity_type"], "bearing")
            self.assertEqual(spherical_bearing["search_effective_entity_type"], "bearing")
            self.assertEqual(spherical_bearing["search_effective_family"], "bearing")

            self.assertEqual(tapered_bearing["search_branch_path"], "подшипники роликовые конические")
            self.assertEqual(tapered_bearing["search_entity_type"], "bearing")
            self.assertEqual(tapered_bearing["search_effective_entity_type"], "bearing")
            self.assertEqual(tapered_bearing["search_effective_family"], "bearing")

            self.assertEqual(ball_bearing["search_branch_path"], "подшипники шариковые радиальные")
            self.assertEqual(ball_bearing["search_entity_type"], "bearing")
            self.assertEqual(ball_bearing["search_effective_entity_type"], "bearing")
            self.assertEqual(ball_bearing["search_effective_family"], "bearing")

            self.assertEqual(thrust_bearing["search_branch_path"], "подшипники шариковые радиально-упорные")
            self.assertEqual(thrust_bearing["search_entity_type"], "bearing")
            self.assertEqual(thrust_bearing["search_effective_entity_type"], "bearing")
            self.assertEqual(thrust_bearing["search_effective_family"], "bearing")

            self.assertEqual(axial_bearing["search_branch_path"], "упорные подшипники")
            self.assertEqual(axial_bearing["search_entity_type"], "bearing")
            self.assertEqual(axial_bearing["search_effective_entity_type"], "bearing")
            self.assertEqual(axial_bearing["search_effective_family"], "bearing")

            self.assertEqual(self_aligning_bearing["search_branch_path"], "самоустанавливающиеся шарикоподшипники")
            self.assertEqual(self_aligning_bearing["search_entity_type"], "bearing")
            self.assertEqual(self_aligning_bearing["search_effective_entity_type"], "bearing")
            self.assertEqual(self_aligning_bearing["search_effective_family"], "bearing")

            self.assertEqual(needle_bearing["search_branch_path"], "игольчатые подшипники")
            self.assertEqual(needle_bearing["search_entity_type"], "bearing")
            self.assertEqual(needle_bearing["search_effective_entity_type"], "bearing")
            self.assertEqual(needle_bearing["search_effective_family"], "bearing")

    def test_build_search_catalog_maps_radiators_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Радиатор стальной панельный 22 500x1000;RAD-1;10;Радиаторы Стальные Панельные;CLS-1;Радиатор стальной панельный;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            radiator = built.loc[built["Артикул"] == "RAD-1"].iloc[0]

            self.assertEqual(radiator["search_branch_path"], "радиаторы стальные панельные")
            self.assertEqual(radiator["search_entity_type"], "radiator")
            self.assertEqual(radiator["search_effective_entity_type"], "radiator")
            self.assertEqual(radiator["search_effective_family"], "radiator")

    def test_build_search_catalog_maps_pressure_gauges_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Манометр радиальный 0-10 бар;GAUGE-1;10;Манометры;CLS-1;Манометр;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            gauge = built.loc[built["Артикул"] == "GAUGE-1"].iloc[0]

            self.assertEqual(gauge["search_branch_path"], "манометры")
            self.assertEqual(gauge["search_entity_type"], "pressure_gauge")
            self.assertEqual(gauge["search_effective_entity_type"], "pressure_gauge")
            self.assertEqual(gauge["search_effective_family"], "pressure_gauge")

    def test_build_search_catalog_maps_multimeters_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Мультиметр цифровой TRUE RMS 600В;MULTI-1;10;Мультиметры;CLS-1;Мультиметр цифровой;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            multimeter = built.loc[built["Артикул"] == "MULTI-1"].iloc[0]

            self.assertEqual(multimeter["search_branch_path"], "мультиметры")
            self.assertEqual(multimeter["search_entity_type"], "multimeter")
            self.assertEqual(multimeter["search_effective_entity_type"], "multimeter")
            self.assertEqual(multimeter["search_effective_family"], "multimeter")

    def test_build_search_catalog_maps_clamp_meters_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Клещи токоизмерительные цифровые 600А;CLAMP-1;10;Клещи Токоизмерительные;CLS-1;Клещи токоизмерительные;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            clamp_meter = built.loc[built["Артикул"] == "CLAMP-1"].iloc[0]

            self.assertEqual(clamp_meter["search_branch_path"], "клещи токоизмерительные")
            self.assertEqual(clamp_meter["search_entity_type"], "clamp_meter")
            self.assertEqual(clamp_meter["search_effective_entity_type"], "clamp_meter")
            self.assertEqual(clamp_meter["search_effective_family"], "clamp_meter")

    def test_build_search_catalog_maps_voltage_indicators_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Индикатор напряжения двухполюсный 12-690В;VIND-1;10;Индикаторы Напряжения;CLS-1;Индикатор напряжения;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            indicator = built.loc[built["Артикул"] == "VIND-1"].iloc[0]

            self.assertEqual(indicator["search_branch_path"], "индикаторы напряжения")
            self.assertEqual(indicator["search_entity_type"], "voltage_indicator")
            self.assertEqual(indicator["search_effective_entity_type"], "voltage_indicator")
            self.assertEqual(indicator["search_effective_family"], "voltage_indicator")

    def test_build_search_catalog_maps_pressure_regulators_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Регулятор давления воды DN20;REG-1;10;Регулятор Давления;CLS-1;Регулятор давления;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            regulator = built.loc[built["Артикул"] == "REG-1"].iloc[0]

            self.assertEqual(regulator["search_branch_path"], "регулятор давления")
            self.assertEqual(regulator["search_entity_type"], "pressure_regulator")
            self.assertEqual(regulator["search_effective_entity_type"], "pressure_regulator")
            self.assertEqual(regulator["search_effective_family"], "pressure_regulator")

    def test_build_search_catalog_maps_voltage_stabilizers_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Стабилизатор напряжения 10 кВА 220В;STAB-1;10;Стабилизаторы Напряжения;CLS-1;Стабилизатор напряжения;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            stabilizer = built.loc[built["Артикул"] == "STAB-1"].iloc[0]

            self.assertEqual(stabilizer["search_branch_path"], "стабилизаторы напряжения")
            self.assertEqual(stabilizer["search_entity_type"], "voltage_stabilizer")
            self.assertEqual(stabilizer["search_effective_entity_type"], "voltage_stabilizer")
            self.assertEqual(stabilizer["search_effective_family"], "voltage_stabilizer")

    def test_build_search_catalog_maps_frequency_drives_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Преобразователь частоты 5,5 кВт 380В;VFD-1;10;Преобразователи Частоты, Приводы;CLS-1;Преобразователь частоты;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            drive = built.loc[built["Артикул"] == "VFD-1"].iloc[0]

            self.assertEqual(drive["search_branch_path"], "преобразователи частоты, приводы")
            self.assertEqual(drive["search_entity_type"], "frequency_drive")
            self.assertEqual(drive["search_effective_entity_type"], "frequency_drive")
            self.assertEqual(drive["search_effective_family"], "frequency_drive")

    def test_build_search_catalog_maps_electric_motors_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Электродвигатель асинхронный трехфазный 5,5 кВт;MOTOR-1;10;Электродвигатели Общепромышленные;CLS-1;Электродвигатель;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            motor = built.loc[built["Артикул"] == "MOTOR-1"].iloc[0]

            self.assertEqual(motor["search_branch_path"], "электродвигатели общепромышленные")
            self.assertEqual(motor["search_entity_type"], "electric_motor")
            self.assertEqual(motor["search_effective_entity_type"], "electric_motor")
            self.assertEqual(motor["search_effective_family"], "electric_motor")

    def test_build_search_catalog_maps_industrial_pumps_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Насос промышленный вертикальный центробежный 5,5 кВт;PUMP-1;10;Промышленные Вертикальные Центробежные Насосы;CLS-1;Насос;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            pump = built.loc[built["Артикул"] == "PUMP-1"].iloc[0]

            self.assertEqual(pump["search_branch_path"], "промышленные вертикальные центробежные насосы")
            self.assertEqual(pump["search_entity_type"], "industrial_pump")
            self.assertEqual(pump["search_effective_entity_type"], "industrial_pump")
            self.assertEqual(pump["search_effective_family"], "industrial_pump")

    def test_build_search_catalog_maps_thread_taps_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Метчик машинно-ручной М8;TAP-1;10;Метчики;CLS-1;Метчик;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            tap = built.loc[built["Артикул"] == "TAP-1"].iloc[0]

            self.assertEqual(tap["search_branch_path"], "метчики")
            self.assertEqual(tap["search_entity_type"], "thread_tap")
            self.assertEqual(tap["search_effective_entity_type"], "thread_tap")
            self.assertEqual(tap["search_effective_family"], "thread_tap")

    def test_build_search_catalog_maps_thread_dies_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Плашка круглая М8;DIE-1;10;Плашки;CLS-1;Плашка;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            die = built.loc[built["Артикул"] == "DIE-1"].iloc[0]

            self.assertEqual(die["search_branch_path"], "плашки")
            self.assertEqual(die["search_entity_type"], "thread_die")
            self.assertEqual(die["search_effective_entity_type"], "thread_die")
            self.assertEqual(die["search_effective_family"], "thread_die")

    def test_build_search_catalog_maps_socket_heads_drive_belts_and_brass_fittings_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Набор торцевых головок 1/2 10-24 мм;SOCKET-1;10;Торцевые Головки И Наборы Головок;CLS-1;Набор торцевых головок;;ReMo\n"
                    "Ремень узкоклиновой SPC 2240;BELT-1;10;Ремни Узкоклиновые;CLS-2;Ремень приводной;;ReMo\n"
                    "Фитинг резьбовой латунный угольник 1/2;FIT-1;10;Фитинги Резьбовые Латунные;CLS-3;Фитинг латунный;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            socket_head = built.loc[built["Артикул"] == "SOCKET-1"].iloc[0]
            belt = built.loc[built["Артикул"] == "BELT-1"].iloc[0]
            fitting = built.loc[built["Артикул"] == "FIT-1"].iloc[0]

            self.assertEqual(socket_head["search_branch_path"], "торцевые головки и наборы головок")
            self.assertEqual(socket_head["search_entity_type"], "socket_head_set")
            self.assertEqual(socket_head["search_effective_entity_type"], "socket_head_set")
            self.assertEqual(socket_head["search_effective_family"], "socket_head_set")

            self.assertEqual(belt["search_branch_path"], "ремни узкоклиновые")
            self.assertEqual(belt["search_entity_type"], "drive_belt")
            self.assertEqual(belt["search_effective_entity_type"], "drive_belt")
            self.assertEqual(belt["search_effective_family"], "drive_belt")

            self.assertEqual(fitting["search_branch_path"], "фитинги резьбовые латунные")
            self.assertEqual(fitting["search_entity_type"], "brass_threaded_fitting")
            self.assertEqual(fitting["search_effective_entity_type"], "brass_threaded_fitting")
            self.assertEqual(fitting["search_effective_family"], "brass_threaded_fitting")

    def test_build_search_catalog_maps_workwear_gloves_polypropylene_fittings_and_turning_tools_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Костюм летний рабочий мужской;WW-1;10;Костюмы Летние;CLS-1;Костюм рабочий;;ReMo\n"
                    "Костюм утепленный рабочий;WW-2;10;Костюмы Утепленные;CLS-2;Костюм рабочий утепленный;;ReMo\n"
                    "Перчатки защитные антипорезные размер 10;GL-1;10;Антипорезные И Защитные Перчатки;CLS-3;Перчатки защитные;;ReMo\n"
                    "Фитинг полипропиленовый муфта 25 мм;PP-1;10;Фитинги Для Полипропиленовых Труб;CLS-4;Фитинг полипропиленовый;;ReMo\n"
                    "Резец по металлу токарный проходной 16x16;TURN-1;10;Резцы По Металлу;CLS-5;Токарный резец;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            suit = built.loc[built["Артикул"] == "WW-1"].iloc[0]
            insulated_suit = built.loc[built["Артикул"] == "WW-2"].iloc[0]
            gloves = built.loc[built["Артикул"] == "GL-1"].iloc[0]
            fitting = built.loc[built["Артикул"] == "PP-1"].iloc[0]
            turning_tool = built.loc[built["Артикул"] == "TURN-1"].iloc[0]

            self.assertEqual(suit["search_branch_path"], "костюмы летние")
            self.assertEqual(suit["search_effective_family"], "workwear")
            self.assertEqual(insulated_suit["search_branch_path"], "костюмы утепленные")
            self.assertEqual(insulated_suit["search_effective_family"], "workwear")

            self.assertEqual(gloves["search_branch_path"], "антипорезные и защитные перчатки")
            self.assertEqual(gloves["search_effective_family"], "protective_gloves")

            self.assertEqual(fitting["search_branch_path"], "фитинги для полипропиленовых труб")
            self.assertEqual(fitting["search_effective_family"], "polypropylene_fitting")

            self.assertEqual(turning_tool["search_branch_path"], "резцы по металлу")
            self.assertEqual(turning_tool["search_effective_family"], "metal_turning_tool")

    def test_build_search_catalog_maps_wrench_caliper_and_blades_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Ключ комбинированный 17 мм;WR-1;10;Комбинированные Ключи;CLS-1;Ключ комбинированный;;ReMo\n"
                    "Штангенциркуль цифровой 150 мм;CAL-1;10;Штангенциркули;CLS-2;Штангенциркуль;;ReMo\n"
                    "Пильный диск по дереву 190x30x24T;WB-1;10;Пильные Диски По Дереву;CLS-3;Пильный диск;;ReMo\n"
                    "Алмазный диск 125 мм по бетону;DB-1;10;Алмазные Диски;CLS-4;Алмазный диск;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            wrench = built.loc[built["Артикул"] == "WR-1"].iloc[0]
            caliper = built.loc[built["Артикул"] == "CAL-1"].iloc[0]
            wood_blade = built.loc[built["Артикул"] == "WB-1"].iloc[0]
            diamond_blade = built.loc[built["Артикул"] == "DB-1"].iloc[0]

            self.assertEqual(wrench["search_branch_path"], "комбинированные ключи")
            self.assertEqual(wrench["search_effective_family"], "combination_wrench")

            self.assertEqual(caliper["search_branch_path"], "штангенциркули")
            self.assertEqual(caliper["search_effective_family"], "caliper")

            self.assertEqual(wood_blade["search_branch_path"], "пильные диски по дереву")
            self.assertEqual(wood_blade["search_effective_family"], "wood_saw_blade")

            self.assertEqual(diamond_blade["search_branch_path"], "алмазные диски")
            self.assertEqual(diamond_blade["search_effective_family"], "diamond_blade")

    def test_build_search_catalog_maps_cartridges_and_screwdrivers_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Картридж для принтера HP 85A;CRT-1;10;Картриджи Для Печатной Техники;CLS-1;Тонер картридж;;ReMo\n"
                    "Отвертка крестовая PH2x100;SCR-1;10;Крестовые Отвертки;CLS-2;Крестовая отвертка;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            cartridge = built.loc[built["Артикул"] == "CRT-1"].iloc[0]
            screwdriver = built.loc[built["Артикул"] == "SCR-1"].iloc[0]

            self.assertEqual(cartridge["search_branch_path"], "картриджи для печатной техники")
            self.assertEqual(cartridge["search_effective_family"], "printer_cartridge")

            self.assertEqual(screwdriver["search_branch_path"], "крестовые отвертки")
            self.assertEqual(screwdriver["search_effective_family"], "phillips_screwdriver")

    def test_build_search_catalog_maps_self_tapping_screws_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Саморез универсальный 4.2x32;STS-1;10;Саморезы Универсальные;CLS-1;Саморез;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            screw = built.loc[built["Артикул"] == "STS-1"].iloc[0]

            self.assertEqual(screw["search_branch_path"], "саморезы универсальные")
            self.assertEqual(screw["search_effective_family"], "self_tapping_screw")

    def test_build_search_catalog_maps_thread_gauges_bits_wrenches_and_fittings_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Резьбомер метрический М60;GAUGE-1;10;Резьбомеры;CLS-1;Резьбомер;;ReMo\n"
                    "Бита TORX T25 25 мм;TORX-1;10;Биты TORX;CLS-2;Бита;;ReMo\n"
                    "Бита крест PH2 50 мм;PHBIT-1;10;Биты Крест PH (Phillips);CLS-3;Бита;;ReMo\n"
                    "Отвертка шлицевая SL6x100;SL-1;10;Шлицевые Отвертки;CLS-4;Отвертка;;ReMo\n"
                    "Ключ рожковый 17x19 мм;WRENCH-1;10;Рожковые Ключи;CLS-5;Ключ;;ReMo\n"
                    "Ключ имбусовый шестигранный HEX 6 мм;HEX-1;10;Ключи Имбусовые Шестигранные (HEX);CLS-6;Ключ;;ReMo\n"
                    "Фитинг аксиальный для PEX 16x1/2;PEX-1;10;Фитинги Аксиальные Для PEX, PERT;CLS-7;Фитинг;;ReMo\n"
                    "Фитинг компрессионный ПНД 32x1 наружная резьба;PND-1;10;Фитинги Компрессионные Для ПНД Труб Пластиковые;CLS-8;Фитинг;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            expectations = {
                "GAUGE-1": ("резьбомеры", "thread_gauge"),
                "TORX-1": ("биты TORX", "torx_bit"),
                "PHBIT-1": ("биты крест PH (Phillips)", "phillips_bit"),
                "SL-1": ("шлицевые отвертки", "slotted_screwdriver"),
                "WRENCH-1": ("рожковые ключи", "open_end_wrench"),
                "HEX-1": ("ключи имбусовые шестигранные (HEX)", "hex_key"),
                "PEX-1": ("фитинги аксиальные для PEX, PERT", "axial_pex_fitting"),
                "PND-1": ("фитинги компрессионные для ПНД труб пластиковые", "pnd_compression_fitting"),
            }

            for article, (branch_path, family) in expectations.items():
                row = built.loc[built["Артикул"] == article].iloc[0]
                self.assertEqual(row["search_branch_path"], branch_path)
                self.assertEqual(row["search_entity_type"], family)
                self.assertEqual(row["search_effective_entity_type"], family)
                self.assertEqual(row["search_effective_family"], family)

    def test_build_search_catalog_maps_additional_hand_tool_abrasive_and_garden_branches_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Набор резьбонарезного инструмента М3-М12;SET-1;10;Наборы Резьбонарезного Инструмента;CLS-1;Набор инструмента;;ReMo\n"
                    "Ключ разводной 250 мм;ADJ-1;10;Разводные Ключи;CLS-2;Ключ;;ReMo\n"
                    "Фреза пазовая для ручного фрезера 12 мм;ROUT-1;10;Фрезы И Наборы Фрез Для Ручных Фрезеров;CLS-3;Фреза;;ReMo\n"
                    "Круг шлифовальный на липучке P120 125 мм;SAND-1;10;Круги Шлифовальные На Липучке;CLS-4;Круг шлифовальный;;ReMo\n"
                    "Корщетка чашечная М14 75 мм;BRUSH-1;10;Корщетки;CLS-5;Корщетка;;ReMo\n"
                    "Леска для триммера 2.4 мм звезда 15 м;TRIM-1;10;Леска Для Триммеров;CLS-6;Леска;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            expectations = {
                "SET-1": ("наборы резьбонарезного инструмента", "threading_tool_set"),
                "ADJ-1": ("разводные ключи", "adjustable_wrench"),
                "ROUT-1": ("фрезы и наборы фрез для ручных фрезеров", "router_bit"),
                "SAND-1": ("круги шлифовальные на липучке", "hook_loop_sanding_disc"),
                "BRUSH-1": ("корщетки", "wire_brush_tool"),
                "TRIM-1": ("леска для триммеров", "trimmer_line"),
            }

            for article, (branch_path, family) in expectations.items():
                row = built.loc[built["Артикул"] == article].iloc[0]
                self.assertEqual(row["search_branch_path"], branch_path)
                self.assertEqual(row["search_entity_type"], family)
                self.assertEqual(row["search_effective_entity_type"], family)
                self.assertEqual(row["search_effective_family"], family)

    def test_build_search_catalog_maps_additional_tool_drive_and_appliance_branches_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Куртка утепленная рабочая размер 52;WWJ-1;10;Куртки Утепленные;CLS-1;Куртка рабочая;;ReMo\n"
                    "Полукомбинезон рабочий утепленный размер 52;WWO-1;10;Брюки, Полукомбинезоны;CLS-2;Полукомбинезон рабочий;;ReMo\n"
                    "Ключ накидной 17 мм;RW-1;10;Накидные Ключи;CLS-3;Ключ;;ReMo\n"
                    "Валик малярный велюровый 180 мм;ROLL-1;10;Валики;CLS-4;Валик малярный;;ReMo\n"
                    "Бокорезы диэлектрические 160 мм;CUT-1;10;Бокорезы И Кусачки;CLS-5;Бокорезы;;ReMo\n"
                    "Саморез гипсокартон-дерево 3.5x35;STS-2;10;Саморезы Гипсокартон-Дерево;CLS-6;Саморез;;ReMo\n"
                    "Сверло по дереву спиральное 10 мм;WOOD-1;10;Сверла По Дереву;CLS-7;Сверло;;ReMo\n"
                    "Конвектор напольный электрический 1 кВт;FC-1;10;Конвекторы Напольные;CLS-8;Конвектор;;ReMo\n"
                    "Водонагреватель электрический накопительный 80 л;WH-1;10;Водонагреватели Электрические Накопительные;CLS-9;Водонагреватель;;ReMo\n"
                    "Аксессуар для преобразователя частоты с интерфейсной платой;FD-1;10;Аксессуары Для Преобразователей Частоты;CLS-10;Аксессуар;;ReMo\n"
                    "Клеммный зажим для печатной платы 5,08 мм 2 pin;PCB-1;10;Клеммные Зажимы Для Печатных Плат;CLS-11;Клеммный зажим;;ReMo\n"
                    "Лента изоляционная ПВХ синяя 19 мм;TAPE-1;10;Изолента;CLS-12;Лента изоляционная;;ReMo\n"
                    "Клапан регулирующий чугунный DN50;VALVE-1;10;Клапаны Регулирующие Чугунные;CLS-13;Клапан;;ReMo\n"
                    "Вентиль запорный стальной DN20;VALVE-2;10;Клапаны Запорные (Вентили) Стальные;CLS-14;Вентиль;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            expectations = {
                "WWJ-1": ("куртки утепленные", "workwear"),
                "WWO-1": ("брюки, полукомбинезоны", "workwear"),
                "RW-1": ("накидные ключи", "ring_wrench"),
                "ROLL-1": ("валики", "paint_roller"),
                "CUT-1": ("бокорезы и кусачки", "cutting_pliers"),
                "STS-2": ("саморезы гипсокартон-дерево", "self_tapping_screw"),
                "WOOD-1": ("сверла по дереву", "wood_drill_bit"),
                "FC-1": ("конвекторы напольные", "floor_convector"),
                "WH-1": ("водонагреватели электрические накопительные", "storage_water_heater"),
                "FD-1": ("аксессуары для преобразователей частоты", "frequency_drive"),
                "PCB-1": ("клеммные зажимы для печатных плат", "terminal_block"),
                "TAPE-1": ("изолента", "electrical_tape"),
                "VALVE-1": ("клапаны регулирующие чугунные", "industrial_valve"),
                "VALVE-2": ("клапаны запорные (вентили) стальные", "industrial_valve"),
            }

            for article, (branch_path, family) in expectations.items():
                row = built.loc[built["Артикул"] == article].iloc[0]
                self.assertEqual(row["search_branch_path"], branch_path)
                self.assertEqual(row["search_entity_type"], family)
                self.assertEqual(row["search_effective_entity_type"], family)
                self.assertEqual(row["search_effective_family"], family)

    def test_build_search_catalog_maps_lighting_footwear_hole_saw_and_insulation_branches_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Люстра 8xE14 макс. 40Вт;LIGHT-1;10;Люстры Под Лампу;CLS-1;Люстра;;ReMo\n"
                    "Ботинки рабочие S1P SRC, р.42;BOOT-1;10;Ботинки Рабочие;CLS-2;Ботинки;;ReMo\n"
                    "Полуботинки рабочие кожаные S1, р.43;SHOE-1;10;Полуботинки Рабочие;CLS-3;Полуботинки;;ReMo\n"
                    "Кольцевая коронка 53 мм;HOLE-2;10;Коронки;CLS-4;Коронка;;ReMo\n"
                    "Фреза концевая 10 мм z=4;MILL-1;10;Фрезы Для Станков;CLS-5;Фреза;;ReMo\n"
                    "Изоляция из вспененного каучука трубная 22x9;PIPE-1;10;Изоляция Из Вспененного Каучука Трубная;CLS-6;Трубная изоляция;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            expectations = {
                "LIGHT-1": ("люстры под лампу", "lighting_fixture"),
                "BOOT-1": ("ботинки рабочие", "safety_footwear"),
                "SHOE-1": ("полуботинки рабочие", "safety_footwear"),
                "HOLE-2": ("коронки", "hole_saw"),
                "MILL-1": ("фрезы для станков", "milling_cutter"),
                "PIPE-1": ("изоляция из вспененного каучука трубная", "pipe_insulation"),
            }

            for article, (branch_path, family) in expectations.items():
                row = built.loc[built["Артикул"] == article].iloc[0]
                self.assertEqual(row["search_branch_path"], branch_path)
                self.assertEqual(row["search_entity_type"], family)
                self.assertEqual(row["search_effective_entity_type"], family)
                self.assertEqual(row["search_effective_family"], family)

    def test_build_search_catalog_maps_measurement_hand_tool_and_footwear_branches_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Ботинки утепленные рабочие размер 43;BOOT-2;10;Ботинки Утепленные;CLS-1;Ботинки;;ReMo\n"
                    "Сапоги резиновые защитные высокие;BOOT-3;10;Сапоги Резиновые;CLS-2;Сапоги;;ReMo\n"
                    "Пресс-клещи для наконечников НШВИ 0.5-6 мм2;CRIMP-1;10;Ручные Пресс-Клещи И Кримперы;CLS-3;Пресс-клещи;;ReMo\n"
                    "Микрометр цифровой 0-25 мм;MIC-1;10;Микрометры;CLS-4;Микрометр;;ReMo\n"
                    "Рулетка измерительная 5м x 19мм;TM-1;10;Измерительные Рулетки;CLS-5;Рулетка;;ReMo\n"
                    "Уровень пузырьковый 600 мм;LVL-1;10;Уровни Пузырьковые;CLS-6;Уровень;;ReMo\n"
                    "Кисть флейцевая 50 мм натуральная щетина;BR-1;10;Кисти Плоские Флейцевые;CLS-7;Кисть;;ReMo\n"
                    "Круг абразивный отрезной 125x1.0x22.23;DISC-1;10;Абразивные Отрезные Диски;CLS-8;Отрезной круг;;ReMo\n"
                    "Длинногубцы изогнутые 160 мм;PLI-1;10;Длинногубцы, Утконосы И Круглогубцы;CLS-9;Длинногубцы;;ReMo\n"
                    "Струбцина F-образная 300 мм;CLAMP-1;10;Струбцины;CLS-10;Струбцина;;ReMo\n"
                    "Напильник плоский 200 мм;FILE-1;10;Напильники;CLS-11;Напильник;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            expectations = {
                "BOOT-2": ("ботинки утепленные", "safety_footwear"),
                "BOOT-3": ("сапоги резиновые", "safety_footwear"),
                "CRIMP-1": ("ручные пресс-клещи и кримперы", "crimping_tool"),
                "MIC-1": ("микрометры", "micrometer"),
                "TM-1": ("измерительные рулетки", "tape_measure"),
                "LVL-1": ("уровни пузырьковые", "spirit_level"),
                "BR-1": ("кисти плоские флейцевые", "paint_brush"),
                "DISC-1": ("абразивные отрезные диски", "abrasive_cutting_disc"),
                "PLI-1": ("длинногубцы, утконосы и круглогубцы", "long_nose_pliers"),
                "CLAMP-1": ("струбцины", "clamp_tool"),
                "FILE-1": ("напильники", "file_tool"),
            }

            for article, (branch_path, family) in expectations.items():
                row = built.loc[built["Артикул"] == article].iloc[0]
                self.assertEqual(row["search_branch_path"], branch_path)
                self.assertEqual(row["search_entity_type"], family)
                self.assertEqual(row["search_effective_entity_type"], family)
                self.assertEqual(row["search_effective_family"], family)

    def test_build_search_catalog_maps_holiday_panel_pipe_and_hardware_branches_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Гирлянда LED бахрома 2м*1м теплый свет 24V;GARLAND-1;10;Гирлянды;CLS-1;Гирлянда;;ReMo\n"
                    "Панель монтажная 2200х800 IEK;PANEL-1;10;Панели И Платы Монтажные;CLS-2;Панель монтажная;;ReMo\n"
                    "Муфта соединительная G1 из сплава цинка IP54;PIPE-1;10;Соединители Для Труб;CLS-3;Муфта соединительная;;ReMo\n"
                    "Анкерный закладной элемент фундамента для мачты МГФ-16;FOUND-1;10;Закладные Детали Фундамента Опор И Мачт Освещения;CLS-4;Деталь закладная;;ReMo\n"
                    "Глазок дверной 16мм хром;HARD-1;10;Фурнитура Для Замков, Дверей И Окон;CLS-5;Глазок дверной;;ReMo\n"
                    "Вакуумметр от -1 до 4 бар с комплектом адаптеров;AUTO-1;10;Специальный Инструмент Для Авторемонта;CLS-6;Вакуумметр;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            expectations = {
                "GARLAND-1": ("гирлянды", "holiday_lighting"),
                "PANEL-1": ("панели и платы монтажные", "enclosure_panel"),
                "PIPE-1": ("соединители для труб", "pipe_connector"),
                "FOUND-1": ("закладные детали фундамента опор и мачт освещения", "lighting_support_foundation"),
                "HARD-1": ("фурнитура для замков, дверей и окон", "door_window_hardware"),
                "AUTO-1": ("специальный инструмент для авторемонта", "auto_repair_tool"),
            }

            for article, (branch_path, family) in expectations.items():
                row = built.loc[built["Артикул"] == article].iloc[0]
                self.assertEqual(row["search_branch_path"], branch_path)
                self.assertEqual(row["search_entity_type"], family)
                self.assertEqual(row["search_effective_entity_type"], family)
                self.assertEqual(row["search_effective_family"], family)

    def test_build_search_catalog_maps_drill_bits_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Сверло по металлу HSS 8 мм;DRILL-1;10;Сверла По Металлу;CLS-1;Сверло;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            drill = built.loc[built["Артикул"] == "DRILL-1"].iloc[0]

            self.assertEqual(drill["search_branch_path"], "сверла по металлу")
            self.assertEqual(drill["search_entity_type"], "drill_bit_metal")
            self.assertEqual(drill["search_effective_entity_type"], "drill_bit_metal")
            self.assertEqual(drill["search_effective_family"], "drill_bit_metal")

    def test_build_search_catalog_maps_masonry_drill_bits_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Бур SDS-Plus 8x160 мм;MASONRY-1;10;Буры SDS-Plus;CLS-1;Бур;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            drill = built.loc[built["Артикул"] == "MASONRY-1"].iloc[0]

            self.assertEqual(drill["search_branch_path"], "буры sds-plus")
            self.assertEqual(drill["search_entity_type"], "masonry_drill_bit")
            self.assertEqual(drill["search_effective_entity_type"], "masonry_drill_bit")
            self.assertEqual(drill["search_effective_family"], "masonry_drill_bit")

    def test_build_search_catalog_maps_concrete_hole_saws_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Коронка по бетону алмазная 68 мм;HOLE-1;10;Коронки По Бетону;CLS-1;Коронка;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            hole_saw = built.loc[built["Артикул"] == "HOLE-1"].iloc[0]

            self.assertEqual(hole_saw["search_branch_path"], "коронки по бетону")
            self.assertEqual(hole_saw["search_entity_type"], "concrete_hole_saw")
            self.assertEqual(hole_saw["search_effective_entity_type"], "concrete_hole_saw")
            self.assertEqual(hole_saw["search_effective_family"], "concrete_hole_saw")

    def test_build_search_catalog_maps_sds_chisels_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Зубило SDS-Plus плоское 20x250 мм;CHISEL-1;10;Зубила SDS-Plus;CLS-1;Зубило;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            chisel = built.loc[built["Артикул"] == "CHISEL-1"].iloc[0]

            self.assertEqual(chisel["search_branch_path"], "зубила sds-plus")
            self.assertEqual(chisel["search_entity_type"], "sds_chisel")
            self.assertEqual(chisel["search_effective_entity_type"], "sds_chisel")
            self.assertEqual(chisel["search_effective_family"], "sds_chisel")

    def test_build_search_catalog_maps_distribution_enclosures_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Щит распределительный встраиваемый металлический на 36 модулей;ENC-1;10;Корпуса Учетно-Распределительные Встраиваемые Металлические;CLS-1;Щит распределительный;;ReMo\n"
                    "Корпус распределительный встраиваемый пластиковый на 24 модуля;ENC-2;10;Корпуса Распределительные Встраиваемые Пластиковые;CLS-2;Корпус распределительный;;ReMo\n"
                    "Щит распределительный навесной металлический ЩРН-36;ENC-3;10;Корпуса Учетно-Распределительные Навесные Металлические;CLS-3;Щит распределительный;;ReMo\n"
                    "Корпус распределительный навесной пластиковый ЩРН-П 24;ENC-4;10;Корпуса Распределительные Навесные Пластиковые;CLS-4;Корпус распределительный;;ReMo\n"
                    "Встраиваемый силовой щит Nova 12 модулей с пластиковой дверью IP41;ENC-5;10;Корпуса Распределительные Встраиваемые;CLS-5;Щит;;ReMo\n"
                    "Щит с монтажной панелью ЩМП-30.25.15 IP66;ENC-6;10;Корпуса Учетно-Распределительные Встраиваемые Металлические;CLS-6;Щит с монтажной панелью;;ReMo\n"
                    "Козырек защитный ЩМП 300х150мм;ACC-1;10;Вспомогательные Щитовые Аксессуары;CLS-7;Козырек;;ReMo\n"
                    "Дверь внутренняя ЩМП 500х500мм;ACC-2;10;Дополнительные Двери;CLS-8;Дверь;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            metal = built.loc[built["Артикул"] == "ENC-1"].iloc[0]
            plastic = built.loc[built["Артикул"] == "ENC-2"].iloc[0]
            metal_wall = built.loc[built["Артикул"] == "ENC-3"].iloc[0]
            plastic_wall = built.loc[built["Артикул"] == "ENC-4"].iloc[0]
            generic_built_in = built.loc[built["Артикул"] == "ENC-5"].iloc[0]
            panel_enclosure = built.loc[built["Артикул"] == "ENC-6"].iloc[0]
            canopy = built.loc[built["Артикул"] == "ACC-1"].iloc[0]
            inner_door = built.loc[built["Артикул"] == "ACC-2"].iloc[0]

            self.assertEqual(metal["search_branch_path"], "корпуса учетно-распределительные встраиваемые металлические")
            self.assertEqual(metal["search_entity_type"], "distribution_enclosure")
            self.assertEqual(metal["search_effective_entity_type"], "distribution_enclosure")
            self.assertEqual(metal["search_effective_family"], "distribution_enclosure")

            self.assertEqual(plastic["search_branch_path"], "корпуса распределительные встраиваемые пластиковые")
            self.assertEqual(plastic["search_entity_type"], "distribution_enclosure")
            self.assertEqual(plastic["search_effective_entity_type"], "distribution_enclosure")
            self.assertEqual(plastic["search_effective_family"], "distribution_enclosure")

            self.assertEqual(metal_wall["search_branch_path"], "корпуса учетно-распределительные навесные металлические")
            self.assertEqual(metal_wall["search_entity_type"], "distribution_enclosure")
            self.assertEqual(metal_wall["search_effective_entity_type"], "distribution_enclosure")
            self.assertEqual(metal_wall["search_effective_family"], "distribution_enclosure")

            self.assertEqual(plastic_wall["search_branch_path"], "корпуса распределительные навесные пластиковые")
            self.assertEqual(plastic_wall["search_entity_type"], "distribution_enclosure")
            self.assertEqual(plastic_wall["search_effective_entity_type"], "distribution_enclosure")
            self.assertEqual(plastic_wall["search_effective_family"], "distribution_enclosure")

            self.assertEqual(generic_built_in["search_branch_path"], "корпуса распределительные встраиваемые пластиковые")
            self.assertEqual(generic_built_in["search_effective_entity_type"], "distribution_enclosure")
            self.assertEqual(generic_built_in["search_effective_family"], "distribution_enclosure")

            self.assertEqual(panel_enclosure["search_branch_path"], "корпуса щитов монтажных металлических")
            self.assertEqual(panel_enclosure["search_effective_entity_type"], "distribution_enclosure")
            self.assertEqual(panel_enclosure["search_effective_family"], "distribution_enclosure")

            self.assertEqual(canopy["search_branch_path"], "вспомогательные щитовые аксессуары")
            self.assertEqual(canopy["search_effective_entity_type"], "switchboard_accessory")
            self.assertEqual(canopy["search_effective_family"], "switchboard_accessory")

            self.assertEqual(inner_door["search_branch_path"], "дополнительные двери")
            self.assertEqual(inner_door["search_effective_entity_type"], "switchboard_accessory")
            self.assertEqual(inner_door["search_effective_family"], "switchboard_accessory")

    def test_build_search_catalog_maps_cable_conduits_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Металлорукав в ПВХ изоляции 20 мм;COND-1;10;Металлорукав С Изоляцией;CLS-1;Металлорукав;;ReMo\n"
                    "Труба гофрированная для прокладки кабеля 25 мм;COND-2;10;Гофрированные Трубы Для Прокладки Кабеля;CLS-2;Труба гофрированная;;ReMo\n"
                    "Труба жесткая двустенная 110 мм;COND-3;10;Трубы Жесткие Двустенные;CLS-3;Труба жесткая двустенная;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            metal = built.loc[built["Артикул"] == "COND-1"].iloc[0]
            corrugated = built.loc[built["Артикул"] == "COND-2"].iloc[0]
            rigid = built.loc[built["Артикул"] == "COND-3"].iloc[0]

            self.assertEqual(metal["search_branch_path"], "металлорукав с изоляцией")
            self.assertEqual(metal["search_entity_type"], "cable_conduit")
            self.assertEqual(metal["search_effective_entity_type"], "cable_conduit")
            self.assertEqual(metal["search_effective_family"], "cable_conduit")

            self.assertEqual(corrugated["search_branch_path"], "гофрированные трубы для прокладки кабеля")
            self.assertEqual(corrugated["search_entity_type"], "cable_conduit")
            self.assertEqual(corrugated["search_effective_entity_type"], "cable_conduit")
            self.assertEqual(corrugated["search_effective_family"], "cable_conduit")

            self.assertEqual(rigid["search_branch_path"], "трубы жесткие двустенные")
            self.assertEqual(rigid["search_entity_type"], "cable_conduit")
            self.assertEqual(rigid["search_effective_entity_type"], "cable_conduit")
            self.assertEqual(rigid["search_effective_family"], "cable_conduit")

    def test_build_search_catalog_maps_power_accessories_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Удлинитель силовой на 4 розетки 3м;PWR-1;10;Удлинители, Сетевые Фильтры, Переходники, Штепсельные Вилки;CLS-1;Удлинитель;;ReMo\n"
                    "Штепсельная вилка прямая 16А 220В;PWR-2;10;Удлинители, Сетевые Фильтры, Переходники, Штепсельные Вилки;CLS-2;Штепсельная вилка;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            strip = built.loc[built["Артикул"] == "PWR-1"].iloc[0]
            plug = built.loc[built["Артикул"] == "PWR-2"].iloc[0]

            self.assertEqual(strip["search_branch_path"], "удлинители, сетевые фильтры, переходники, штепсельные вилки")
            self.assertEqual(strip["search_entity_type"], "power_accessory")
            self.assertEqual(strip["search_effective_entity_type"], "power_accessory")
            self.assertEqual(strip["search_effective_family"], "power_accessory")

            self.assertEqual(plug["search_branch_path"], "удлинители, сетевые фильтры, переходники, штепсельные вилки")
            self.assertEqual(plug["search_entity_type"], "power_accessory")
            self.assertEqual(plug["search_effective_entity_type"], "power_accessory")
            self.assertEqual(plug["search_effective_family"], "power_accessory")

    def test_build_search_catalog_maps_batch_tool_plumbing_and_heating_branches_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Очки защитные закрытого типа прозрачные;GLS-1;10;Защитные Очки;CLS-1;Очки;;ReMo\n"
                    "Нутромер индикаторный 18-35 мм;BORE-1;10;Нутромеры;CLS-2;Нутромер;;ReMo\n"
                    "Набор отверток диэлектрических 6 шт;SDSET-1;10;Наборы Отверток;CLS-3;Набор отверток;;ReMo\n"
                    "Бита шестигранная HEX 5 25мм;HEXBIT-1;10;Биты Шестигранные HEX;CLS-4;Бита;;ReMo\n"
                    "Съемник двухлапый ручной 150 мм;PULL-1;10;Съемники Ручные;CLS-5;Съемник;;ReMo\n"
                    "Хомут для труб 32 мм оцинкованный;PCLAMP-1;10;Хомуты Для Труб;CLS-6;Хомут;;ReMo\n"
                    "Отвод 110 мм для наружной канализации;SEWER-1;10;Фитинги Для Наружной Канализации;CLS-7;Отвод;;ReMo\n"
                    "Сифон бутылочный для раковины 1 1/4;SIF-1;10;Сифоны;CLS-8;Сифон;;ReMo\n"
                    "Зенковка коническая 16 мм HSS;CSINK-1;10;Зенкеры И Зенковки;CLS-9;Зенковка;;ReMo\n"
                    "Нагревательный мат теплый пол 1.5 м2;HMAT-1;10;Нагревательные Маты;CLS-10;Нагревательный мат;;ReMo\n"
                    "Изоляция из вспененного полиэтилена трубная 22x9;INS-1;10;Изоляция Из Вспененного Полиэтилена Трубная;CLS-11;Изоляция трубная;;ReMo\n"
                    "Клапан обратный чугунный DN50;VALVE-2;10;Клапаны Обратные Чугунные;CLS-12;Клапан обратный;;ReMo\n"
                    "Задвижка чугунная клиновая DN80;VALVE-3;10;Задвижки Чугунные Клиновые;CLS-13;Задвижка;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            expectations = {
                "GLS-1": ("защитные очки", "safety_glasses"),
                "BORE-1": ("нутромеры", "bore_gauge"),
                "SDSET-1": ("наборы отверток", "screwdriver_set"),
                "HEXBIT-1": ("биты шестигранные HEX", "hex_bit"),
                "PULL-1": ("съемники ручные", "manual_puller"),
                "PCLAMP-1": ("хомуты для труб", "pipe_clamp"),
                "SEWER-1": ("фитинги для наружной канализации", "sewer_fitting"),
                "SIF-1": ("сифоны", "siphon"),
                "CSINK-1": ("зенкеры и зенковки", "countersink_tool"),
                "HMAT-1": ("нагревательные маты", "heating_mat"),
                "INS-1": ("изоляция из вспененного полиэтилена трубная", "pipe_insulation"),
                "VALVE-2": ("клапаны обратные чугунные", "industrial_valve"),
                "VALVE-3": ("задвижки чугунные клиновые", "industrial_valve"),
            }

            for article, (branch_path, family) in expectations.items():
                row = built.loc[built["Артикул"] == article].iloc[0]
                self.assertEqual(row["search_branch_path"], branch_path)
                self.assertEqual(row["search_entity_type"], family)
                self.assertEqual(row["search_effective_entity_type"], family)
                self.assertEqual(row["search_effective_family"], family)

    def test_build_search_catalog_maps_additional_batch_families_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Каска защитная белая с храповиком;HELM-1;10;Каски;CLS-1;Каска;;ReMo\n"
                    "Домкрат гидравлический бутылочный 10т;JACK-1;10;Домкраты;CLS-2;Домкрат;;ReMo\n"
                    "Конвектор электрический настенный 2 кВт;CONV-1;10;Конвекторы Электрические;CLS-3;Конвектор;;ReMo\n"
                    "Коллекторная группа для теплого пола на 6 выходов;MANI-1;10;Коллекторные Группы Для Теплого Пола;CLS-4;Коллектор;;ReMo\n"
                    "Смеситель для мойки однорычажный хром;FAUC-1;10;Смесители Для Мойки;CLS-5;Смеситель;;ReMo\n"
                    "УКРМ 0.4кВ 50 квар;RPC-1;10;Устройства Компенсации Реактивной Мощности 0.4кВ;CLS-6;УКРМ;;ReMo\n"
                    "Наконечник ТМЛ 16-8-6;LUG-1;10;Силовые Медные Луженые Наконечники (ТМЛ);CLS-7;Наконечник;;ReMo\n"
                    "Перемычка для клемм на DIN-рейку FBS 10;JMP-1;10;Перемычки Для Клемм На DIN-Рейку;CLS-8;Перемычка;;ReMo\n"
                    "IP-видеокамера 4 Мп уличная;IPC-1;10;IP-Видеокамеры;CLS-9;IP-видеокамера;;ReMo\n"
                    "Нож строительный сегментный 18 мм;KNF-1;10;Ножи Строительные;CLS-10;Нож строительный;;ReMo\n"
                    "Костюм сварщика брезентовый размер 52;WW-1;10;Костюмы Сварщика;CLS-11;Костюм сварщика;;ReMo\n"
                    "Фитинг шумопоглощающий для канализации 110 мм;SEW-1;10;Фитинги Шумопоглощающие Для Канализации;CLS-12;Фитинг;;ReMo\n"
                    "Саморез гипсокартон-металл 3.5x25;SCR-1;10;Саморезы Гипсокартон-Металл;CLS-13;Саморез;;ReMo\n"
                    "Корпус щита монтажный металлический ЩМП-2;ENC-1;10;Корпуса Щитов Монтажных Металлических;CLS-14;Корпус щита;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")

            expectations = {
                "HELM-1": ("каски", "protective_helmet"),
                "JACK-1": ("домкраты", "jack"),
                "CONV-1": ("конвекторы электрические", "electric_convector"),
                "MANI-1": ("коллекторные группы для теплого пола", "floor_heating_manifold"),
                "FAUC-1": ("смесители для мойки", "faucet"),
                "RPC-1": ("устройства компенсации реактивной мощности 0.4кв", "reactive_power_compensator"),
                "LUG-1": ("силовые медные луженые наконечники (тмл)", "power_terminal_lug"),
                "JMP-1": ("перемычки для клемм на din-рейку", "terminal_block_accessory"),
                "IPC-1": ("ip-видеокамеры", "ip_camera"),
                "KNF-1": ("ножи строительные", "utility_knife"),
                "WW-1": ("костюмы сварщика", "workwear"),
                "SEW-1": ("фитинги шумопоглощающие для канализации", "sewer_fitting"),
                "SCR-1": ("саморезы гипсокартон-металл", "self_tapping_screw"),
                "ENC-1": ("корпуса щитов монтажных металлических", "distribution_enclosure"),
            }

            for article, (branch_path, family) in expectations.items():
                row = built.loc[built["Артикул"] == article].iloc[0]
                self.assertEqual(row["search_branch_path"], branch_path)
                self.assertEqual(row["search_entity_type"], family)
                self.assertEqual(row["search_effective_entity_type"], family)
                self.assertEqual(row["search_effective_family"], family)

    def test_build_search_catalog_maps_floor_convectors_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Конвектор внутрипольный с вентилятором 2000мм;CONV-1;10;Конвекторы Внутрипольные;CLS-1;Конвектор внутрипольный;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            convector = built.loc[built["Артикул"] == "CONV-1"].iloc[0]

            self.assertEqual(convector["search_branch_path"], "конвекторы внутрипольные")
            self.assertEqual(convector["search_entity_type"], "floor_convector")
            self.assertEqual(convector["search_effective_entity_type"], "floor_convector")
            self.assertEqual(convector["search_effective_family"], "floor_convector")

    def test_build_search_catalog_maps_heat_shrink_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Термоусаживаемая трубка 12/6 черная;HS-1;10;Термоусаживаемые Изделия;CLS-1;Термоусаживаемая трубка;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            heat_shrink = built.loc[built["Артикул"] == "HS-1"].iloc[0]

            self.assertEqual(heat_shrink["search_branch_path"], "термоусаживаемые изделия")
            self.assertEqual(heat_shrink["search_entity_type"], "heat_shrink")
            self.assertEqual(heat_shrink["search_effective_entity_type"], "heat_shrink")
            self.assertEqual(heat_shrink["search_effective_family"], "heat_shrink")

    def test_build_search_catalog_maps_transformers_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Трансформатор напряжения понижающий низковольтный 220/24В;TR-1;10;Трансформаторы Напряжения Понижающие Низковольтные;CLS-1;Трансформатор напряжения понижающий;;ReMo\n"
                    "Трансформатор тока низковольтный 100/5А;TR-2;10;Трансформаторы Тока Низковольтные;CLS-2;Трансформатор тока;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            transformer = built.loc[built["Артикул"] == "TR-1"].iloc[0]
            current_transformer = built.loc[built["Артикул"] == "TR-2"].iloc[0]

            self.assertEqual(transformer["search_branch_path"], "трансформаторы напряжения понижающие низковольтные")
            self.assertEqual(transformer["search_entity_type"], "transformer")
            self.assertEqual(transformer["search_effective_entity_type"], "transformer")
            self.assertEqual(transformer["search_effective_family"], "transformer")

            self.assertEqual(current_transformer["search_branch_path"], "трансформаторы тока низковольтные")
            self.assertEqual(current_transformer["search_entity_type"], "transformer")
            self.assertEqual(current_transformer["search_effective_entity_type"], "transformer")
            self.assertEqual(current_transformer["search_effective_family"], "transformer")

    def test_build_search_catalog_maps_fuses_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Предохранитель плавкий 10А;FUSE-1;10;Плавкие Предохранители;CLS-1;Предохранитель плавкий;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            fuse = built.loc[built["Артикул"] == "FUSE-1"].iloc[0]

            self.assertEqual(fuse["search_branch_path"], "плавкие предохранители")
            self.assertEqual(fuse["search_entity_type"], "fuse")
            self.assertEqual(fuse["search_effective_entity_type"], "fuse")
            self.assertEqual(fuse["search_effective_family"], "fuse")

    def test_build_search_catalog_maps_ups_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Источник бесперебойного питания Line Interactive 2000VA;UPS-1;10;Источники Бесперебойного Питания (ИБП);CLS-1;Источник бесперебойного питания;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            ups = built.loc[built["Артикул"] == "UPS-1"].iloc[0]

            self.assertEqual(ups["search_branch_path"], "источники бесперебойного питания (ибп)")
            self.assertEqual(ups["search_entity_type"], "ups")
            self.assertEqual(ups["search_effective_entity_type"], "ups")
            self.assertEqual(ups["search_effective_family"], "ups")

    def test_build_search_catalog_maps_push_buttons_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Кнопка управления красная 22мм;BTN-1;10;Кнопки;CLS-1;Кнопка;;ReMo\n"
                    "Кнопочный пост ПКЕ 2 кнопки;BTN-2;10;Кнопочные Посты;CLS-2;Кнопочный пост;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            button = built.loc[built["Артикул"] == "BTN-1"].iloc[0]
            post = built.loc[built["Артикул"] == "BTN-2"].iloc[0]

            self.assertEqual(button["search_branch_path"], "кнопки")
            self.assertEqual(button["search_entity_type"], "push_button")
            self.assertEqual(button["search_effective_entity_type"], "push_button")
            self.assertEqual(button["search_effective_family"], "push_button")

            self.assertEqual(post["search_branch_path"], "кнопочные посты")
            self.assertEqual(post["search_entity_type"], "push_button")
            self.assertEqual(post["search_effective_entity_type"], "push_button")
            self.assertEqual(post["search_effective_family"], "push_button")

    def test_build_search_catalog_maps_terminal_blocks_and_signal_indicators_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Клеммный блок на DIN-рейку 2,5мм серый;TERM-1;10;Клеммные Блоки Зажимов На DIN-рейку;CLS-1;Клеммный блок;;ReMo\n"
                    "Проходная клемма на DIN-рейку 4мм;TERM-2;10;Проходные Клеммы На DIN-рейку;CLS-2;Проходная клемма;;ReMo\n"
                    "Миниклемма на DIN-рейку 2,5мм;TERM-3;10;Миниклеммы На DIN-рейку;CLS-3;Миниклемма;;ReMo\n"
                    "Арматура светосигнальная зеленая 24В;SIG-1;10;Светосигнальная Арматура;CLS-2;Арматура светосигнальная;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            terminal_block = built.loc[built["Артикул"] == "TERM-1"].iloc[0]
            feed_through = built.loc[built["Артикул"] == "TERM-2"].iloc[0]
            mini = built.loc[built["Артикул"] == "TERM-3"].iloc[0]
            signal_indicator = built.loc[built["Артикул"] == "SIG-1"].iloc[0]

            self.assertEqual(terminal_block["search_branch_path"], "клеммные блоки зажимов на din-рейку")
            self.assertEqual(terminal_block["search_entity_type"], "terminal_block")
            self.assertEqual(terminal_block["search_effective_entity_type"], "terminal_block")
            self.assertEqual(terminal_block["search_effective_family"], "terminal_block")

            self.assertEqual(feed_through["search_branch_path"], "проходные клеммы на din-рейку")
            self.assertEqual(feed_through["search_entity_type"], "terminal_block")
            self.assertEqual(feed_through["search_effective_entity_type"], "terminal_block")
            self.assertEqual(feed_through["search_effective_family"], "terminal_block")

            self.assertEqual(mini["search_branch_path"], "миниклеммы на din-рейку")
            self.assertEqual(mini["search_entity_type"], "terminal_block")
            self.assertEqual(mini["search_effective_entity_type"], "terminal_block")
            self.assertEqual(mini["search_effective_family"], "terminal_block")

            self.assertEqual(signal_indicator["search_branch_path"], "светосигнальная арматура")
            self.assertEqual(signal_indicator["search_entity_type"], "signal_indicator")
            self.assertEqual(signal_indicator["search_effective_entity_type"], "signal_indicator")
            self.assertEqual(signal_indicator["search_effective_family"], "signal_indicator")

    def test_build_search_catalog_maps_neutral_busbars_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Нулевая шина на DIN-рейку 12 групп;BUS-1;10;Нулевые Шины На DIN-Рейку;CLS-1;Шина нулевая;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            busbar = built.loc[built["Артикул"] == "BUS-1"].iloc[0]

            self.assertEqual(busbar["search_branch_path"], "нулевые шины на din-рейку")
            self.assertEqual(busbar["search_entity_type"], "neutral_busbar")
            self.assertEqual(busbar["search_effective_entity_type"], "neutral_busbar")
            self.assertEqual(busbar["search_effective_family"], "neutral_busbar")

    def test_build_search_catalog_maps_wire_ferrules_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Наконечник штыревой втулочный НШВИ 1,5-8;FER-1;10;Штыревые Втулочные Наконечники (НШВ И НШВИ);CLS-1;Наконечник втулочный;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            ferrule = built.loc[built["Артикул"] == "FER-1"].iloc[0]

            self.assertEqual(ferrule["search_branch_path"], "штыревые втулочные наконечники (ншв и ншви)")
            self.assertEqual(ferrule["search_entity_type"], "wire_ferrule")
            self.assertEqual(ferrule["search_effective_entity_type"], "wire_ferrule")
            self.assertEqual(ferrule["search_effective_family"], "wire_ferrule")

    def test_build_search_catalog_maps_rubilniki_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Рубильник ВН32 3P 63A;BRK-1;10;Рубильники;CLS-1;Рубильник;;ReMo\n"
                    "Выключатель нагрузки 3P 125A;BRK-2;10;Рубильники;CLS-2;Выключатель нагрузки;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            rubilnik = built.loc[built["Артикул"] == "BRK-1"].iloc[0]
            load_switch = built.loc[built["Артикул"] == "BRK-2"].iloc[0]

            self.assertEqual(rubilnik["search_branch_path"], "рубильники")
            self.assertEqual(rubilnik["search_entity_type"], "breaker")
            self.assertEqual(rubilnik["search_effective_entity_type"], "breaker")
            self.assertEqual(rubilnik["search_effective_family"], "breaker")

            self.assertEqual(load_switch["search_branch_path"], "рубильники")
            self.assertEqual(load_switch["search_entity_type"], "breaker")
            self.assertEqual(load_switch["search_effective_entity_type"], "breaker")
            self.assertEqual(load_switch["search_effective_family"], "breaker")

    def test_build_search_catalog_maps_surge_protectors_out_of_other(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Ограничитель импульсного перенапряжения SPD тип 2 40кА;SPD-1;10;Ограничители Импульсного Перенапряжения Силовые Модульные;CLS-1;Ограничитель импульсного перенапряжения;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            built = pd.read_csv(search_path, sep=";", encoding="utf-8")
            surge = built.loc[built["Артикул"] == "SPD-1"].iloc[0]

            self.assertEqual(surge["search_branch_path"], "ограничители импульсного перенапряжения силовые модульные")
            self.assertEqual(surge["search_entity_type"], "surge_protector")
            self.assertEqual(surge["search_effective_entity_type"], "surge_protector")
            self.assertEqual(surge["search_effective_family"], "surge_protector")

    def test_derive_branch_from_text_skips_telecom_rack_for_control_cabinet(self):
        self.assertEqual(
            derive_branch_from_text("Шкаф контрольно-пусковой"),
            "прочее",
        )

    def test_classify_item_type_splits_other_into_boxes_and_switch_wiring(self):
        self.assertEqual(
            classify_item_type("Коробка монтажная огнестойкая"),
            "box",
        )
        self.assertEqual(
            derive_branch_from_text("Коробка монтажная огнестойкая"),
            "коробки распределительные наружные",
        )
        self.assertEqual(
            classify_item_type("Аксессуары для установочных коробок"),
            "box_accessory",
        )
        self.assertEqual(
            classify_item_type("Выключатель скрытого монтажа 1-клавишный"),
            "switch_wiring",
        )
        self.assertEqual(
            derive_branch_from_text("Рамка 2-местная белая"),
            "рамки",
        )

    def test_build_search_catalog_writes_taxonomy_snapshot_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Коробка монтажная огнестойкая;BOX-1;120;Коробки распределительные наружные;CLS-1;Коробка;;ReMo\n"
                    "Рамка 2-местная белая;FRAME-1;80;Рамки;CLS-2;Рамка;;ReMo\n"
                ),
                encoding="utf-8",
            )

            build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            tree_path = get_search_taxonomy_tree_path(root)
            branch_summary_path = get_search_taxonomy_branch_summary_path(root)

            self.assertTrue(tree_path.exists())
            self.assertTrue(branch_summary_path.exists())

            snapshot = json.loads(tree_path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["catalog_stats"]["rows_total"], 2)
            self.assertIn("box", snapshot["families"])
            self.assertIn("switch_wiring", snapshot["families"])
            self.assertIn("рамки", snapshot["branches"])

            branch_df = pd.read_csv(branch_summary_path, sep=";", encoding="utf-8")
            self.assertIn("box", set(branch_df["effective_family"]))
            self.assertIn("switch_wiring", set(branch_df["effective_family"]))

    def test_ensure_search_taxonomy_snapshot_rebuilds_stale_snapshot_from_catalog(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Извещатель пожарный дымовой адресный;FIRE-1;1200;Извещатели пожарные;CLS-1;Извещатель;;ReMo\n"
                    "Пульт контроля и управления;CTRL-1;2500;Приборы приёмно-контрольные для опс;CLS-2;Пульт;;ReMo\n"
                ),
                encoding="utf-8",
            )

            search_path = build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            tree_path = get_search_taxonomy_tree_path(root)
            branch_summary_path = get_search_taxonomy_branch_summary_path(root)

            tree_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2000-01-01T00:00:00+00:00",
                        "family_count": 1,
                        "branch_count": 1,
                        "families": {"legacy": {"default_branches": []}},
                        "branches": {},
                        "catalog_stats": {"rows_total": 1, "family_counts": [], "top_branches": []},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            branch_summary_path.write_text(
                "search_branch_path;branch_total_rows;effective_family;rows_count;family_share_within_branch\nlegacy;1;legacy;1;1.0\n",
                encoding="utf-8",
            )

            stale_mtime = search_path.stat().st_mtime - 10
            os.utime(tree_path, (stale_mtime, stale_mtime))
            os.utime(branch_summary_path, (stale_mtime, stale_mtime))

            refreshed_tree_path, refreshed_summary_path = ensure_search_taxonomy_snapshot(root)

            self.assertEqual(refreshed_tree_path, tree_path)
            self.assertEqual(refreshed_summary_path, branch_summary_path)

            snapshot = json.loads(tree_path.read_text(encoding="utf-8"))
            self.assertIn("fire_detector", snapshot["families"])
            self.assertIn("security_control_panel", snapshot["families"])
            self.assertEqual(snapshot["catalog_stats"]["rows_total"], 2)

            branch_df = pd.read_csv(branch_summary_path, sep=";", encoding="utf-8")
            self.assertIn("fire_detector", set(branch_df["effective_family"]))
            self.assertIn("security_control_panel", set(branch_df["effective_family"]))

    def test_build_search_taxonomy_preview_writes_preview_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Извещатель пожарный дымовой адресный;FIRE-1;1200;Извещатели пожарные;CLS-1;Извещатель;;ReMo\n"
                    "Пульт контроля и управления;CTRL-1;2500;Приборы приёмно-контрольные для опс;CLS-2;Пульт;;ReMo\n"
                    "Кабель интерфейсный RS-485;IF-1;800;Кабели интерфейсные;CLS-3;Кабель;;ReMo\n"
                ),
                encoding="utf-8",
            )

            tree_path, summary_path, audit_path = build_search_taxonomy_preview(root)

            self.assertEqual(tree_path, get_search_taxonomy_preview_tree_path(root))
            self.assertEqual(summary_path, get_search_taxonomy_preview_branch_summary_path(root))
            self.assertEqual(audit_path, get_search_taxonomy_preview_audit_path(root))
            self.assertTrue(tree_path.exists())
            self.assertTrue(summary_path.exists())
            self.assertTrue(audit_path.exists())

            snapshot = json.loads(tree_path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["catalog_stats"]["mode"], "preview")
            self.assertEqual(snapshot["catalog_stats"]["rows_total"], 3)
            self.assertIn("fire_detector", snapshot["families"])

            summary_df = pd.read_csv(summary_path, sep=";", encoding="utf-8")
            self.assertIn("effective_family", summary_df.columns)
            self.assertIn("fire_detector", set(summary_df["effective_family"]))

            audit_df = pd.read_csv(audit_path, sep=";", encoding="utf-8")
            self.assertIn("search_branch_path", audit_df.columns)
            self.assertIn("suspicious_score", audit_df.columns)

    def test_build_search_taxonomy_branch_probe_writes_probe_artifacts_for_selected_branches(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            merged_path = root / "price_clean_merged.csv"
            merged_path.write_text(
                (
                    "Наименование;Артикул;Цена розничная;Название класса;Код класса;Тип изделия;"
                    "Тип исполнения кабельного изделия;Производитель\n"
                    "Выключатель автоматический модульный 1P 16A;BR-1;10;Автоматические выключатели модульные;CLS-1;Выключатель автоматический;;ReMo\n"
                    "Светильник светодиодный консольный 100Вт;LGT-1;10;Светильники наружные;CLS-2;Светильник;;ReMo\n"
                    "Кабель интерфейсный RS-485;IF-1;10;Кабели интерфейсные;CLS-3;Кабель;;ReMo\n"
                ),
                encoding="utf-8",
            )

            build_search_catalog_from_merged(merged_path, get_search_catalog_csv_path(root))
            tree_path, summary_path, audit_path = build_search_taxonomy_branch_probe(
                root,
                ["свет > светильники", "электрика > автоматы > модульные"],
            )

            self.assertEqual(tree_path, get_search_taxonomy_probe_tree_path(root))
            self.assertEqual(summary_path, get_search_taxonomy_probe_branch_summary_path(root))
            self.assertEqual(audit_path, get_search_taxonomy_probe_audit_path(root))
            report_path = get_search_taxonomy_probe_report_path(root)
            self.assertTrue(tree_path.exists())
            self.assertTrue(summary_path.exists())
            self.assertTrue(audit_path.exists())
            self.assertTrue(report_path.exists())

            snapshot = json.loads(tree_path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["catalog_stats"]["mode"], "branch_probe")
            self.assertEqual(
                set(snapshot["catalog_stats"]["selected_branches"]),
                {"свет > светильники", "электрика > автоматы > модульные"},
            )

            summary_df = pd.read_csv(summary_path, sep=";", encoding="utf-8")
            self.assertEqual(
                set(summary_df["search_branch_path"]),
                {"свет > светильники", "электрика > автоматы > модульные"},
            )

            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report_payload["mode"], "branch_probe_report")
            self.assertIn("branches", report_payload)
            self.assertIn("suspicious_branches", report_payload)

    def test_build_search_taxonomy_bootstrap_draft_uses_branch_probe_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            search_path = get_search_catalog_csv_path(root)
            pd.DataFrame(
                [
                    {
                        "Наименование": "Крышка для кабельного лотка 100мм",
                        "Артикул": "TR-1",
                        "Цена розничная": 10,
                        "Название класса": "Крышки Для Кабельных Лотков Оцинкованные",
                        "Код класса": "CLS-1",
                        "Тип изделия": "Крышка",
                        "Тип исполнения кабельного изделия": "",
                        "Производитель": "ReMo",
                        "search_branch_path": "крышки для кабельных лотков оцинкованные",
                        "search_branch_leaf": "крышки для кабельных лотков оцинкованные",
                        "search_normalized_name": "крышка для кабельного лотка 100мм",
                        "search_tokens_json": "[]",
                        "search_entity_type": "tray_sheet",
                        "search_effective_family": "rack_accessory_strict",
                        "search_effective_entity_type": "rack_accessory_strict",
                        "search_item_markers_json": "{}",
                    },
                    {
                        "Наименование": "Лоток листовой 100х50",
                        "Артикул": "TR-2",
                        "Цена розничная": 10,
                        "Название класса": "Крышки Для Кабельных Лотков Оцинкованные",
                        "Код класса": "CLS-1",
                        "Тип изделия": "Лоток",
                        "Тип исполнения кабельного изделия": "",
                        "Производитель": "ReMo",
                        "search_branch_path": "крышки для кабельных лотков оцинкованные",
                        "search_branch_leaf": "крышки для кабельных лотков оцинкованные",
                        "search_normalized_name": "лоток листовой 100х50",
                        "search_tokens_json": "[]",
                        "search_entity_type": "tray_sheet",
                        "search_effective_family": "tray_sheet",
                        "search_effective_entity_type": "tray_sheet",
                        "search_item_markers_json": "{}",
                    },
                ]
            ).to_csv(search_path, sep=";", encoding="utf-8", index=False)

            get_search_taxonomy_probe_tree_path(root).write_text(
                json.dumps(
                    {
                        "catalog_stats": {
                            "mode": "branch_probe",
                            "source_path": str(search_path),
                            "selected_branches": ["крышки для кабельных лотков оцинкованные"],
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "крышки для кабельных лотков оцинкованные",
                        "branch_total_rows": 2,
                        "effective_family": "rack_accessory_strict",
                        "rows_count": 1,
                        "family_share_within_branch": 0.5,
                    },
                    {
                        "search_branch_path": "крышки для кабельных лотков оцинкованные",
                        "branch_total_rows": 2,
                        "effective_family": "tray_sheet",
                        "rows_count": 1,
                        "family_share_within_branch": 0.5,
                    },
                ]
            ).to_csv(get_search_taxonomy_probe_branch_summary_path(root), sep=";", encoding="utf-8", index=False)
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "крышки для кабельных лотков оцинкованные",
                        "branch_total_rows": 2,
                        "family_count": 2,
                        "top_family": "rack_accessory_strict",
                        "top_family_rows": 1,
                        "top_family_share": 0.5,
                        "second_family": "tray_sheet",
                        "second_family_rows": 1,
                        "second_family_share": 0.5,
                        "other_rows": 0,
                        "other_share": 0.0,
                        "suspicious_score": 1.0,
                        "top_families": "rack_accessory_strict (1) | tray_sheet (1)",
                    }
                ]
            ).to_csv(get_search_taxonomy_probe_audit_path(root), sep=";", encoding="utf-8", index=False)

            json_path, csv_path = build_search_taxonomy_bootstrap_draft(
                root,
                api_key="test",
                max_branches=1,
                generate_text=lambda _prompt: json.dumps(
                    {
                        "branches": [
                            {
                                "search_branch_path": "крышки для кабельных лотков оцинкованные",
                                "suggested_family": "rack_accessory_strict",
                                "suggested_subfamily": "tray_cover",
                                "suggested_action": "tighten_family_mapping",
                                "confidence": 0.93,
                                "rationale": "Крышки для лотков ближе к аксессуарам трассы, а не к самому лотку.",
                                "evidence_tokens": ["крышки", "лотков", "крышка"],
                                "notes": "Хороший кандидат на отдельный subfamily.",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            )

            self.assertEqual(json_path, get_search_taxonomy_bootstrap_draft_json_path(root))
            self.assertEqual(csv_path, get_search_taxonomy_bootstrap_draft_csv_path(root))
            self.assertTrue(json_path.exists())
            self.assertTrue(csv_path.exists())

            draft_payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(draft_payload["mode"], "branch_probe_bootstrap_draft")
            self.assertEqual(draft_payload["selected_branches"], ["крышки для кабельных лотков оцинкованные"])

            draft_df = pd.read_csv(csv_path, sep=";", encoding="utf-8")
            self.assertEqual(len(draft_df), 1)
            self.assertEqual(draft_df.at[0, "suggested_family"], "rack_accessory_strict")
            self.assertEqual(draft_df.at[0, "suggested_subfamily"], "tray_cover")

    def test_build_search_taxonomy_bootstrap_draft_aligns_branch_names_and_keeps_split_branch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            search_path = get_search_catalog_csv_path(root)
            pd.DataFrame(
                [
                    {
                        "Наименование": "Demo cable tray cover 100",
                        "Артикул": "D-1",
                        "Цена розничная": 10,
                        "Название класса": "Demo Tray Covers",
                        "Код класса": "CLS-1",
                        "Тип изделия": "Cover",
                        "Тип исполнения кабельного изделия": "",
                        "Производитель": "ReMo",
                        "search_branch_path": "demo > cable tray covers",
                        "search_branch_leaf": "cable tray covers",
                        "search_normalized_name": "demo cable tray cover 100",
                        "search_tokens_json": "[]",
                        "search_entity_type": "rack_accessory_strict",
                        "search_effective_family": "rack_accessory_strict",
                        "search_effective_entity_type": "rack_accessory_strict",
                        "search_item_markers_json": "{}",
                    }
                ]
            ).to_csv(search_path, sep=";", encoding="utf-8", index=False)

            get_search_taxonomy_probe_tree_path(root).write_text(
                json.dumps(
                    {
                        "catalog_stats": {
                            "mode": "branch_probe",
                            "source_path": str(search_path),
                            "selected_branches": ["demo > cable tray covers"],
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "demo > cable tray covers",
                        "branch_total_rows": 100,
                        "effective_family": "rack_accessory_strict",
                        "rows_count": 55,
                        "family_share_within_branch": 0.55,
                    },
                    {
                        "search_branch_path": "demo > cable tray covers",
                        "branch_total_rows": 100,
                        "effective_family": "tray_sheet",
                        "rows_count": 45,
                        "family_share_within_branch": 0.45,
                    },
                ]
            ).to_csv(get_search_taxonomy_probe_branch_summary_path(root), sep=";", encoding="utf-8", index=False)
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "demo > cable tray covers",
                        "branch_total_rows": 100,
                        "family_count": 2,
                        "top_family": "rack_accessory_strict",
                        "top_family_rows": 55,
                        "top_family_share": 0.55,
                        "second_family": "tray_sheet",
                        "second_family_rows": 45,
                        "second_family_share": 0.45,
                        "other_rows": 0,
                        "other_share": 0.0,
                        "suspicious_score": 45.0,
                        "top_families": "rack_accessory_strict (55) | tray_sheet (45)",
                    }
                ]
            ).to_csv(get_search_taxonomy_probe_audit_path(root), sep=";", encoding="utf-8", index=False)

            _, csv_path = build_search_taxonomy_bootstrap_draft(
                root,
                api_key="test",
                max_branches=1,
                generate_text=lambda _prompt: json.dumps(
                    {
                        "branches": [
                            {
                                "search_branch_path": "demo > cable tray covers !!!",
                                "suggested_family": "",
                                "suggested_subfamily": "",
                                "suggested_action": "split_branch",
                                "confidence": 0.88,
                                "rationale": "Branch is mixed and should be split into narrower tray cover groups.",
                                "evidence_tokens": ["cover", "tray", "mixed"],
                                "notes": "Do not force one family onto the full branch.",
                            }
                        ]
                    }
                ),
            )

            draft_df = pd.read_csv(csv_path, sep=";", encoding="utf-8")
            self.assertEqual(draft_df.at[0, "response_branch_path"], "demo > cable tray covers !!!")
            self.assertEqual(draft_df.at[0, "branch_match_method"], "normalized_exact")
            self.assertEqual(draft_df.at[0, "suggested_action"], "split_branch")
            self.assertTrue(pd.isna(draft_df.at[0, "suggested_family"]) or draft_df.at[0, "suggested_family"] == "")
            self.assertTrue(str(draft_df.at[0, "sample_rows"]).strip())

    def test_build_search_taxonomy_bootstrap_draft_forces_split_branch_for_wide_mixed_branch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            get_search_taxonomy_probe_tree_path(root).write_text(
                json.dumps(
                    {
                        "catalog_stats": {
                            "mode": "branch_probe",
                            "source_path": "",
                            "selected_branches": ["electrics > cables"],
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "electrics > cables",
                        "branch_total_rows": 52000,
                        "effective_family": "cable",
                        "rows_count": 44720,
                        "family_share_within_branch": 0.86,
                        "sample_names_json": "[\"Power cable 3x2.5\"]",
                        "sample_rows_json": "[\"Power cable 3x2.5 | class=Power Cables | type=Cable | article=C-1\"]",
                        "top_class_names_json": "[\"Power Cables\", \"Cable Tray Angles\"]",
                        "top_item_types_json": "[\"Cable\", \"Angle\"]",
                        "top_articles_json": "[\"C-1\"]",
                    },
                    {
                        "search_branch_path": "electrics > cables",
                        "branch_total_rows": 52000,
                        "effective_family": "rack_accessory_strict",
                        "rows_count": 2080,
                        "family_share_within_branch": 0.04,
                        "sample_names_json": "[\"Power cable 3x2.5\"]",
                        "sample_rows_json": "[\"Power cable 3x2.5 | class=Power Cables | type=Cable | article=C-1\"]",
                        "top_class_names_json": "[\"Power Cables\", \"Cable Tray Angles\"]",
                        "top_item_types_json": "[\"Cable\", \"Angle\"]",
                        "top_articles_json": "[\"C-1\"]",
                    },
                ]
            ).to_csv(get_search_taxonomy_probe_branch_summary_path(root), sep=";", encoding="utf-8", index=False)
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "electrics > cables",
                        "branch_total_rows": 52000,
                        "family_count": 7,
                        "top_family": "cable",
                        "top_family_rows": 44720,
                        "top_family_share": 0.86,
                        "second_family": "rack_accessory_strict",
                        "second_family_rows": 2080,
                        "second_family_share": 0.04,
                        "other_rows": 520,
                        "other_share": 0.01,
                        "suspicious_score": 14.0,
                        "top_families": "cable (44720) | rack_accessory_strict (2080)",
                    }
                ]
            ).to_csv(get_search_taxonomy_probe_audit_path(root), sep=";", encoding="utf-8", index=False)

            _, csv_path = build_search_taxonomy_bootstrap_draft(
                root,
                api_key="test",
                max_branches=1,
                generate_text=lambda _prompt: json.dumps(
                    {
                        "branches": [
                            {
                                "search_branch_path": "electrics > cables",
                                "suggested_family": "cable",
                                "suggested_subfamily": "power_cable",
                                "suggested_action": "tighten_family_mapping",
                                "confidence": 0.9,
                                "rationale": "Most rows are power cables.",
                                "evidence_tokens": ["cable", "power", "3x2.5"],
                                "notes": "Looks mostly like one cable family.",
                            }
                        ]
                    }
                ),
            )

            draft_df = pd.read_csv(csv_path, sep=";", encoding="utf-8")
            self.assertEqual(draft_df.at[0, "suggested_action"], "split_branch")
            self.assertEqual(draft_df.at[0, "backend_guardrail"], "force_split_branch")
            self.assertTrue(bool(draft_df.at[0, "split_branch_required"]))
            self.assertIn("wide_mixed_branch", str(draft_df.at[0, "split_branch_reason"]))
            self.assertTrue(pd.isna(draft_df.at[0, "suggested_family"]) or draft_df.at[0, "suggested_family"] == "")
            self.assertTrue(pd.isna(draft_df.at[0, "suggested_subfamily"]) or draft_df.at[0, "suggested_subfamily"] == "")

    def test_build_search_taxonomy_bootstrap_draft_supports_new_family_for_other_branch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            get_search_taxonomy_probe_tree_path(root).write_text(
                json.dumps(
                    {
                        "catalog_stats": {
                            "mode": "branch_probe",
                            "source_path": "",
                            "selected_branches": ["industrial > roller bearings"],
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "industrial > roller bearings",
                        "branch_total_rows": 14948,
                        "effective_family": "other",
                        "rows_count": 14484,
                        "family_share_within_branch": 0.968959,
                        "sample_names_json": "[\"Подшипник 32214 КМ FBC\"]",
                        "sample_rows_json": "[\"Подшипник 32214 КМ FBC | class=Подшипники Роликовые Цилиндрические | type=Подшипник роликовый цилиндрический | article=00-1\"]",
                        "top_class_names_json": "[\"Подшипники Роликовые Цилиндрические\"]",
                        "top_item_types_json": "[\"Подшипник роликовый цилиндрический\", \"Подшипник корпусный\"]",
                        "top_articles_json": "[\"00-1\"]",
                    },
                    {
                        "search_branch_path": "industrial > roller bearings",
                        "branch_total_rows": 14948,
                        "effective_family": "fastener",
                        "rows_count": 330,
                        "family_share_within_branch": 0.022077,
                        "sample_names_json": "[\"Подшипник 32214 КМ FBC\"]",
                        "sample_rows_json": "[\"Подшипник 32214 КМ FBC | class=Подшипники Роликовые Цилиндрические | type=Подшипник роликовый цилиндрический | article=00-1\"]",
                        "top_class_names_json": "[\"Подшипники Роликовые Цилиндрические\"]",
                        "top_item_types_json": "[\"Подшипник роликовый цилиндрический\", \"Подшипник корпусный\"]",
                        "top_articles_json": "[\"00-1\"]",
                    },
                ]
            ).to_csv(get_search_taxonomy_probe_branch_summary_path(root), sep=";", encoding="utf-8", index=False)
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "industrial > roller bearings",
                        "branch_total_rows": 14948,
                        "family_count": 3,
                        "top_family": "other",
                        "top_family_rows": 14484,
                        "top_family_share": 0.968959,
                        "second_family": "fastener",
                        "second_family_rows": 330,
                        "second_family_share": 0.022077,
                        "other_rows": 14484,
                        "other_share": 0.968959,
                        "suspicious_score": 464.0,
                        "top_families": "other (14484) | fastener (330)",
                    }
                ]
            ).to_csv(get_search_taxonomy_probe_audit_path(root), sep=";", encoding="utf-8", index=False)

            _, csv_path = build_search_taxonomy_bootstrap_draft(
                root,
                api_key="test",
                max_branches=1,
                generate_text=lambda _prompt: json.dumps(
                    {
                        "branches": [
                            {
                                "search_branch_path": "industrial > roller bearings",
                                "suggested_family": "",
                                "suggested_subfamily": "",
                                "suggested_action": "new_family",
                                "proposed_family_key": "bearing",
                                "proposed_family_label": "Bearings",
                                "proposed_subfamily_key": "roller_bearing",
                                "confidence": 0.94,
                                "rationale": "This branch is a coherent mechanical product group and should become its own family instead of staying in other.",
                                "evidence_tokens": ["подшипник", "роликовый", "цилиндрический"],
                                "notes": "Good candidate for taxonomy expansion.",
                            }
                        ]
                    }
                ),
            )

            draft_df = pd.read_csv(csv_path, sep=";", encoding="utf-8")
            self.assertTrue(bool(draft_df.at[0, "taxonomy_gap_candidate"]))
            self.assertIn("taxonomy_gap_candidate", str(draft_df.at[0, "taxonomy_gap_reason"]))
            self.assertEqual(draft_df.at[0, "suggested_action"], "new_family")
            self.assertEqual(draft_df.at[0, "proposed_family_key"], "bearing")
            self.assertEqual(draft_df.at[0, "proposed_family_label"], "Bearings")
            self.assertEqual(draft_df.at[0, "proposed_subfamily_key"], "roller_bearing")
            self.assertTrue(pd.isna(draft_df.at[0, "suggested_family"]) or draft_df.at[0, "suggested_family"] == "")

    def test_build_search_taxonomy_bootstrap_draft_includes_clean_leaf_branches_from_probe_summary(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            get_search_taxonomy_probe_tree_path(root).write_text(
                json.dumps(
                    {
                        "catalog_stats": {
                            "mode": "branch_probe",
                            "source_path": "",
                            "selected_branches": ["электрика > кабели"],
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "электрика > кабели",
                        "branch_total_rows": 52000,
                        "effective_family": "cable",
                        "rows_count": 44720,
                        "family_share_within_branch": 0.86,
                        "sample_names_json": "[\"Кабель ВВГнг-LS 3x2.5\"]",
                        "sample_rows_json": "[\"Кабель ВВГнг-LS 3x2.5 | class=Силовые кабели | type=Кабель | article=C-1\"]",
                        "top_class_names_json": "[\"Силовые кабели\"]",
                        "top_item_types_json": "[\"Кабель\"]",
                        "top_articles_json": "[\"C-1\"]",
                    },
                    {
                        "search_branch_path": "перфорированные кабель-каналы",
                        "branch_total_rows": 4200,
                        "effective_family": "cable_channel",
                        "rows_count": 4090,
                        "family_share_within_branch": 0.9738,
                        "sample_names_json": "[\"Короб перфорированный 40x40 серый\"]",
                        "sample_rows_json": "[\"Короб перфорированный 40x40 серый | class=Перфорированные Кабель-Каналы | type=Короб перфорированный | article=DUCT-1\"]",
                        "top_class_names_json": "[\"Перфорированные Кабель-Каналы\"]",
                        "top_item_types_json": "[\"Короб перфорированный\"]",
                        "top_articles_json": "[\"DUCT-1\"]",
                    },
                ]
            ).to_csv(get_search_taxonomy_probe_branch_summary_path(root), sep=";", encoding="utf-8", index=False)
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "электрика > кабели",
                        "branch_total_rows": 52000,
                        "family_count": 7,
                        "top_family": "cable",
                        "top_family_rows": 44720,
                        "top_family_share": 0.86,
                        "second_family": "rack_accessory_strict",
                        "second_family_rows": 2080,
                        "second_family_share": 0.04,
                        "other_rows": 520,
                        "other_share": 0.01,
                        "suspicious_score": 14.0,
                        "top_families": "cable (44720) | rack_accessory_strict (2080)",
                    }
                ]
            ).to_csv(get_search_taxonomy_probe_audit_path(root), sep=";", encoding="utf-8", index=False)

            _, csv_path = build_search_taxonomy_bootstrap_draft(
                root,
                api_key="test",
                max_branches=2,
                generate_text=lambda _prompt: json.dumps(
                    {
                        "branches": [
                            {
                                "search_branch_path": "электрика > кабели",
                                "suggested_family": "",
                                "suggested_subfamily": "",
                                "suggested_action": "split_branch",
                                "confidence": 0.9,
                                "rationale": "Wide mixed branch.",
                                "evidence_tokens": ["кабель", "mixed"],
                                "notes": "",
                            },
                            {
                                "search_branch_path": "перфорированные кабель-каналы",
                                "suggested_family": "cable_channel",
                                "suggested_subfamily": "perforated_cable_channel",
                                "suggested_action": "tighten_family_mapping",
                                "confidence": 0.94,
                                "rationale": "Clean cable channel branch.",
                                "evidence_tokens": ["перфорированный", "кабель-канал"],
                                "notes": "",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
            )

            draft_df = pd.read_csv(csv_path, sep=";", encoding="utf-8")
            self.assertEqual(
                draft_df["search_branch_path"].tolist(),
                ["электрика > кабели", "перфорированные кабель-каналы"],
            )

    def test_build_search_taxonomy_bootstrap_draft_prioritizes_selected_probe_roots_before_audit_tail(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            get_search_taxonomy_probe_tree_path(root).write_text(
                json.dumps(
                    {
                        "catalog_stats": {
                            "mode": "branch_probe",
                            "source_path": "",
                            "selected_branches": ["Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ðµ ÐºÐ°Ð±ÐµÐ»ÑŒ-ÐºÐ°Ð½Ð°Ð»Ñ‹"],
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ðµ ÐºÐ°Ð±ÐµÐ»ÑŒ-ÐºÐ°Ð½Ð°Ð»Ñ‹",
                        "branch_total_rows": 4200,
                        "effective_family": "cable_channel",
                        "rows_count": 4090,
                        "family_share_within_branch": 0.9738,
                        "sample_names_json": "[\"ÐšÐ¾Ñ€Ð¾Ð± Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ð¹ 40x40 ÑÐµÑ€Ñ‹Ð¹\"]",
                        "sample_rows_json": "[\"ÐšÐ¾Ñ€Ð¾Ð± Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ð¹ 40x40 ÑÐµÑ€Ñ‹Ð¹ | class=ÐŸÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ðµ ÐšÐ°Ð±ÐµÐ»ÑŒ-ÐšÐ°Ð½Ð°Ð»Ñ‹ | type=ÐšÐ¾Ñ€Ð¾Ð± Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ð¹ | article=DUCT-1\"]",
                        "top_class_names_json": "[\"ÐŸÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ðµ ÐšÐ°Ð±ÐµÐ»ÑŒ-ÐšÐ°Ð½Ð°Ð»Ñ‹\"]",
                        "top_item_types_json": "[\"ÐšÐ¾Ñ€Ð¾Ð± Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ð¹\"]",
                        "top_articles_json": "[\"DUCT-1\"]",
                    },
                    {
                        "search_branch_path": "ÐºÑ€Ð°Ð½Ñ‹ ÑˆÐ°Ñ€Ð¾Ð²Ñ‹Ðµ ÑÑ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ",
                        "branch_total_rows": 19008,
                        "effective_family": "other",
                        "rows_count": 18950,
                        "family_share_within_branch": 0.997,
                        "sample_names_json": "[\"ÐšÑ€Ð°Ð½ ÑˆÐ°Ñ€Ð¾Ð²Ð¾Ð¹ ÑÑ‚Ð°Ð»ÑŒÐ½Ð¾Ð¹ DN50\"]",
                        "sample_rows_json": "[\"ÐšÑ€Ð°Ð½ ÑˆÐ°Ñ€Ð¾Ð²Ð¾Ð¹ ÑÑ‚Ð°Ð»ÑŒÐ½Ð¾Ð¹ DN50 | class=ÐšÑ€Ð°Ð½Ñ‹ Ð¨Ð°Ñ€Ð¾Ð²Ñ‹Ðµ Ð¡Ñ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ | type=ÐšÑ€Ð°Ð½ | article=VALVE-2\"]",
                        "top_class_names_json": "[\"ÐšÑ€Ð°Ð½Ñ‹ Ð¨Ð°Ñ€Ð¾Ð²Ñ‹Ðµ Ð¡Ñ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ\"]",
                        "top_item_types_json": "[\"ÐšÑ€Ð°Ð½\"]",
                        "top_articles_json": "[\"VALVE-2\"]",
                    },
                ]
            ).to_csv(get_search_taxonomy_probe_branch_summary_path(root), sep=";", encoding="utf-8", index=False)
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "Ð·Ð°Ñ‚Ð²Ð¾Ñ€Ñ‹ Ð¿Ð¾Ð²Ð¾Ñ€Ð¾Ñ‚Ð½Ñ‹Ðµ Ð´Ð¸ÑÐºÐ¾Ð²Ñ‹Ðµ ÑÑ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ",
                        "branch_total_rows": 20000,
                        "family_count": 1,
                        "top_family": "other",
                        "top_family_rows": 19999,
                        "top_family_share": 0.999,
                        "second_family": "",
                        "second_family_rows": 0,
                        "second_family_share": 0.0,
                        "other_rows": 19999,
                        "other_share": 0.999,
                        "suspicious_score": 999.0,
                        "top_families": "other (19999)",
                    }
                ]
            ).to_csv(get_search_taxonomy_probe_audit_path(root), sep=";", encoding="utf-8", index=False)

            _, csv_path = build_search_taxonomy_bootstrap_draft(
                root,
                api_key="test",
                max_branches=1,
                generate_text=lambda _prompt: json.dumps(
                    {
                        "branches": [
                            {
                                "search_branch_path": "Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ðµ ÐºÐ°Ð±ÐµÐ»ÑŒ-ÐºÐ°Ð½Ð°Ð»Ñ‹",
                                "suggested_family": "cable_channel",
                                "suggested_subfamily": "perforated_cable_channel",
                                "suggested_action": "tighten_family_mapping",
                                "confidence": 0.96,
                                "rationale": "Selected clean probe root must be kept ahead of audit tail.",
                                "evidence_tokens": ["Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ð¹", "ÐºÐ°Ð±ÐµÐ»ÑŒ-ÐºÐ°Ð½Ð°Ð»"],
                                "notes": "",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            )

            draft_df = pd.read_csv(csv_path, sep=";", encoding="utf-8")
            self.assertEqual(draft_df["search_branch_path"].tolist(), ["Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ðµ ÐºÐ°Ð±ÐµÐ»ÑŒ-ÐºÐ°Ð½Ð°Ð»Ñ‹"])

    def test_build_search_taxonomy_branch_probe_keeps_context_for_reclassified_leaf_branches(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            search_path = get_search_catalog_csv_path(root)
            pd.DataFrame(
                [
                    {
                        "Наименование": "Угол внутренний 25x17 коричневый AIM",
                        "Артикул": "CC-1",
                        "Цена розничная": 10,
                        "Название класса": "Углы Для Кабель-Каналов",
                        "Код класса": "CLS-1",
                        "Тип изделия": "Угол внутренний",
                        "Тип исполнения кабельного изделия": "",
                        "Производитель": "ReMo",
                        "search_branch_path": "электрика > кабели",
                        "search_branch_leaf": "кабели",
                        "search_normalized_name": "угол внутренний 25x17 коричневый aim",
                        "search_tokens_json": "[]",
                        "search_entity_type": "cable",
                        "search_effective_family": "cable",
                        "search_effective_entity_type": "cable",
                        "search_item_markers_json": "{}",
                    }
                ]
            ).to_csv(search_path, sep=";", encoding="utf-8", index=False)

            _, summary_path, _ = build_search_taxonomy_branch_probe(root, ["электрика > кабели"])
            summary_df = pd.read_csv(summary_path, sep=";", encoding="utf-8")

            leaf_row = summary_df.loc[summary_df["search_branch_path"] == "углы для кабель-каналов"].iloc[0]
            self.assertTrue(str(leaf_row["sample_names_json"]).strip())
            self.assertTrue(str(leaf_row["sample_rows_json"]).strip())
            self.assertTrue(str(leaf_row["top_class_names_json"]).strip())
            self.assertTrue(str(leaf_row["top_item_types_json"]).strip())

    def test_build_search_taxonomy_branch_probe_includes_related_leaf_branches_for_selected_root_branch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            search_path = get_search_catalog_csv_path(root)
            pd.DataFrame(
                [
                    {
                        "Наименование": "Короб перфорированный 40x40 серый",
                        "Артикул": "DUCT-1",
                        "Цена розничная": 10,
                        "Название класса": "Перфорированные Кабель-Каналы",
                        "Код класса": "CLS-1",
                        "Тип изделия": "Короб перфорированный",
                        "Тип исполнения кабельного изделия": "",
                        "Производитель": "ReMo",
                        "search_branch_path": "перфорированные кабель-каналы",
                        "search_branch_leaf": "перфорированные кабель-каналы",
                        "search_normalized_name": "короб перфорированный 40x40 серый",
                        "search_tokens_json": "[]",
                        "search_entity_type": "cable_channel",
                        "search_effective_family": "cable_channel",
                        "search_effective_entity_type": "cable_channel",
                        "search_item_markers_json": "{\"installation_kind\": \"cable_channel\"}",
                    },
                    {
                        "Наименование": "Патч-корд UTP cat6 1м",
                        "Артикул": "PATCH-1",
                        "Цена розничная": 10,
                        "Название класса": "Патч-Корды",
                        "Код класса": "CLS-2",
                        "Тип изделия": "Патч-корд",
                        "Тип исполнения кабельного изделия": "",
                        "Производитель": "ReMo",
                        "search_branch_path": "телеком > кабели > патч корды",
                        "search_branch_leaf": "патч корды",
                        "search_normalized_name": "патч корд utp cat6 1м",
                        "search_tokens_json": "[]",
                        "search_entity_type": "patch_cord",
                        "search_effective_family": "patch_cord",
                        "search_effective_entity_type": "patch_cord",
                        "search_item_markers_json": "{}",
                    },
                ]
            ).to_csv(search_path, sep=";", encoding="utf-8", index=False)

            _, summary_path, _ = build_search_taxonomy_branch_probe(root, ["электрика > кабели"])
            summary_df = pd.read_csv(summary_path, sep=";", encoding="utf-8")

            self.assertIn("перфорированные кабель-каналы", summary_df["search_branch_path"].tolist())
            self.assertNotIn("телеком > кабели > патч корды", summary_df["search_branch_path"].tolist())

    def test_build_search_taxonomy_branch_probe_does_not_overexpand_flat_industrial_branches(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            search_path = get_search_catalog_csv_path(root)
            pd.DataFrame(
                [
                    {
                        "ÐÐ°Ð¸Ð¼ÐµÐ½Ð¾Ð²Ð°Ð½Ð¸Ðµ": "Ð—Ð°Ñ‚Ð²Ð¾Ñ€ Ð¿Ð¾Ð²Ð¾Ñ€Ð¾Ñ‚Ð½Ñ‹Ð¹ Ð´Ð¸ÑÐºÐ¾Ð²Ñ‹Ð¹ ÑÑ‚Ð°Ð»ÑŒÐ½Ð¾Ð¹ DN100",
                        "ÐÑ€Ñ‚Ð¸ÐºÑƒÐ»": "VALVE-1",
                        "Ð¦ÐµÐ½Ð° Ñ€Ð¾Ð·Ð½Ð¸Ñ‡Ð½Ð°Ñ": 10,
                        "ÐÐ°Ð·Ð²Ð°Ð½Ð¸Ðµ ÐºÐ»Ð°ÑÑÐ°": "Ð—Ð°Ñ‚Ð²Ð¾Ñ€Ñ‹ ÐŸÐ¾Ð²Ð¾Ñ€Ð¾Ñ‚Ð½Ñ‹Ðµ Ð”Ð¸ÑÐºÐ¾Ð²Ñ‹Ðµ Ð¡Ñ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ",
                        "ÐšÐ¾Ð´ ÐºÐ»Ð°ÑÑÐ°": "CLS-1",
                        "Ð¢Ð¸Ð¿ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ": "Ð—Ð°Ñ‚Ð²Ð¾Ñ€",
                        "Ð¢Ð¸Ð¿ Ð¸ÑÐ¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ ÐºÐ°Ð±ÐµÐ»ÑŒÐ½Ð¾Ð³Ð¾ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ": "",
                        "ÐŸÑ€Ð¾Ð¸Ð·Ð²Ð¾Ð´Ð¸Ñ‚ÐµÐ»ÑŒ": "ReMo",
                        "search_branch_path": "Ð·Ð°Ñ‚Ð²Ð¾Ñ€Ñ‹ Ð¿Ð¾Ð²Ð¾Ñ€Ð¾Ñ‚Ð½Ñ‹Ðµ Ð´Ð¸ÑÐºÐ¾Ð²Ñ‹Ðµ ÑÑ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ",
                        "search_branch_leaf": "Ð·Ð°Ñ‚Ð²Ð¾Ñ€Ñ‹ Ð¿Ð¾Ð²Ð¾Ñ€Ð¾Ñ‚Ð½Ñ‹Ðµ Ð´Ð¸ÑÐºÐ¾Ð²Ñ‹Ðµ ÑÑ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ",
                        "search_normalized_name": "Ð·Ð°Ñ‚Ð²Ð¾Ñ€ Ð¿Ð¾Ð²Ð¾Ñ€Ð¾Ñ‚Ð½Ñ‹Ð¹ Ð´Ð¸ÑÐºÐ¾Ð²Ñ‹Ð¹ ÑÑ‚Ð°Ð»ÑŒÐ½Ð¾Ð¹ dn100",
                        "search_tokens_json": "[]",
                        "search_entity_type": "other",
                        "search_effective_family": "other",
                        "search_effective_entity_type": "other",
                        "search_item_markers_json": "{}",
                    },
                    {
                        "ÐÐ°Ð¸Ð¼ÐµÐ½Ð¾Ð²Ð°Ð½Ð¸Ðµ": "ÐšÑ€Ð°Ð½ ÑˆÐ°Ñ€Ð¾Ð²Ð¾Ð¹ ÑÑ‚Ð°Ð»ÑŒÐ½Ð¾Ð¹ DN50",
                        "ÐÑ€Ñ‚Ð¸ÐºÑƒÐ»": "VALVE-2",
                        "Ð¦ÐµÐ½Ð° Ñ€Ð¾Ð·Ð½Ð¸Ñ‡Ð½Ð°Ñ": 10,
                        "ÐÐ°Ð·Ð²Ð°Ð½Ð¸Ðµ ÐºÐ»Ð°ÑÑÐ°": "ÐšÑ€Ð°Ð½Ñ‹ Ð¨Ð°Ñ€Ð¾Ð²Ñ‹Ðµ Ð¡Ñ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ",
                        "ÐšÐ¾Ð´ ÐºÐ»Ð°ÑÑÐ°": "CLS-2",
                        "Ð¢Ð¸Ð¿ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ": "ÐšÑ€Ð°Ð½",
                        "Ð¢Ð¸Ð¿ Ð¸ÑÐ¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ ÐºÐ°Ð±ÐµÐ»ÑŒÐ½Ð¾Ð³Ð¾ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ": "",
                        "ÐŸÑ€Ð¾Ð¸Ð·Ð²Ð¾Ð´Ð¸Ñ‚ÐµÐ»ÑŒ": "ReMo",
                        "search_branch_path": "ÐºÑ€Ð°Ð½Ñ‹ ÑˆÐ°Ñ€Ð¾Ð²Ñ‹Ðµ ÑÑ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ",
                        "search_branch_leaf": "ÐºÑ€Ð°Ð½Ñ‹ ÑˆÐ°Ñ€Ð¾Ð²Ñ‹Ðµ ÑÑ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ",
                        "search_normalized_name": "ÐºÑ€Ð°Ð½ ÑˆÐ°Ñ€Ð¾Ð²Ð¾Ð¹ ÑÑ‚Ð°Ð»ÑŒÐ½Ð¾Ð¹ dn50",
                        "search_tokens_json": "[]",
                        "search_entity_type": "other",
                        "search_effective_family": "other",
                        "search_effective_entity_type": "other",
                        "search_item_markers_json": "{}",
                    },
                ]
            ).to_csv(search_path, sep=";", encoding="utf-8", index=False)

            _, summary_path, _ = build_search_taxonomy_branch_probe(root, ["Ð·Ð°Ñ‚Ð²Ð¾Ñ€Ñ‹ Ð¿Ð¾Ð²Ð¾Ñ€Ð¾Ñ‚Ð½Ñ‹Ðµ Ð´Ð¸ÑÐºÐ¾Ð²Ñ‹Ðµ ÑÑ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ"])
            summary_df = pd.read_csv(summary_path, sep=";", encoding="utf-8")

            self.assertEqual(len(summary_df), 1)
            self.assertNotIn("ÐºÑ€Ð°Ð½Ñ‹ ÑˆÐ°Ñ€Ð¾Ð²Ñ‹Ðµ ÑÑ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ", summary_df["search_branch_path"].tolist())

    def test_build_search_taxonomy_bootstrap_draft_can_use_probe_summary_context_without_source_db(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            get_search_taxonomy_probe_tree_path(root).write_text(
                json.dumps(
                    {
                        "catalog_stats": {
                            "mode": "branch_probe",
                            "source_path": "",
                            "selected_branches": ["demo > cable tray covers"],
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "demo > cable tray covers",
                        "branch_total_rows": 100,
                        "effective_family": "rack_accessory_strict",
                        "rows_count": 55,
                        "family_share_within_branch": 0.55,
                        "sample_names_json": "[\"Demo cable tray cover 100\"]",
                        "sample_rows_json": "[\"Demo cable tray cover 100 | class=Demo Tray Covers | type=Cover | article=D-1\"]",
                        "top_class_names_json": "[\"Demo Tray Covers\"]",
                        "top_item_types_json": "[\"Cover\"]",
                        "top_articles_json": "[\"D-1\"]",
                    },
                    {
                        "search_branch_path": "demo > cable tray covers",
                        "branch_total_rows": 100,
                        "effective_family": "tray_sheet",
                        "rows_count": 45,
                        "family_share_within_branch": 0.45,
                        "sample_names_json": "[\"Demo cable tray cover 100\"]",
                        "sample_rows_json": "[\"Demo cable tray cover 100 | class=Demo Tray Covers | type=Cover | article=D-1\"]",
                        "top_class_names_json": "[\"Demo Tray Covers\"]",
                        "top_item_types_json": "[\"Cover\"]",
                        "top_articles_json": "[\"D-1\"]",
                    },
                ]
            ).to_csv(get_search_taxonomy_probe_branch_summary_path(root), sep=";", encoding="utf-8", index=False)
            pd.DataFrame(
                [
                    {
                        "search_branch_path": "demo > cable tray covers",
                        "branch_total_rows": 100,
                        "family_count": 2,
                        "top_family": "rack_accessory_strict",
                        "top_family_rows": 55,
                        "top_family_share": 0.55,
                        "second_family": "tray_sheet",
                        "second_family_rows": 45,
                        "second_family_share": 0.45,
                        "other_rows": 0,
                        "other_share": 0.0,
                        "suspicious_score": 45.0,
                        "top_families": "rack_accessory_strict (55) | tray_sheet (45)",
                    }
                ]
            ).to_csv(get_search_taxonomy_probe_audit_path(root), sep=";", encoding="utf-8", index=False)

            _, csv_path = build_search_taxonomy_bootstrap_draft(
                root,
                api_key="test",
                max_branches=1,
                generate_text=lambda _prompt: json.dumps(
                    {
                        "branches": [
                            {
                                "search_branch_path": "demo > cable tray covers !!!",
                                "suggested_family": "",
                                "suggested_subfamily": "",
                                "suggested_action": "split_branch",
                                "confidence": 0.88,
                                "rationale": "Branch is mixed and should be split into narrower tray cover groups.",
                                "evidence_tokens": ["cover", "tray", "mixed"],
                                "notes": "Do not force one family onto the full branch.",
                            }
                        ]
                    }
                ),
            )

            draft_df = pd.read_csv(csv_path, sep=";", encoding="utf-8")
            self.assertEqual(draft_df.at[0, "response_branch_path"], "demo > cable tray covers !!!")
            self.assertEqual(draft_df.at[0, "branch_match_method"], "normalized_exact")
            self.assertEqual(draft_df.at[0, "suggested_action"], "split_branch")
            self.assertTrue(pd.isna(draft_df.at[0, "suggested_family"]) or draft_df.at[0, "suggested_family"] == "")
            self.assertTrue(str(draft_df.at[0, "sample_rows"]).strip())

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
            self.assertIn("search_effective_family", built.columns)
            self.assertIn("search_effective_entity_type", built.columns)
            self.assertEqual(len(built), 1)
            self.assertEqual(built.loc[0, "search_entity_type"], "pdu_basic")
            self.assertEqual(built.loc[0, "search_effective_family"], "pdu")
            self.assertEqual(built.loc[0, "search_effective_entity_type"], "pdu")

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
