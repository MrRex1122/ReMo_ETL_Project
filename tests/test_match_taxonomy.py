import unittest

from matcher import ReMoMatcher


class MatchTaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ReMoMatcher.__new__(ReMoMatcher)
        self.matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(self.matcher)
        self.matcher._normalize_query_terms = ReMoMatcher._normalize_query_terms.__get__(self.matcher, ReMoMatcher)
        self.matcher._normalize_text = ReMoMatcher._normalize_text.__get__(self.matcher, ReMoMatcher)
        self.matcher._tokenize = ReMoMatcher._tokenize.__get__(self.matcher, ReMoMatcher)
        self.matcher._classify_item_type = ReMoMatcher._classify_item_type.__get__(self.matcher, ReMoMatcher)
        self.matcher._detect_query_row_type = ReMoMatcher._detect_query_row_type.__get__(self.matcher, ReMoMatcher)
        self.matcher._extract_query_features = ReMoMatcher._extract_query_features.__get__(self.matcher, ReMoMatcher)
        self.matcher._rank_branches = ReMoMatcher._rank_branches.__get__(self.matcher, ReMoMatcher)
        self.matcher._rank_candidates = ReMoMatcher._rank_candidates.__get__(self.matcher, ReMoMatcher)
        self.matcher._branch_match_bonus = ReMoMatcher._branch_match_bonus.__get__(self.matcher, ReMoMatcher)
        self.matcher._apply_attribute_score = ReMoMatcher._apply_attribute_score.__get__(self.matcher, ReMoMatcher)
        self.matcher._score_candidates_locally = ReMoMatcher._score_candidates_locally.__get__(self.matcher, ReMoMatcher)
        self.matcher._is_disallowed_category_substitution = ReMoMatcher._is_disallowed_category_substitution.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._is_hard_incompatible_match = ReMoMatcher._is_hard_incompatible_match.__get__(self.matcher, ReMoMatcher)
        self.matcher.match_mode = "exact"
        self.matcher.branch_index = {
            "телеком > питание > pdu": [],
            "телеком > питание > pdu > zero u": [],
            "телеком > коммутация > патч панели": [],
        }
        self.matcher.branch_prefix_index = {
            "телеком > питание > pdu": [],
            "телеком > питание > pdu > zero u": [],
            "телеком > коммутация > патч панели": [],
        }
        self.matcher.branch_token_index = {
            "pdu": ["телеком > питание > pdu", "телеком > питание > pdu > zero u"],
            "zero": ["телеком > питание > pdu > zero u"],
            "u": ["телеком > питание > pdu > zero u"],
            "блок": ["телеком > питание > pdu"],
        }
        self.matcher.branch_priority_scores = {
            "телеком > питание > pdu > zero u": 0.35,
            "телеком > питание > pdu": 0.25,
        }
        self.matcher.token_idf = {"pdu": 2.0, "zero": 2.5, "блок": 1.5}

    def test_detect_query_row_type_marks_section_rows(self):
        self.assertEqual(self.matcher._detect_query_row_type("Шкафы телекоммуникационные"), "section")

    def test_rank_branches_prefers_zero_u_pdu_path(self):
        features = self.matcher._extract_query_features("Вертикальный блок розеток PDU Zero U")
        ranked = self.matcher._rank_branches(features)

        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["path"], "телеком > питание > pdu > zero u")

    def test_score_candidates_locally_prefers_zero_u_candidate(self):
        features = self.matcher._extract_query_features("Вертикальный блок розеток PDU Zero U")
        features["ranked_branches"] = [
            {"path": "телеком > питание > pdu > zero u", "score": 8.0},
            {"path": "телеком > питание > pdu", "score": 6.0},
        ]

        zero_u = {
            "name": "Вертикальный блок розеток PDU Zero U",
            "name_lc": "вертикальный блок розеток pdu zero u",
            "normalized_name": "вертикальный блок розеток pdu zero u",
            "article": "PDU-ZU",
            "price": 100.0,
            "row_idx": 1,
            "tokens": ["вертикальный", "блок", "розеток", "pdu", "zero", "u"],
            "branch_path": "телеком > питание > pdu > zero u",
            "entity_type": "pdu",
        }
        one_u = {
            "name": "Горизонтальный блок розеток PDU 1U",
            "name_lc": "горизонтальный блок розеток pdu 1u",
            "normalized_name": "горизонтальный блок розеток pdu 1u",
            "article": "PDU-1U",
            "price": 95.0,
            "row_idx": 2,
            "tokens": ["горизонтальный", "блок", "розеток", "pdu", "1u"],
            "branch_path": "телеком > питание > pdu",
            "entity_type": "pdu",
        }
        self.matcher.catalog_items = [zero_u, one_u]
        self.matcher.token_index = {
            "блок": [zero_u, one_u],
            "розеток": [zero_u, one_u],
            "pdu": [zero_u, one_u],
            "zero": [zero_u],
            "u": [zero_u],
        }

        ranked = self.matcher._score_candidates_locally(features, [zero_u, one_u])

        self.assertEqual(ranked[0]["item"]["article"], "PDU-ZU")
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])

    def test_detect_query_row_type_marks_sks_as_section(self):
        self.assertEqual(self.matcher._detect_query_row_type("СКС"), "section")

    def test_hard_incompatibility_blocks_power_cord_to_pdu(self):
        features = self.matcher._extract_query_features(
            "Кабель электрический соединительный 230VAC 16A IEC320 C19-C20"
        )
        item = {
            "name": "Блок распределения питания PDU Ippon Basic 1 U",
            "normalized_name": "блок распределения питания pdu ippon basic 1 u",
            "branch_path": "телеком > питание > pdu",
            "entity_type": "pdu",
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))

    def test_hard_incompatibility_blocks_ats_to_breaker(self):
        features = self.matcher._extract_query_features("Статический переключатель ATS/STS 16A")
        item = {
            "name": "Автоматический выключатель BKN-b 3P+N C16A",
            "normalized_name": "автоматический выключатель bkn b 3p n c16a",
            "branch_path": "электрика > автоматы",
            "entity_type": "breaker",
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))

    def test_hard_incompatibility_blocks_ats_to_soft_starter(self):
        features = self.matcher._extract_query_features("Статический переключатель ATS/STS 30(32)A")
        item = {
            "name": "Устройство плавного пуска STS22 30 кВт",
            "normalized_name": "устройство плавного пуска sts22 30 квт",
            "branch_path": "электрика > приводы",
            "entity_type": "soft_starter",
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "ats_sts_vs_soft_starter")


    def test_hard_incompatibility_blocks_temperature_sensor_to_reed(self):
        features = self.matcher._extract_query_features("Датчик температуры и влажности")
        item = {
            "name": "Датчик герконовый магнитоконтактный",
            "normalized_name": "датчик герконовый магнитоконтактный",
            "branch_path": "автоматика > датчики",
            "entity_type": "reed_sensor",
            "item_markers": {"sensor_kind": "reed"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "sensor_type_mismatch")

    def test_hard_incompatibility_blocks_shelf_to_rails(self):
        features = self.matcher._extract_query_features("Полка консольная 1U 19''")
        item = {
            "name": "Комплект монтажных рельс 1U",
            "normalized_name": "комплект монтажных рельс 1u",
            "branch_path": "телеком > аксессуары > шкафные аксессуары",
            "entity_type": "rack_rail",
            "item_markers": {"mount_kind": "rail", "rack_unit": "1"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "rack_accessory_type_mismatch")

    def test_hard_incompatibility_blocks_rj45_connector_to_power_cable(self):
        features = self.matcher._extract_query_features("Коннектор RJ-45 cat6")
        item = {
            "name": "Кабель силовой C13-C14 2м",
            "normalized_name": "кабель силовой c13-c14 2м",
            "branch_path": "электрика > кабели",
            "entity_type": "iec_power_cable",
            "item_markers": {"connector_pair": "c13-c14"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "entity_family_mismatch")

    def test_optical_cross_is_strict_and_blocks_non_optical_items(self):
        features = self.matcher._extract_query_features("Оптический кросс на 48 волокон 1U")
        item = {
            "name": "Блок управления противопожарным клапаном",
            "normalized_name": "блок управления противопожарным клапаном",
            "branch_path": "автоматика > управление",
            "entity_type": "other",
        }

        self.assertEqual(self.matcher._match_strictness_for_query(features), "strict")
        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "optical_cross_family_mismatch")

    def test_airflow_blanking_panel_rejects_generic_module_blank(self):
        features = self.matcher._extract_query_features("Заглушка для управления потоком воздуха 1U")
        item = {
            "name": "Заглушка на 4 модуля для встраиваемых щитков",
            "normalized_name": "заглушка на 4 модуля для встраиваемых щитков",
            "branch_path": "электрика > щитки",
            "entity_type": "rack_blank_panel",
            "item_markers": {"mount_kind": "blank_panel"},
        }

        self.assertEqual(self.matcher._match_strictness_for_query(features), "strict")
        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "airflow_blanking_family_mismatch")

    def test_patch_panel_blocks_non_panel_items(self):
        features = self.matcher._extract_query_features(
            "Панель коммутационная неэкранированной 24 порта, блочная, категория 6"
        )
        item = {
            "name": "Пена монтажная Roof Complect огнеупорная",
            "normalized_name": "пена монтажная roof complect огнеупорная",
            "branch_path": "прочее",
            "entity_type": "other",
        }

        self.assertEqual(self.matcher._match_strictness_for_query(features), "strict")
        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "patch_panel_family_mismatch")

    def test_strict_fallback_rejects_cross_family_candidate(self):
        features = self.matcher._extract_query_features(
            "Панель коммутационная неэкранированной 24 порта, блочная, категория 6"
        )
        wrong_item = {
            "name": "Пена монтажная Roof Complect огнеупорная",
            "normalized_name": "пена монтажная roof complect огнеупорная",
            "branch_path": "прочее",
            "entity_type": "other",
        }
        valid_item = {
            "name": "Патч-панель 1U категории 6 UTP 24 порта",
            "normalized_name": "патч панель 1u категории 6 utp 24 порта",
            "branch_path": "телеком > коммутация > патч панели",
            "entity_type": "patch_panel",
            "item_markers": {"category": "cat6", "shielding": "utp", "port_count": "24", "rack_unit": "1"},
        }

        self.assertFalse(self.matcher._is_strict_fallback_allowed(features, wrong_item))
        self.assertTrue(self.matcher._is_strict_fallback_allowed(features, valid_item))

    def test_gemini_family_gate_rejects_cross_family_for_optical_cross(self):
        features = self.matcher._extract_query_features("Оптический кросс на 24 волокна 1U")
        wrong_item = {
            "name": "Термометр биметаллический",
            "normalized_name": "термометр биметаллический",
            "branch_path": "измерение > термометры",
            "entity_type": "other",
        }
        valid_item = {
            "name": "Оптический кросс 24 волокна 1U",
            "normalized_name": "оптический кросс 24 волокна 1u",
            "branch_path": "телеком > оптика > кроссы",
            "entity_type": "optical_cross",
        }

        self.assertFalse(self.matcher._is_gemini_result_family_valid(features, wrong_item))
        self.assertTrue(self.matcher._is_gemini_result_family_valid(features, valid_item))

    def test_compatibility_penalty_marks_weak_mismatch(self):
        features = self.matcher._extract_query_features("Оптический патч-корд LC-LC duplex OS2 2м")
        item = {
            "name": "Оптический патч-корд LC-LC duplex OM3 2м",
            "normalized_name": "оптический патч-корд lc-lc duplex om3 2м",
            "branch_path": "телеком > кабели > оптические патч корды",
            "entity_type": "optical_patch_cord",
            "item_markers": {"connector_pair": "lc-lc", "duplex": "yes", "fiber_mode": "om3", "length_m": "2"},
        }

        self.assertFalse(self.matcher._is_hard_incompatible_match(features, item))
        self.assertGreater(self.matcher._compatibility_penalty(features, item), 0.2)
        self.assertEqual(self.matcher._compatibility_label(features, item), "weakly_compatible")


    def test_bulk_twisted_pair_with_explicit_markers_becomes_strict(self):
        features = self.matcher._extract_query_features(
            "Кабель витая пара, LSZH, неэкранированный, категория 6, внешний"
        )

        self.assertEqual(features["attributes"].get("category"), "cat6")
        self.assertEqual(self.matcher._match_strictness_for_query(features), "strict")

    def test_hard_incompatibility_blocks_bulk_twisted_pair_category_mismatch(self):
        features = self.matcher._extract_query_features(
            "Кабель витая пара, LSZH, неэкранированный, категория 6"
        )
        item = {
            "name": "Витая пара категория 5e U/UTP LSZH 305 м",
            "normalized_name": "витая пара категория 5e u/utp lszh 305 м",
            "branch_path": "телеком > кабели > витая пара > cat5e",
            "entity_type": "bulk_twisted_pair",
            "item_markers": {"category": "cat5e", "shielding": "utp"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "category_mismatch")

    def test_hard_incompatibility_blocks_outdoor_bulk_twisted_pair_to_indoor(self):
        features = self.matcher._extract_query_features(
            "Кабель витая пара, LSZH, неэкранированный, категория 6, внешний"
        )
        item = {
            "name": "Витая пара U/UTP категория 6 LSZH",
            "normalized_name": "витая пара u/utp категория 6 lszh",
            "branch_path": "телеком > кабели > витая пара > cat6",
            "entity_type": "bulk_twisted_pair",
            "item_markers": {"category": "cat6", "shielding": "utp", "cable_environment": "indoor"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "cable_environment_mismatch")


    def test_patch_panel_blocks_missing_category_and_ports(self):
        features = self.matcher._extract_query_features(
            "Панель коммутационная неэкранированной 24 порта, блочная, категория 6"
        )
        item = {
            "name": "Панель 19 1U",
            "normalized_name": "панель 19 1u",
            "branch_path": "телеком > аксессуары > шкафные аксессуары",
            "entity_type": "patch_panel",
            "item_markers": {"rack_unit": "1"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "category_mismatch")

    def test_keystone_blocks_adapter_and_missing_category(self):
        features = self.matcher._extract_query_features("Модуль Keystone, экранированный, категория 6a")
        item = {
            "name": "Avanti Адаптер для Keystone 1 модуль",
            "normalized_name": "avanti адаптер для keystone 1 модуль",
            "branch_path": "телеком > коммутация > модули",
            "entity_type": "keystone_module",
            "item_markers": {"component_kind": "adapter"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "category_mismatch")

    def test_rj45_outlet_blocks_faceplate_only_items(self):
        features = self.matcher._extract_query_features(
            "Конструктив сетевой розетки для одного порта RJ-45 в лючок напольный в сборе"
        )
        item = {
            "name": "Лицевая панель для информационных розеток Keystone 2 модуля",
            "normalized_name": "лицевая панель для информационных розеток keystone 2 модуля",
            "branch_path": "телеком > коммутация > модули",
            "entity_type": "keystone_module",
            "item_markers": {"component_kind": "faceplate"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "rj45_component_mismatch")

    def test_rj45_outlet_blocks_wrong_installation_kind_for_floor_box_assembly(self):
        features = self.matcher._extract_query_features(
            "Конструктив сетевой розетки для одного порта RJ-45 в лючок напольный в сборе"
        )
        item = {
            "name": "Розетка компьютерная 1-местная RJ-45",
            "normalized_name": "розетка компьютерная 1 местная rj 45",
            "branch_path": "телеком > коммутация > модули",
            "entity_type": "rj45_outlet",
            "item_markers": {"component_kind": "outlet", "installation_kind": "outlet_module", "port_count": "1"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "rj45_component_mismatch")

    def test_rj45_outlet_blocks_single_port_for_two_port_cable_channel_assembly(self):
        features = self.matcher._extract_query_features(
            "Конструктив сетевой розетки для двух портов RJ-45 в кабель-канал, в сборе"
        )
        item = {
            "name": "Розетка компьютерная 1-местная RJ-45",
            "normalized_name": "розетка компьютерная 1 местная rj 45",
            "branch_path": "телеком > коммутация > модули",
            "entity_type": "rj45_outlet",
            "item_markers": {"component_kind": "outlet", "installation_kind": "outlet_module", "port_count": "1"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "rj45_component_mismatch")


if __name__ == "__main__":
    unittest.main()
