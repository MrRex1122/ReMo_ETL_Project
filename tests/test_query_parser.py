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

        backup_block = parse_query_spec(
            "Блок резервного питания 12В 2.5А в компактном корпусе под АКБ 1.2Ач",
            taxonomy_rules=self.rules,
        )
        relay_block = parse_query_spec(
            "Блок реле ВЭРС-БРУ 16 версия 3.1, 16 реле с тремя контактами перекидного типа",
            taxonomy_rules=self.rules,
        )
        ppkop_panel = parse_query_spec(
            "Прибор приемно-контрольный охранно-пожарный Гранит-5А GSM",
            taxonomy_rules=self.rules,
        )
        expansion_module = parse_query_spec(
            "Блок расширения адресных шлейфов",
            taxonomy_rules=self.rules,
        )
        remote_indicator = parse_query_spec(
            "Блок выносной индикации на 32 ППКОП",
            taxonomy_rules=self.rules,
        )
        address_marker = parse_query_spec(
            "Метка адресная пожарная со встроенным изолятором короткого замыкания",
            taxonomy_rules=self.rules,
        )

        self.assertEqual(backup_block.entity_type, "power_backup")
        self.assertEqual(relay_block.entity_type, "security_module_device")
        self.assertEqual(ppkop_panel.entity_type, "security_control_panel")
        self.assertEqual(expansion_module.entity_type, "security_module_device")
        self.assertEqual(remote_indicator.entity_type, "security_control_panel")
        self.assertEqual(address_marker.entity_type, "security_module_device")

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

    def test_parse_query_spec_aligns_large_electrical_branch_batch(self):
        contactor = parse_query_spec("Контактор магнитный 18А 230В", taxonomy_rules=self.rules)
        starter = parse_query_spec("Пускатель магнитный ПМЛ 25А", taxonomy_rules=self.rules)
        relay = parse_query_spec("Реле промежуточное 24В", taxonomy_rules=self.rules)
        key = parse_query_spec("Клавиша двухклавишная белая", taxonomy_rules=self.rules)
        cover = parse_query_spec("Накладка для розетки 1-постовая белая", taxonomy_rules=self.rules)
        led_strip = parse_query_spec("Лента светодиодная 24В 14.4Вт/м", taxonomy_rules=self.rules)
        led_profile = parse_query_spec("Профиль для светодиодной ленты угловой 2м", taxonomy_rules=self.rules)
        led_driver = parse_query_spec("Блок питания для светодиодной ленты 24В 100Вт", taxonomy_rules=self.rules)
        lamp_e = parse_query_spec("Лампа светодиодная E27 12Вт", taxonomy_rules=self.rules)
        lamp_gu = parse_query_spec("Лампа светодиодная GU10 7Вт", taxonomy_rules=self.rules)

        self.assertEqual(contactor.entity_type, "contactor_starter")
        self.assertEqual(contactor.branch_hint, "контакторы магнитные")
        self.assertEqual(starter.entity_type, "contactor_starter")
        self.assertEqual(starter.branch_hint, "пускатели магнитные")
        self.assertEqual(relay.entity_type, "control_relay")
        self.assertEqual(relay.branch_hint, "промежуточные реле")
        self.assertEqual(key.entity_type, "switch_wiring")
        self.assertEqual(key.branch_hint, "клавиши")
        self.assertEqual(cover.entity_type, "socket")
        self.assertEqual(cover.branch_hint, "накладки")
        self.assertEqual(led_strip.entity_type, "lighting_fixture")
        self.assertEqual(led_strip.branch_hint, "ленты светодиодные 24в")
        self.assertEqual(led_profile.entity_type, "lighting_fixture")
        self.assertEqual(led_profile.branch_hint, "профиль для светодиодной ленты")
        self.assertEqual(led_driver.entity_type, "lighting_fixture")
        self.assertEqual(led_driver.branch_hint, "блок питания и драйвер для светодиодной ленты")
        self.assertEqual(lamp_e.entity_type, "lighting_fixture")
        self.assertEqual(lamp_e.branch_hint, "лампы светодиодные е27, е14, е40")
        self.assertEqual(lamp_gu.entity_type, "lighting_fixture")
        self.assertEqual(lamp_gu.branch_hint, "лампы светодиодные g, gx, gu")

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

    def test_parse_query_spec_detects_cartridge_and_screwdriver_queries(self):
        cartridge = parse_query_spec("Картридж для принтера HP 85A", taxonomy_rules=self.rules)
        screwdriver = parse_query_spec("Отвертка крестовая PH2x100", taxonomy_rules=self.rules)

        self.assertEqual(cartridge.entity_type, "printer_cartridge")
        self.assertEqual(cartridge.branch_hint, "картриджи для печатной техники")
        self.assertEqual(screwdriver.entity_type, "phillips_screwdriver")
        self.assertEqual(screwdriver.branch_hint, "крестовые отвертки")

    def test_parse_query_spec_detects_thread_gauge_bits_wrenches_and_fitting_queries(self):
        gauge = parse_query_spec("Резьбомер метрический М60", taxonomy_rules=self.rules)
        torx_bit = parse_query_spec("Бита TORX T25 25 мм", taxonomy_rules=self.rules)
        phillips_bit = parse_query_spec("Бита крест PH2 50 мм", taxonomy_rules=self.rules)
        slotted = parse_query_spec("Отвертка шлицевая SL6x100", taxonomy_rules=self.rules)
        open_end = parse_query_spec("Ключ рожковый 17x19 мм", taxonomy_rules=self.rules)
        hex_key = parse_query_spec("Ключ имбусовый шестигранный HEX 6 мм", taxonomy_rules=self.rules)
        axial = parse_query_spec("Фитинг аксиальный для PEX 16x1/2", taxonomy_rules=self.rules)
        pnd = parse_query_spec("Фитинг компрессионный ПНД 32x1 наружная резьба", taxonomy_rules=self.rules)

        self.assertEqual(gauge.entity_type, "thread_gauge")
        self.assertEqual(gauge.branch_hint, "резьбомеры")
        self.assertEqual(torx_bit.entity_type, "torx_bit")
        self.assertEqual(torx_bit.branch_hint, "биты TORX")
        self.assertEqual(phillips_bit.entity_type, "phillips_bit")
        self.assertEqual(phillips_bit.branch_hint, "биты крест PH (Phillips)")
        self.assertEqual(slotted.entity_type, "slotted_screwdriver")
        self.assertEqual(slotted.branch_hint, "шлицевые отвертки")
        self.assertEqual(open_end.entity_type, "open_end_wrench")
        self.assertEqual(open_end.branch_hint, "рожковые ключи")
        self.assertEqual(hex_key.entity_type, "hex_key")
        self.assertEqual(hex_key.branch_hint, "ключи имбусовые шестигранные (HEX)")
        self.assertEqual(axial.entity_type, "axial_pex_fitting")
        self.assertEqual(axial.branch_hint, "фитинги аксиальные для PEX, PERT")
        self.assertEqual(pnd.entity_type, "pnd_compression_fitting")
        self.assertEqual(pnd.branch_hint, "фитинги компрессионные для ПНД труб пластиковые")

    def test_parse_query_spec_detects_additional_hand_tool_abrasive_and_garden_queries(self):
        threading_set = parse_query_spec("Набор резьбонарезного инструмента М3-М12", taxonomy_rules=self.rules)
        adjustable = parse_query_spec("Ключ разводной 250 мм", taxonomy_rules=self.rules)
        router = parse_query_spec("Фреза пазовая для ручного фрезера 12 мм", taxonomy_rules=self.rules)
        sanding_disc = parse_query_spec("Круг шлифовальный на липучке P120 125 мм", taxonomy_rules=self.rules)
        wire_brush = parse_query_spec("Корщетка чашечная М14 75 мм", taxonomy_rules=self.rules)
        trimmer = parse_query_spec("Леска для триммера 2.4 мм звезда 15 м", taxonomy_rules=self.rules)

        self.assertEqual(threading_set.entity_type, "threading_tool_set")
        self.assertEqual(threading_set.branch_hint, "наборы резьбонарезного инструмента")
        self.assertEqual(adjustable.entity_type, "adjustable_wrench")
        self.assertEqual(adjustable.branch_hint, "разводные ключи")
        self.assertEqual(router.entity_type, "router_bit")
        self.assertEqual(router.branch_hint, "фрезы и наборы фрез для ручных фрезеров")
        self.assertEqual(sanding_disc.entity_type, "hook_loop_sanding_disc")
        self.assertEqual(sanding_disc.branch_hint, "круги шлифовальные на липучке")
        self.assertEqual(wire_brush.entity_type, "wire_brush_tool")
        self.assertEqual(wire_brush.branch_hint, "корщетки")
        self.assertEqual(trimmer.entity_type, "trimmer_line")
        self.assertEqual(trimmer.branch_hint, "леска для триммеров")

    def test_parse_query_spec_detects_additional_tool_drive_and_appliance_queries(self):
        jacket = parse_query_spec("Куртка утепленная рабочая размер 52", taxonomy_rules=self.rules)
        overalls = parse_query_spec("Полукомбинезон рабочий утепленный размер 52", taxonomy_rules=self.rules)
        ring_wrench = parse_query_spec("Ключ накидной 17 мм", taxonomy_rules=self.rules)
        roller = parse_query_spec("Валик малярный велюровый 180 мм", taxonomy_rules=self.rules)
        pliers = parse_query_spec("Бокорезы диэлектрические 160 мм", taxonomy_rules=self.rules)
        drywall_screw = parse_query_spec("Саморез гипсокартон-дерево 3.5x35", taxonomy_rules=self.rules)
        wood_drill = parse_query_spec("Сверло по дереву спиральное 10 мм", taxonomy_rules=self.rules)
        floor_convector = parse_query_spec("Конвектор напольный электрический 1 кВт", taxonomy_rules=self.rules)
        heater = parse_query_spec("Водонагреватель электрический накопительный 80 л", taxonomy_rules=self.rules)
        drive_accessory = parse_query_spec("Аксессуар для преобразователя частоты с интерфейсной платой", taxonomy_rules=self.rules)
        pcb_terminal = parse_query_spec("Клеммный зажим для печатной платы 5,08 мм 2 pin", taxonomy_rules=self.rules)
        tape = parse_query_spec("Лента изоляционная ПВХ синяя 19 мм", taxonomy_rules=self.rules)
        control_valve = parse_query_spec("Клапан регулирующий чугунный DN50", taxonomy_rules=self.rules)
        shutoff_valve = parse_query_spec("Вентиль запорный стальной DN20", taxonomy_rules=self.rules)

        self.assertEqual(jacket.entity_type, "workwear")
        self.assertEqual(jacket.branch_hint, "куртки утепленные")
        self.assertEqual(overalls.entity_type, "workwear")
        self.assertEqual(overalls.branch_hint, "брюки, полукомбинезоны")
        self.assertEqual(ring_wrench.entity_type, "ring_wrench")
        self.assertEqual(ring_wrench.branch_hint, "накидные ключи")
        self.assertEqual(roller.entity_type, "paint_roller")
        self.assertEqual(roller.branch_hint, "валики")
        self.assertEqual(pliers.entity_type, "cutting_pliers")
        self.assertEqual(pliers.branch_hint, "бокорезы и кусачки")
        self.assertEqual(drywall_screw.entity_type, "self_tapping_screw")
        self.assertEqual(drywall_screw.branch_hint, "саморезы гипсокартон-дерево")
        self.assertEqual(wood_drill.entity_type, "wood_drill_bit")
        self.assertEqual(wood_drill.branch_hint, "сверла по дереву")
        self.assertEqual(floor_convector.entity_type, "floor_convector")
        self.assertEqual(floor_convector.branch_hint, "конвекторы напольные")
        self.assertEqual(heater.entity_type, "storage_water_heater")
        self.assertEqual(heater.branch_hint, "водонагреватели электрические накопительные")
        self.assertEqual(drive_accessory.entity_type, "frequency_drive")
        self.assertEqual(drive_accessory.branch_hint, "аксессуары для преобразователей частоты")
        self.assertEqual(pcb_terminal.entity_type, "terminal_block")
        self.assertEqual(pcb_terminal.branch_hint, "клеммные зажимы для печатных плат")
        self.assertEqual(tape.entity_type, "electrical_tape")
        self.assertEqual(tape.branch_hint, "изолента")
        self.assertEqual(control_valve.entity_type, "industrial_valve")
        self.assertEqual(control_valve.branch_hint, "клапаны регулирующие чугунные")
        self.assertEqual(shutoff_valve.entity_type, "industrial_valve")
        self.assertEqual(shutoff_valve.branch_hint, "клапаны запорные (вентили) стальные")

    def test_parse_query_spec_detects_additional_batch_families(self):
        helmet = parse_query_spec("Каска защитная белая с храповиком", taxonomy_rules=self.rules)
        jack = parse_query_spec("Домкрат гидравлический бутылочный 10т", taxonomy_rules=self.rules)
        convector = parse_query_spec("Конвектор электрический настенный 2 кВт", taxonomy_rules=self.rules)
        manifold = parse_query_spec("Коллекторная группа для теплого пола на 6 выходов", taxonomy_rules=self.rules)
        faucet = parse_query_spec("Смеситель для мойки однорычажный хром", taxonomy_rules=self.rules)
        compensator = parse_query_spec("УКРМ 0.4кВ 50 квар", taxonomy_rules=self.rules)
        lug = parse_query_spec("Наконечник ТМЛ 16-8-6", taxonomy_rules=self.rules)
        jumper = parse_query_spec("Перемычка для клемм на DIN-рейку FBS 10", taxonomy_rules=self.rules)
        camera = parse_query_spec("IP-видеокамера 4 Мп уличная", taxonomy_rules=self.rules)
        knife = parse_query_spec("Нож строительный сегментный 18 мм", taxonomy_rules=self.rules)
        welder = parse_query_spec("Костюм сварщика брезентовый размер 52", taxonomy_rules=self.rules)
        sewer = parse_query_spec("Фитинг шумопоглощающий для канализации 110 мм", taxonomy_rules=self.rules)
        drywall_metal = parse_query_spec("Саморез гипсокартон-металл 3.5x25", taxonomy_rules=self.rules)
        enclosure = parse_query_spec("Корпус щита монтажный металлический ЩМП-2", taxonomy_rules=self.rules)

        self.assertEqual(helmet.entity_type, "protective_helmet")
        self.assertEqual(helmet.branch_hint, "каски")
        self.assertEqual(jack.entity_type, "jack")
        self.assertEqual(jack.branch_hint, "домкраты")
        self.assertEqual(convector.entity_type, "electric_convector")
        self.assertEqual(convector.branch_hint, "конвекторы электрические")
        self.assertEqual(manifold.entity_type, "floor_heating_manifold")
        self.assertEqual(manifold.branch_hint, "коллекторные группы для теплого пола")
        self.assertEqual(faucet.entity_type, "faucet")
        self.assertEqual(faucet.branch_hint, "смесители для мойки")
        self.assertEqual(compensator.entity_type, "reactive_power_compensator")
        self.assertEqual(compensator.branch_hint, "устройства компенсации реактивной мощности 0.4кв")
        self.assertEqual(lug.entity_type, "power_terminal_lug")
        self.assertEqual(lug.branch_hint, "силовые медные луженые наконечники (тмл)")
        self.assertEqual(jumper.entity_type, "terminal_block_accessory")
        self.assertEqual(jumper.branch_hint, "перемычки для клемм на din-рейку")
        self.assertEqual(camera.entity_type, "ip_camera")
        self.assertEqual(camera.branch_hint, "ip-видеокамеры")
        self.assertEqual(knife.entity_type, "utility_knife")
        self.assertEqual(knife.branch_hint, "ножи строительные")
        self.assertEqual(welder.entity_type, "workwear")
        self.assertEqual(welder.branch_hint, "костюмы сварщика")
        self.assertEqual(sewer.entity_type, "sewer_fitting")
        self.assertEqual(sewer.branch_hint, "фитинги шумопоглощающие для канализации")
        self.assertEqual(drywall_metal.entity_type, "self_tapping_screw")
        self.assertEqual(drywall_metal.branch_hint, "саморезы гипсокартон-металл")
        self.assertEqual(enclosure.entity_type, "distribution_enclosure")
        self.assertEqual(enclosure.branch_hint, "корпуса щитов монтажных металлических")

    def test_parse_query_spec_detects_lighting_footwear_hole_saw_and_insulation_queries(self):
        chandelier = parse_query_spec("Люстра 8xE14 макс. 40Вт", taxonomy_rules=self.rules)
        boots = parse_query_spec("Ботинки рабочие S1P SRC, р.42", taxonomy_rules=self.rules)
        low_shoes = parse_query_spec("Полуботинки рабочие кожаные S1, р.43", taxonomy_rules=self.rules)
        hole_saw = parse_query_spec("Кольцевая коронка 53 мм", taxonomy_rules=self.rules)
        milling_cutter = parse_query_spec("Фреза концевая 10 мм z=4", taxonomy_rules=self.rules)
        insulation = parse_query_spec("Изоляция из вспененного каучука трубная 22x9", taxonomy_rules=self.rules)

        self.assertEqual(chandelier.entity_type, "lighting_fixture")
        self.assertEqual(chandelier.branch_hint, "люстры под лампу")
        self.assertEqual(boots.entity_type, "safety_footwear")
        self.assertEqual(boots.branch_hint, "ботинки рабочие")
        self.assertEqual(low_shoes.entity_type, "safety_footwear")
        self.assertEqual(low_shoes.branch_hint, "полуботинки рабочие")
        self.assertEqual(hole_saw.entity_type, "hole_saw")
        self.assertEqual(hole_saw.branch_hint, "коронки")
        self.assertEqual(milling_cutter.entity_type, "milling_cutter")
        self.assertEqual(milling_cutter.branch_hint, "фрезы для станков")
        self.assertEqual(insulation.entity_type, "pipe_insulation")
        self.assertEqual(insulation.branch_hint, "изоляция из вспененного каучука трубная")

    def test_parse_query_spec_detects_remaining_other_branch_batch(self):
        cart_wheel = parse_query_spec("Колесо для тележки поворотное 160 мм", taxonomy_rules=self.rules)
        crane_coil = parse_query_spec("Катушка тормоза крана РДК-250", taxonomy_rules=self.rules)
        burr = parse_query_spec("Бор-фреза твердосплавная цилиндрическая 10x20", taxonomy_rules=self.rules)
        breaker = parse_query_spec("Автомат защиты двигателя MMS-32H 40A", taxonomy_rules=self.rules)

        self.assertEqual(cart_wheel.entity_type, "warehouse_cart_part")
        self.assertEqual(cart_wheel.branch_hint, "запчасти для складских тележек")
        self.assertEqual(crane_coil.entity_type, "crane_equipment_accessory")
        self.assertEqual(crane_coil.branch_hint, "вспомогательные элементы и аксессуары двигателей и кранового оборудования")
        self.assertEqual(burr.entity_type, "rotary_burr")
        self.assertEqual(burr.branch_hint, "борфрезы и шарошки")
        self.assertEqual(breaker.entity_type, "breaker")

    def test_parse_query_spec_detects_measurement_hand_tool_and_footwear_queries(self):
        winter_boots = parse_query_spec("Ботинки утепленные рабочие размер 43", taxonomy_rules=self.rules)
        rubber_boots = parse_query_spec("Сапоги резиновые защитные высокие", taxonomy_rules=self.rules)
        crimper = parse_query_spec("Пресс-клещи для наконечников НШВИ 0.5-6 мм2", taxonomy_rules=self.rules)
        micrometer = parse_query_spec("Микрометр цифровой 0-25 мм", taxonomy_rules=self.rules)
        tape_measure = parse_query_spec("Рулетка измерительная 5м x 19мм", taxonomy_rules=self.rules)
        level = parse_query_spec("Уровень пузырьковый 600 мм", taxonomy_rules=self.rules)
        brush = parse_query_spec("Кисть флейцевая 50 мм натуральная щетина", taxonomy_rules=self.rules)
        disc = parse_query_spec("Круг абразивный отрезной 125x1.0x22.23", taxonomy_rules=self.rules)
        pliers = parse_query_spec("Длинногубцы изогнутые 160 мм", taxonomy_rules=self.rules)
        clamp_tool = parse_query_spec("Струбцина F-образная 300 мм", taxonomy_rules=self.rules)
        file_tool = parse_query_spec("Напильник плоский 200 мм", taxonomy_rules=self.rules)

        self.assertEqual(winter_boots.entity_type, "safety_footwear")
        self.assertEqual(winter_boots.branch_hint, "ботинки утепленные")
        self.assertEqual(rubber_boots.entity_type, "safety_footwear")
        self.assertEqual(rubber_boots.branch_hint, "сапоги резиновые")
        self.assertEqual(crimper.entity_type, "crimping_tool")
        self.assertEqual(crimper.branch_hint, "ручные пресс-клещи и кримперы")
        self.assertEqual(micrometer.entity_type, "micrometer")
        self.assertEqual(micrometer.branch_hint, "микрометры")
        self.assertEqual(tape_measure.entity_type, "tape_measure")
        self.assertEqual(tape_measure.branch_hint, "измерительные рулетки")
        self.assertEqual(level.entity_type, "spirit_level")
        self.assertEqual(level.branch_hint, "уровни пузырьковые")
        self.assertEqual(brush.entity_type, "paint_brush")
        self.assertEqual(brush.branch_hint, "кисти плоские флейцевые")
        self.assertEqual(disc.entity_type, "abrasive_cutting_disc")
        self.assertEqual(disc.branch_hint, "абразивные отрезные диски")
        self.assertEqual(pliers.entity_type, "long_nose_pliers")
        self.assertEqual(pliers.branch_hint, "длинногубцы, утконосы и круглогубцы")
        self.assertEqual(clamp_tool.entity_type, "clamp_tool")
        self.assertEqual(clamp_tool.branch_hint, "струбцины")
        self.assertEqual(file_tool.entity_type, "file_tool")
        self.assertEqual(file_tool.branch_hint, "напильники")

    def test_parse_query_spec_detects_holiday_panel_pipe_and_hardware_queries(self):
        garland = parse_query_spec("Гирлянда LED бахрома 2м*1м теплый свет 24V", taxonomy_rules=self.rules)
        panel = parse_query_spec("Панель монтажная 2200х800 IEK", taxonomy_rules=self.rules)
        connector = parse_query_spec("Муфта соединительная G1 из сплава цинка IP54", taxonomy_rules=self.rules)
        foundation = parse_query_spec("Анкерный закладной элемент фундамента для мачты МГФ-16", taxonomy_rules=self.rules)
        hardware = parse_query_spec("Глазок дверной 16мм хром", taxonomy_rules=self.rules)
        auto_tool = parse_query_spec("Вакуумметр от -1 до 4 бар с комплектом адаптеров", taxonomy_rules=self.rules)

        self.assertEqual(garland.entity_type, "holiday_lighting")
        self.assertEqual(garland.branch_hint, "гирлянды")
        self.assertEqual(panel.entity_type, "enclosure_panel")
        self.assertEqual(panel.branch_hint, "панели и платы монтажные")
        self.assertEqual(connector.entity_type, "pipe_connector")
        self.assertEqual(connector.branch_hint, "соединители для труб")
        self.assertEqual(foundation.entity_type, "lighting_support_foundation")
        self.assertEqual(foundation.branch_hint, "закладные детали фундамента опор и мачт освещения")
        self.assertEqual(hardware.entity_type, "door_window_hardware")
        self.assertEqual(hardware.branch_hint, "фурнитура для замков, дверей и окон")
        self.assertEqual(auto_tool.entity_type, "auto_repair_tool")
        self.assertEqual(auto_tool.branch_hint, "специальный инструмент для авторемонта")

    def test_parse_query_spec_detects_self_tapping_screw_queries(self):
        screw = parse_query_spec("Саморез универсальный 4.2x32", taxonomy_rules=self.rules)

        self.assertEqual(screw.entity_type, "self_tapping_screw")
        self.assertEqual(screw.branch_hint, "саморезы универсальные")

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
        with_door = parse_query_spec("Встраиваемый силовой щит Nova 12 модулей с пластиковой дверью IP41", taxonomy_rules=self.rules)
        with_panel = parse_query_spec("Щит с монтажной панелью ЩМП-30.25.15 IP66", taxonomy_rules=self.rules)
        generic_wall = parse_query_spec("Щит распределительный навесной на 12 модулей", taxonomy_rules=self.rules)
        accessory = parse_query_spec("Козырек защитный ЩМП 300х150мм", taxonomy_rules=self.rules)

        self.assertEqual(metal.entity_type, "distribution_enclosure")
        self.assertEqual(metal.branch_hint, "корпуса учетно-распределительные встраиваемые металлические")
        self.assertEqual(plastic.entity_type, "distribution_enclosure")
        self.assertEqual(plastic.branch_hint, "корпуса распределительные встраиваемые пластиковые")
        self.assertEqual(metal_wall.entity_type, "distribution_enclosure")
        self.assertEqual(metal_wall.branch_hint, "корпуса учетно-распределительные навесные металлические")
        self.assertEqual(plastic_wall.entity_type, "distribution_enclosure")
        self.assertEqual(plastic_wall.branch_hint, "корпуса распределительные навесные пластиковые")
        self.assertEqual(with_door.entity_type, "distribution_enclosure")
        self.assertEqual(with_panel.entity_type, "distribution_enclosure")
        self.assertEqual(generic_wall.entity_type, "distribution_enclosure")
        self.assertEqual(generic_wall.branch_hint, "корпуса распределительные навесные")
        self.assertEqual(accessory.entity_type, "switchboard_accessory")
        self.assertEqual(accessory.branch_hint, "вспомогательные щитовые аксессуары")

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

    def test_parse_query_spec_detects_batch_tool_plumbing_and_heating_queries(self):
        glasses = parse_query_spec("Очки защитные закрытого типа прозрачные", taxonomy_rules=self.rules)
        bore = parse_query_spec("Нутромер индикаторный 18-35 мм", taxonomy_rules=self.rules)
        set_screwdriver = parse_query_spec("Набор отверток диэлектрических 6 шт", taxonomy_rules=self.rules)
        hex_bit = parse_query_spec("Бита шестигранная HEX 5 25мм", taxonomy_rules=self.rules)
        puller = parse_query_spec("Съемник двухлапый ручной 150 мм", taxonomy_rules=self.rules)
        clamp = parse_query_spec("Хомут для труб 32 мм оцинкованный", taxonomy_rules=self.rules)
        sewer = parse_query_spec("Отвод 110 мм для наружной канализации", taxonomy_rules=self.rules)
        siphon = parse_query_spec("Сифон бутылочный для раковины 1 1/4", taxonomy_rules=self.rules)
        countersink = parse_query_spec("Зенковка коническая 16 мм HSS", taxonomy_rules=self.rules)
        heating = parse_query_spec("Нагревательный мат теплый пол 1.5 м2", taxonomy_rules=self.rules)
        insulation = parse_query_spec("Изоляция из вспененного полиэтилена трубная 22x9", taxonomy_rules=self.rules)
        check_valve = parse_query_spec("Клапан обратный чугунный DN50", taxonomy_rules=self.rules)
        gate_valve = parse_query_spec("Задвижка чугунная клиновая DN80", taxonomy_rules=self.rules)

        self.assertEqual(glasses.entity_type, "safety_glasses")
        self.assertEqual(glasses.branch_hint, "защитные очки")
        self.assertEqual(bore.entity_type, "bore_gauge")
        self.assertEqual(bore.branch_hint, "нутромеры")
        self.assertEqual(set_screwdriver.entity_type, "screwdriver_set")
        self.assertEqual(set_screwdriver.branch_hint, "наборы отверток")
        self.assertEqual(hex_bit.entity_type, "hex_bit")
        self.assertEqual(hex_bit.branch_hint, "биты шестигранные HEX")
        self.assertEqual(puller.entity_type, "manual_puller")
        self.assertEqual(puller.branch_hint, "съемники ручные")
        self.assertEqual(clamp.entity_type, "pipe_clamp")
        self.assertEqual(clamp.branch_hint, "хомуты для труб")
        self.assertEqual(sewer.entity_type, "sewer_fitting")
        self.assertEqual(sewer.branch_hint, "фитинги для наружной канализации")
        self.assertEqual(siphon.entity_type, "siphon")
        self.assertEqual(siphon.branch_hint, "сифоны")
        self.assertEqual(countersink.entity_type, "countersink_tool")
        self.assertEqual(countersink.branch_hint, "зенкеры и зенковки")
        self.assertEqual(heating.entity_type, "heating_mat")
        self.assertEqual(heating.branch_hint, "нагревательные маты")
        self.assertEqual(insulation.entity_type, "pipe_insulation")
        self.assertEqual(insulation.branch_hint, "изоляция из вспененного полиэтилена трубная")
        self.assertEqual(check_valve.entity_type, "industrial_valve")
        self.assertEqual(check_valve.branch_hint, "клапаны обратные чугунные")
        self.assertEqual(gate_valve.entity_type, "industrial_valve")
        self.assertEqual(gate_valve.branch_hint, "задвижки чугунные клиновые")

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
