import unittest

from query_parser import detect_query_row_type, parse_query_spec
from taxonomy_registry import load_registry_taxonomy_rules


class QueryParserTests(unittest.TestCase):
    def setUp(self):
        self.rules = load_registry_taxonomy_rules()

    def test_detect_query_row_type_marks_header_like_rows_as_section(self):
        self.assertEqual(detect_query_row_type("ОБОРУДОВАНИЕ", self.rules), "section")
        self.assertEqual(
            detect_query_row_type("Наименование оборудования материалов и кабелей", self.rules),
            "section",
        )
        self.assertEqual(detect_query_row_type("ОГНЕСТОЙКАЯ КАБЕЛЬНАЯ ЛИНИЯ", self.rules), "section")
        self.assertEqual(detect_query_row_type("МАТЕРИАЛЫ", self.rules), "section")
        self.assertEqual(detect_query_row_type("КАБЕЛЬНАЯ ПРОДУКЦИЯ", self.rules), "section")
        self.assertEqual(detect_query_row_type("МПН", self.rules), "item")

    def test_parse_query_spec_extracts_article_and_designation_signature(self):
        spec = parse_query_spec("Кабель, артикул ВВГнг(A)-LS 4x4", taxonomy_rules=self.rules)

        self.assertEqual(spec.parser_source, "local")
        self.assertEqual(spec.extracted_article, "ВВГнг(A)-LS 4x4")
        self.assertTrue(spec.designation_signature)
        self.assertEqual(spec.markers.get("designation_family"), "ввгнг ls")

    def test_parse_query_spec_preserves_cable_dimension_order(self):
        spec = parse_query_spec("Кабель, артикул КГВЭВнг(A)-LS 4x1", taxonomy_rules=self.rules)

        self.assertEqual(spec.designation_signature, "кгвэвнг ls|4x1")

    def test_parse_query_spec_extracts_accessory_markers_and_dimensions(self):
        spec = parse_query_spec("Угол CD 90 вертикальный внешний 100x50", taxonomy_rules=self.rules)

        self.assertEqual(spec.markers.get("accessory_kind"), "corner")
        self.assertEqual(spec.markers.get("orientation_kind"), "vertical")
        self.assertEqual(spec.markers.get("position_kind"), "outer")
        self.assertIn("50x100", spec.dimension_pairs)

    def test_parse_query_spec_classifies_clamp_as_rack_accessory(self):
        spec = parse_query_spec("Скоба однолапковая d=20-21", taxonomy_rules=self.rules)

        self.assertEqual(spec.entity_type, "rack_accessory_strict")
        self.assertEqual(spec.markers.get("accessory_kind"), "holder")
        self.assertIn("20-21", spec.dimension_diameters)

    def test_parse_query_spec_avoids_rack_family_for_firestop_and_control_cabinet(self):
        foam_spec = parse_query_spec("Огнестойкая монтажная пена ОГНЕЗА EI240, 750 мл", taxonomy_rules=self.rules)
        cabinet_spec = parse_query_spec("Шкаф контрольно-пусковой", taxonomy_rules=self.rules)

        self.assertEqual(foam_spec.entity_type, "firestop_material")
        self.assertEqual(cabinet_spec.entity_type, "other")

    def test_parse_query_spec_detects_cable_channel_box_query(self):
        spec = parse_query_spec("Короб с крышкой 80x40 (3 м.)", taxonomy_rules=self.rules)

        self.assertEqual(spec.entity_type, "cable_channel")
        self.assertEqual(spec.branch_hint, "электрика > кабели > кабель-каналы")
        self.assertEqual(spec.markers.get("installation_kind"), "cable_channel")
        self.assertEqual(spec.markers.get("length_m"), "3")
        self.assertNotIn("designation_family", spec.markers)
        self.assertEqual(spec.designation_signature, "")
        self.assertIn("40x80", spec.dimension_pairs)

    def test_parse_query_spec_uses_other_subfamily_split_for_lighting_and_tray(self):
        lighting_spec = parse_query_spec("Светильник светодиодный аварийный 595x595", taxonomy_rules=self.rules)
        tray_spec = parse_query_spec("Лоток листовой перфорированный 200х50", taxonomy_rules=self.rules)

        self.assertEqual(lighting_spec.entity_type, "lighting_fixture")
        self.assertEqual(lighting_spec.branch_hint, "свет > светильники")
        self.assertEqual(tray_spec.entity_type, "tray_sheet")
        self.assertTrue(tray_spec.branch_hint.startswith("листовые лотки"))

    def test_parse_query_spec_uses_other_subfamily_split_for_fire_alarm_and_supporting_items(self):
        detector = parse_query_spec("Извещатель пожарный дымовой адресный", taxonomy_rules=self.rules)
        annunciator = parse_query_spec("Оповещатель световой стробоскопический", taxonomy_rules=self.rules)
        panel = parse_query_spec("Пульт контроля и управления", taxonomy_rules=self.rules)
        interface = parse_query_spec("Преобразователь интерфейса RS485 в Modbus RTU", taxonomy_rules=self.rules)
        module = parse_query_spec("Модуль подключения нагрузки", taxonomy_rules=self.rules)
        software = parse_query_spec("ПО Сервер Орион Про", taxonomy_rules=self.rules)
        battery = parse_query_spec("Аккумуляторная батарея 26 Ач", taxonomy_rules=self.rules)
        firestop = parse_query_spec("Герметик огнезащитный терморасширяющийся", taxonomy_rules=self.rules)

        self.assertEqual(detector.entity_type, "fire_detector")
        self.assertEqual(annunciator.entity_type, "fire_annunciator")
        self.assertEqual(panel.entity_type, "security_control_panel")
        self.assertEqual(interface.entity_type, "security_interface_device")
        self.assertEqual(module.entity_type, "security_module_device")
        self.assertEqual(software.entity_type, "security_software")
        self.assertEqual(battery.entity_type, "power_backup")
        self.assertEqual(firestop.entity_type, "firestop_material")

    def test_parse_query_spec_uses_subfamily_split_for_boxes_and_switch_wiring(self):
        box_spec = parse_query_spec("Коробка монтажная огнестойкая", taxonomy_rules=self.rules)
        box_accessory_spec = parse_query_spec("Аксессуары для установочных коробок", taxonomy_rules=self.rules)
        switch_spec = parse_query_spec("Выключатель скрытого монтажа 1-клавишный", taxonomy_rules=self.rules)
        frame_spec = parse_query_spec("Рамка 2-местная белая", taxonomy_rules=self.rules)

        self.assertEqual(box_spec.entity_type, "box")
        self.assertEqual(box_spec.branch_hint, "коробки распределительные наружные")
        self.assertEqual(box_accessory_spec.entity_type, "box_accessory")
        self.assertEqual(box_accessory_spec.branch_hint, "аксессуары для установочных коробок")
        self.assertEqual(switch_spec.entity_type, "switch_wiring")
        self.assertEqual(switch_spec.branch_hint, "выключатели скрытого монтажа")
        self.assertEqual(frame_spec.entity_type, "switch_wiring")
        self.assertEqual(frame_spec.branch_hint, "рамки")


    def test_parse_query_spec_detects_industrial_valve_queries(self):
        disc_valve = parse_query_spec("Затвор дисковый поворотный DN100", taxonomy_rules=self.rules)
        ball_valve = parse_query_spec("Кран шаровой стальной DN50", taxonomy_rules=self.rules)
        cast_iron_valve = parse_query_spec("Затвор дисковый поворотный чугунный DN80", taxonomy_rules=self.rules)

        self.assertEqual(disc_valve.entity_type, "industrial_valve")
        self.assertEqual(disc_valve.branch_hint, "затворы поворотные дисковые стальные")
        self.assertEqual(ball_valve.entity_type, "industrial_valve")
        self.assertEqual(ball_valve.branch_hint, "краны шаровые стальные")
        self.assertEqual(cast_iron_valve.entity_type, "industrial_valve")
        self.assertEqual(cast_iron_valve.branch_hint, "затворы поворотные дисковые чугунные")

    def test_parse_query_spec_detects_bearing_queries(self):
        roller_bearing = parse_query_spec("Подшипник роликовый цилиндрический 22210", taxonomy_rules=self.rules)
        ball_bearing = parse_query_spec("Подшипник шариковый радиальный 6205", taxonomy_rules=self.rules)

        self.assertEqual(roller_bearing.entity_type, "bearing")
        self.assertEqual(roller_bearing.branch_hint, "подшипники роликовые цилиндрические")
        self.assertEqual(ball_bearing.entity_type, "bearing")
        self.assertEqual(ball_bearing.branch_hint, "подшипники шариковые радиальные")

    def test_parse_query_spec_detects_radiator_queries(self):
        radiator = parse_query_spec("Радиатор стальной панельный 22 500x1000", taxonomy_rules=self.rules)

        self.assertEqual(radiator.entity_type, "radiator")
        self.assertEqual(radiator.branch_hint, "радиаторы стальные панельные")

    def test_parse_query_spec_detects_transformer_queries(self):
        transformer = parse_query_spec("Трансформатор напряжения понижающий низковольтный 220/24В", taxonomy_rules=self.rules)

        self.assertEqual(transformer.entity_type, "transformer")
        self.assertEqual(transformer.branch_hint, "трансформаторы напряжения понижающие низковольтные")

if __name__ == "__main__":
    unittest.main()
