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

    def test_parse_query_spec_detects_signage_queries(self):
        light_sign = parse_query_spec("Свето-звуковое табло ВЫХОД 12В", taxonomy_rules=self.rules)
        safety_sign = parse_query_spec("Знак безопасности Направление эвакуации", taxonomy_rules=self.rules)

        self.assertEqual(light_sign.entity_type, "light_signage")
        self.assertEqual(light_sign.branch_hint, "свето-звуковое табло")
        self.assertEqual(safety_sign.entity_type, "safety_sign")
        self.assertEqual(safety_sign.branch_hint, "знаки безопасности")


    def test_parse_query_spec_detects_industrial_valve_queries(self):
        disc_valve = parse_query_spec("Затвор дисковый поворотный DN100", taxonomy_rules=self.rules)
        ball_valve = parse_query_spec("Кран шаровой стальной DN50", taxonomy_rules=self.rules)
        brass_valve = parse_query_spec("Кран шаровой латунный для воды DN20", taxonomy_rules=self.rules)
        pnd_valve = parse_query_spec("Кран шаровой ПНД 32 мм", taxonomy_rules=self.rules)
        cast_iron_valve = parse_query_spec("Затвор дисковый поворотный чугунный DN80", taxonomy_rules=self.rules)
        solenoid_valve = parse_query_spec("Клапан электромагнитный соленоидный 1/2", taxonomy_rules=self.rules)

        self.assertEqual(disc_valve.entity_type, "industrial_valve")
        self.assertEqual(disc_valve.branch_hint, "затворы поворотные дисковые стальные")
        self.assertEqual(ball_valve.entity_type, "industrial_valve")
        self.assertEqual(ball_valve.branch_hint, "краны шаровые стальные")
        self.assertEqual(brass_valve.entity_type, "industrial_valve")
        self.assertEqual(brass_valve.branch_hint, "краны шаровые латунные для воды")
        self.assertEqual(pnd_valve.entity_type, "industrial_valve")
        self.assertEqual(pnd_valve.branch_hint, "краны шаровые пнд")
        self.assertEqual(cast_iron_valve.entity_type, "industrial_valve")
        self.assertEqual(cast_iron_valve.branch_hint, "затворы поворотные дисковые чугунные")
        self.assertEqual(solenoid_valve.entity_type, "industrial_valve")
        self.assertEqual(solenoid_valve.branch_hint, "клапаны электромагнитные (соленоидные)")

    def test_parse_query_spec_detects_bearing_queries(self):
        roller_bearing = parse_query_spec("Подшипник роликовый цилиндрический 22210", taxonomy_rules=self.rules)
        spherical_bearing = parse_query_spec("Подшипник роликовый сферический 22212", taxonomy_rules=self.rules)
        tapered_bearing = parse_query_spec("Подшипник роликовый конический 30205", taxonomy_rules=self.rules)
        ball_bearing = parse_query_spec("Подшипник шариковый радиальный 6205", taxonomy_rules=self.rules)
        thrust_bearing = parse_query_spec("Подшипник шариковый радиально-упорный 7205", taxonomy_rules=self.rules)
        axial_bearing = parse_query_spec("Подшипник упорный 51105", taxonomy_rules=self.rules)
        self_aligning_bearing = parse_query_spec("Подшипник самоустанавливающийся шариковый 1205", taxonomy_rules=self.rules)
        needle_bearing = parse_query_spec("Подшипник игольчатый HK1210", taxonomy_rules=self.rules)

        self.assertEqual(roller_bearing.entity_type, "bearing")
        self.assertEqual(roller_bearing.branch_hint, "подшипники роликовые цилиндрические")
        self.assertEqual(spherical_bearing.entity_type, "bearing")
        self.assertEqual(spherical_bearing.branch_hint, "подшипники роликовые сферические")
        self.assertEqual(tapered_bearing.entity_type, "bearing")
        self.assertEqual(tapered_bearing.branch_hint, "подшипники роликовые конические")
        self.assertEqual(ball_bearing.entity_type, "bearing")
        self.assertEqual(ball_bearing.branch_hint, "подшипники шариковые радиальные")
        self.assertEqual(thrust_bearing.entity_type, "bearing")
        self.assertEqual(thrust_bearing.branch_hint, "подшипники шариковые радиально-упорные")
        self.assertEqual(axial_bearing.entity_type, "bearing")
        self.assertEqual(axial_bearing.branch_hint, "упорные подшипники")
        self.assertEqual(self_aligning_bearing.entity_type, "bearing")
        self.assertEqual(self_aligning_bearing.branch_hint, "самоустанавливающиеся шарикоподшипники")
        self.assertEqual(needle_bearing.entity_type, "bearing")
        self.assertEqual(needle_bearing.branch_hint, "игольчатые подшипники")

    def test_parse_query_spec_detects_radiator_queries(self):
        radiator = parse_query_spec("Радиатор стальной панельный 22 500x1000", taxonomy_rules=self.rules)

        self.assertEqual(radiator.entity_type, "radiator")
        self.assertEqual(radiator.branch_hint, "радиаторы стальные панельные")

    def test_parse_query_spec_detects_floor_convector_queries(self):
        convector = parse_query_spec("Конвектор внутрипольный с вентилятором 2000мм", taxonomy_rules=self.rules)

        self.assertEqual(convector.entity_type, "floor_convector")
        self.assertEqual(convector.branch_hint, "конвекторы внутрипольные")

    def test_parse_query_spec_detects_heat_shrink_queries(self):
        heat_shrink = parse_query_spec("Термоусаживаемая трубка 12/6 черная", taxonomy_rules=self.rules)

        self.assertEqual(heat_shrink.entity_type, "heat_shrink")
        self.assertEqual(heat_shrink.branch_hint, "термоусаживаемые изделия")

    def test_parse_query_spec_detects_transformer_queries(self):
        transformer = parse_query_spec("Трансформатор напряжения понижающий низковольтный 220/24В", taxonomy_rules=self.rules)
        current_transformer = parse_query_spec("Трансформатор тока низковольтный 100/5А", taxonomy_rules=self.rules)

        self.assertEqual(transformer.entity_type, "transformer")
        self.assertEqual(transformer.branch_hint, "трансформаторы напряжения понижающие низковольтные")
        self.assertEqual(current_transformer.entity_type, "transformer")
        self.assertEqual(current_transformer.branch_hint, "трансформаторы тока низковольтные")

    def test_parse_query_spec_detects_pressure_gauge_queries(self):
        gauge = parse_query_spec("Манометр радиальный 0-10 бар", taxonomy_rules=self.rules)

        self.assertEqual(gauge.entity_type, "pressure_gauge")
        self.assertEqual(gauge.branch_hint, "манометры")

    def test_parse_query_spec_detects_pressure_regulator_queries(self):
        regulator = parse_query_spec("Регулятор давления воды DN20", taxonomy_rules=self.rules)

        self.assertEqual(regulator.entity_type, "pressure_regulator")
        self.assertEqual(regulator.branch_hint, "регулятор давления")

    def test_parse_query_spec_detects_fuse_queries(self):
        fuse = parse_query_spec("Предохранитель плавкий 10А", taxonomy_rules=self.rules)

        self.assertEqual(fuse.entity_type, "fuse")
        self.assertEqual(fuse.branch_hint, "плавкие предохранители")

    def test_parse_query_spec_detects_ups_queries(self):
        ups = parse_query_spec("Источник бесперебойного питания Line Interactive 2000VA", taxonomy_rules=self.rules)

        self.assertEqual(ups.entity_type, "ups")
        self.assertEqual(ups.branch_hint, "источники бесперебойного питания (ибп)")

    def test_parse_query_spec_detects_push_button_queries(self):
        button = parse_query_spec("Кнопка управления красная 22мм", taxonomy_rules=self.rules)
        post = parse_query_spec("Кнопочный пост ПКЕ 2 кнопки", taxonomy_rules=self.rules)

        self.assertEqual(button.entity_type, "push_button")
        self.assertEqual(button.branch_hint, "кнопки")
        self.assertEqual(post.entity_type, "push_button")
        self.assertEqual(post.branch_hint, "кнопочные посты")

    def test_parse_query_spec_detects_terminal_block_and_signal_indicator_queries(self):
        terminal_block = parse_query_spec("Клеммный блок на DIN-рейку 2,5мм серый", taxonomy_rules=self.rules)
        signal_indicator = parse_query_spec("Арматура светосигнальная зеленая 24В", taxonomy_rules=self.rules)
        feed_through = parse_query_spec("Проходная клемма на DIN-рейку 4мм", taxonomy_rules=self.rules)
        mini = parse_query_spec("Миниклемма на DIN-рейку 2,5мм", taxonomy_rules=self.rules)

        self.assertEqual(terminal_block.entity_type, "terminal_block")
        self.assertEqual(terminal_block.branch_hint, "клеммные блоки зажимов на din-рейку")
        self.assertEqual(feed_through.entity_type, "terminal_block")
        self.assertEqual(feed_through.branch_hint, "проходные клеммы на din-рейку")
        self.assertEqual(mini.entity_type, "terminal_block")
        self.assertEqual(mini.branch_hint, "миниклеммы на din-рейку")
        self.assertEqual(signal_indicator.entity_type, "signal_indicator")
        self.assertEqual(signal_indicator.branch_hint, "светосигнальная арматура")

    def test_parse_query_spec_detects_breaker_load_switch_queries(self):
        load_switch = parse_query_spec("Выключатель нагрузки 3P 63A", taxonomy_rules=self.rules)
        disconnector = parse_query_spec("Выключатель разъединитель 3P 125A", taxonomy_rules=self.rules)

        self.assertEqual(load_switch.entity_type, "breaker")
        self.assertEqual(load_switch.branch_hint, "рубильники")
        self.assertEqual(disconnector.entity_type, "breaker")
        self.assertEqual(disconnector.branch_hint, "рубильники")

    def test_parse_query_spec_detects_surge_protector_queries(self):
        surge = parse_query_spec("Ограничитель импульсного перенапряжения SPD тип 2 40кА", taxonomy_rules=self.rules)

        self.assertEqual(surge.entity_type, "surge_protector")
        self.assertEqual(surge.branch_hint, "ограничители импульсного перенапряжения силовые модульные")

if __name__ == "__main__":
    unittest.main()
