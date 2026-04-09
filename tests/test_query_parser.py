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

    def test_parse_query_spec_detects_multimeter_queries(self):
        multimeter = parse_query_spec("Мультиметр цифровой TRUE RMS 600В", taxonomy_rules=self.rules)

        self.assertEqual(multimeter.entity_type, "multimeter")
        self.assertEqual(multimeter.branch_hint, "мультиметры")

    def test_parse_query_spec_detects_clamp_meter_queries(self):
        clamp_meter = parse_query_spec("Клещи токоизмерительные цифровые 600А", taxonomy_rules=self.rules)

        self.assertEqual(clamp_meter.entity_type, "clamp_meter")
        self.assertEqual(clamp_meter.branch_hint, "клещи токоизмерительные")

    def test_parse_query_spec_detects_voltage_indicator_queries(self):
        indicator = parse_query_spec("Индикатор напряжения двухполюсный 12-690В", taxonomy_rules=self.rules)

        self.assertEqual(indicator.entity_type, "voltage_indicator")
        self.assertEqual(indicator.branch_hint, "индикаторы напряжения")

    def test_parse_query_spec_detects_pressure_regulator_queries(self):
        regulator = parse_query_spec("Регулятор давления воды DN20", taxonomy_rules=self.rules)

        self.assertEqual(regulator.entity_type, "pressure_regulator")
        self.assertEqual(regulator.branch_hint, "регулятор давления")

    def test_parse_query_spec_detects_voltage_stabilizer_queries(self):
        stabilizer = parse_query_spec("Стабилизатор напряжения 10 кВА 220В", taxonomy_rules=self.rules)

        self.assertEqual(stabilizer.entity_type, "voltage_stabilizer")
        self.assertEqual(stabilizer.branch_hint, "стабилизаторы напряжения")

    def test_parse_query_spec_detects_frequency_drive_queries(self):
        drive = parse_query_spec("Преобразователь частоты 5,5 кВт 380В", taxonomy_rules=self.rules)

        self.assertEqual(drive.entity_type, "frequency_drive")
        self.assertEqual(drive.branch_hint, "преобразователи частоты, приводы")

    def test_parse_query_spec_detects_electric_motor_queries(self):
        motor = parse_query_spec("Электродвигатель асинхронный трехфазный 5,5 кВт", taxonomy_rules=self.rules)

        self.assertEqual(motor.entity_type, "electric_motor")
        self.assertEqual(motor.branch_hint, "электродвигатели общепромышленные")

    def test_parse_query_spec_detects_industrial_pump_queries(self):
        pump = parse_query_spec("Насос промышленный вертикальный центробежный 5,5 кВт", taxonomy_rules=self.rules)

        self.assertEqual(pump.entity_type, "industrial_pump")
        self.assertEqual(pump.branch_hint, "промышленные вертикальные центробежные насосы")

    def test_parse_query_spec_detects_thread_tap_queries(self):
        tap = parse_query_spec("Метчик машинно-ручной М8", taxonomy_rules=self.rules)

        self.assertEqual(tap.entity_type, "thread_tap")
        self.assertEqual(tap.branch_hint, "метчики")

    def test_parse_query_spec_detects_thread_die_queries(self):
        die = parse_query_spec("Плашка круглая М8", taxonomy_rules=self.rules)

        self.assertEqual(die.entity_type, "thread_die")
        self.assertEqual(die.branch_hint, "плашки")

    def test_parse_query_spec_detects_socket_head_drive_belt_and_brass_fitting_queries(self):
        socket_head = parse_query_spec("Набор торцевых головок 1/2 10-24 мм", taxonomy_rules=self.rules)
        belt = parse_query_spec("Ремень узкоклиновой SPC 2240", taxonomy_rules=self.rules)
        fitting = parse_query_spec("Фитинг резьбовой латунный угольник 1/2", taxonomy_rules=self.rules)

        self.assertEqual(socket_head.entity_type, "socket_head_set")
        self.assertEqual(socket_head.branch_hint, "торцевые головки и наборы головок")
        self.assertEqual(belt.entity_type, "drive_belt")
        self.assertEqual(belt.branch_hint, "ремни узкоклиновые")
        self.assertEqual(fitting.entity_type, "brass_threaded_fitting")
        self.assertEqual(fitting.branch_hint, "фитинги резьбовые латунные")

    def test_parse_query_spec_detects_workwear_gloves_polypropylene_fitting_and_turning_tool_queries(self):
        suit = parse_query_spec("Костюм летний рабочий мужской", taxonomy_rules=self.rules)
        gloves = parse_query_spec("Перчатки защитные антипорезные размер 10", taxonomy_rules=self.rules)
        fitting = parse_query_spec("Фитинг полипропиленовый муфта 25 мм", taxonomy_rules=self.rules)
        turning_tool = parse_query_spec("Резец по металлу токарный проходной 16x16", taxonomy_rules=self.rules)

        self.assertEqual(suit.entity_type, "workwear")
        self.assertEqual(suit.branch_hint, "костюмы летние")
        self.assertEqual(gloves.entity_type, "protective_gloves")
        self.assertEqual(gloves.branch_hint, "антипорезные и защитные перчатки")
        self.assertEqual(fitting.entity_type, "polypropylene_fitting")
        self.assertEqual(fitting.branch_hint, "фитинги для полипропиленовых труб")
        self.assertEqual(turning_tool.entity_type, "metal_turning_tool")
        self.assertEqual(turning_tool.branch_hint, "резцы по металлу")

    def test_parse_query_spec_detects_wrench_caliper_and_blade_queries(self):
        wrench = parse_query_spec("Ключ комбинированный 17 мм", taxonomy_rules=self.rules)
        caliper = parse_query_spec("Штангенциркуль цифровой 150 мм", taxonomy_rules=self.rules)
        wood_blade = parse_query_spec("Пильный диск по дереву 190x30x24T", taxonomy_rules=self.rules)
        diamond_blade = parse_query_spec("Алмазный диск 125 мм по бетону", taxonomy_rules=self.rules)

        self.assertEqual(wrench.entity_type, "combination_wrench")
        self.assertEqual(wrench.branch_hint, "комбинированные ключи")
        self.assertEqual(caliper.entity_type, "caliper")
        self.assertEqual(caliper.branch_hint, "штангенциркули")
        self.assertEqual(wood_blade.entity_type, "wood_saw_blade")
        self.assertEqual(wood_blade.branch_hint, "пильные диски по дереву")
        self.assertEqual(diamond_blade.entity_type, "diamond_blade")
        self.assertEqual(diamond_blade.branch_hint, "алмазные диски")

    def test_parse_query_spec_detects_drill_bit_metal_queries(self):
        drill = parse_query_spec("Сверло по металлу HSS 8 мм", taxonomy_rules=self.rules)

        self.assertEqual(drill.entity_type, "drill_bit_metal")
        self.assertEqual(drill.branch_hint, "сверла по металлу")

    def test_parse_query_spec_detects_masonry_drill_bit_queries(self):
        drill = parse_query_spec("Бур SDS-Plus 8x160 мм", taxonomy_rules=self.rules)

        self.assertEqual(drill.entity_type, "masonry_drill_bit")
        self.assertEqual(drill.branch_hint, "буры sds-plus")

    def test_parse_query_spec_detects_concrete_hole_saw_queries(self):
        hole_saw = parse_query_spec("Коронка по бетону алмазная 68 мм", taxonomy_rules=self.rules)

        self.assertEqual(hole_saw.entity_type, "concrete_hole_saw")
        self.assertEqual(hole_saw.branch_hint, "коронки по бетону")

    def test_parse_query_spec_detects_sds_chisel_queries(self):
        chisel = parse_query_spec("Зубило SDS-Plus плоское 20x250 мм", taxonomy_rules=self.rules)

        self.assertEqual(chisel.entity_type, "sds_chisel")
        self.assertEqual(chisel.branch_hint, "зубила sds-plus")

    def test_parse_query_spec_detects_distribution_enclosure_queries(self):
        metal = parse_query_spec("Щит распределительный встраиваемый металлический на 36 модулей", taxonomy_rules=self.rules)
        plastic = parse_query_spec("Корпус распределительный встраиваемый пластиковый на 24 модуля", taxonomy_rules=self.rules)
        metal_wall = parse_query_spec("Щит распределительный навесной металлический ЩРН-36", taxonomy_rules=self.rules)
        plastic_wall = parse_query_spec("Корпус распределительный навесной пластиковый ЩРН-П 24", taxonomy_rules=self.rules)

        self.assertEqual(metal.entity_type, "distribution_enclosure")
        self.assertEqual(metal.branch_hint, "корпуса учетно-распределительные встраиваемые металлические")
        self.assertEqual(plastic.entity_type, "distribution_enclosure")
        self.assertEqual(plastic.branch_hint, "корпуса распределительные встраиваемые пластиковые")
        self.assertEqual(metal_wall.entity_type, "distribution_enclosure")
        self.assertEqual(metal_wall.branch_hint, "корпуса учетно-распределительные навесные металлические")
        self.assertEqual(plastic_wall.entity_type, "distribution_enclosure")
        self.assertEqual(plastic_wall.branch_hint, "корпуса распределительные навесные пластиковые")

    def test_parse_query_spec_detects_power_accessory_queries(self):
        strip = parse_query_spec("Удлинитель силовой на 4 розетки 3м", taxonomy_rules=self.rules)
        plug = parse_query_spec("Штепсельная вилка прямая 16А 220В", taxonomy_rules=self.rules)

        self.assertEqual(strip.entity_type, "power_accessory")
        self.assertEqual(strip.branch_hint, "удлинители, сетевые фильтры, переходники, штепсельные вилки")
        self.assertEqual(plug.entity_type, "power_accessory")
        self.assertEqual(plug.branch_hint, "удлинители, сетевые фильтры, переходники, штепсельные вилки")

    def test_parse_query_spec_detects_cable_conduit_queries(self):
        metal = parse_query_spec("Металлорукав в ПВХ изоляции 20 мм", taxonomy_rules=self.rules)
        corrugated = parse_query_spec("Труба гофрированная для прокладки кабеля 25 мм", taxonomy_rules=self.rules)
        rigid = parse_query_spec("Труба жесткая двустенная 110 мм", taxonomy_rules=self.rules)

        self.assertEqual(metal.entity_type, "cable_conduit")
        self.assertEqual(metal.branch_hint, "металлорукав с изоляцией")
        self.assertEqual(corrugated.entity_type, "cable_conduit")
        self.assertEqual(corrugated.branch_hint, "гофрированные трубы для прокладки кабеля")
        self.assertEqual(rigid.entity_type, "cable_conduit")
        self.assertEqual(rigid.branch_hint, "трубы жесткие двустенные")

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

    def test_parse_query_spec_detects_neutral_busbar_queries(self):
        busbar = parse_query_spec("Нулевая шина на DIN-рейку 12 групп", taxonomy_rules=self.rules)

        self.assertEqual(busbar.entity_type, "neutral_busbar")
        self.assertEqual(busbar.branch_hint, "нулевые шины на din-рейку")

    def test_parse_query_spec_detects_wire_ferrule_queries(self):
        ferrule = parse_query_spec("Наконечник штыревой втулочный НШВИ 1,5-8", taxonomy_rules=self.rules)
        self.assertEqual(ferrule.entity_type, "wire_ferrule")
        self.assertEqual(ferrule.branch_hint, "штыревые втулочные наконечники (ншв и ншви)")

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
