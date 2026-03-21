import unittest

from matcher import MATCH_MODE_ASSEMBLY, ReMoMatcher


class MatchTaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ReMoMatcher.__new__(ReMoMatcher)
        self.matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(self.matcher)
        self.matcher._normalize_query_terms = ReMoMatcher._normalize_query_terms.__get__(self.matcher, ReMoMatcher)
        self.matcher._normalize_text = ReMoMatcher._normalize_text.__get__(self.matcher, ReMoMatcher)
        self.matcher._clean_text_value = ReMoMatcher._clean_text_value
        self.matcher._tokenize = ReMoMatcher._tokenize.__get__(self.matcher, ReMoMatcher)
        self.matcher._classify_item_type = ReMoMatcher._classify_item_type.__get__(self.matcher, ReMoMatcher)
        self.matcher._detect_query_row_type = ReMoMatcher._detect_query_row_type.__get__(self.matcher, ReMoMatcher)
        self.matcher._extract_query_features = ReMoMatcher._extract_query_features.__get__(self.matcher, ReMoMatcher)
        self.matcher._rank_branches = ReMoMatcher._rank_branches.__get__(self.matcher, ReMoMatcher)
        self.matcher._rank_candidates = ReMoMatcher._rank_candidates.__get__(self.matcher, ReMoMatcher)
        self.matcher._branch_match_bonus = ReMoMatcher._branch_match_bonus.__get__(self.matcher, ReMoMatcher)
        self.matcher._apply_attribute_score = ReMoMatcher._apply_attribute_score.__get__(self.matcher, ReMoMatcher)
        self.matcher._score_candidates_locally = ReMoMatcher._score_candidates_locally.__get__(self.matcher, ReMoMatcher)
        self.matcher._default_branch_paths_for_family = ReMoMatcher._default_branch_paths_for_family.__get__(self.matcher, ReMoMatcher)
        self.matcher._entity_types_for_family = ReMoMatcher._entity_types_for_family.__get__(self.matcher, ReMoMatcher)
        self.matcher._duckdb_category_candidates = ReMoMatcher._duckdb_category_candidates.__get__(self.matcher, ReMoMatcher)
        self.matcher._quote_sql_identifier = ReMoMatcher._quote_sql_identifier
        self.matcher._is_disallowed_category_substitution = ReMoMatcher._is_disallowed_category_substitution.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._candidate_secondary_filter_haystack = ReMoMatcher._candidate_secondary_filter_haystack.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._hard_incompatibility_reason = ReMoMatcher._hard_incompatibility_reason.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._is_hard_incompatible_match = ReMoMatcher._is_hard_incompatible_match.__get__(self.matcher, ReMoMatcher)
        self.matcher._article_match_sanity_reason = ReMoMatcher._article_match_sanity_reason.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._should_reject_weak_resolution_in_exact_mode = ReMoMatcher._should_reject_weak_resolution_in_exact_mode.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._should_use_whole_category_retrieval = ReMoMatcher._should_use_whole_category_retrieval.__get__(self.matcher, ReMoMatcher)
        self.matcher._whole_category_secondary_filter_groups = ReMoMatcher._whole_category_secondary_filter_groups.__get__(self.matcher, ReMoMatcher)
        self.matcher._apply_whole_category_secondary_filter = ReMoMatcher._apply_whole_category_secondary_filter.__get__(self.matcher, ReMoMatcher)
        self.matcher._should_query_gemini_without_candidates = ReMoMatcher._should_query_gemini_without_candidates.__get__(self.matcher, ReMoMatcher)
        self.matcher._should_accept_weak_gemini_result = ReMoMatcher._should_accept_weak_gemini_result.__get__(self.matcher, ReMoMatcher)
        self.matcher._is_assembly_mode_enabled = ReMoMatcher._is_assembly_mode_enabled.__get__(self.matcher, ReMoMatcher)
        self.matcher._supports_assembly_fallback = ReMoMatcher._supports_assembly_fallback.__get__(self.matcher, ReMoMatcher)
        self.matcher._is_patch_cord_assembly_candidate = ReMoMatcher._is_patch_cord_assembly_candidate.__get__(
            self.matcher,
            ReMoMatcher,
        )
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

    def test_whole_category_secondary_filter_keeps_only_organizer_candidates(self):
        features = self.matcher._extract_query_features('Горизонтальный кабельный органайзер 19" в шкаф')
        candidates = [
            {
                "name": 'Горизонтальный кабельный органайзер 1U 19"',
                "normalized_name": "горизонтальный кабельный органайзер 1u 19",
                "branch_path": "телеком > аксессуары > кабельные органайзеры",
                "entity_type": "rack",
            },
            {
                "name": "Шкаф серверный напольный 42U",
                "normalized_name": "шкаф серверный напольный 42u",
                "branch_path": "телеком > аксессуары > кабельные органайзеры",
                "entity_type": "rack",
            },
        ]

        filtered = self.matcher._apply_whole_category_secondary_filter(features, candidates)

        self.assertEqual(len(filtered), 1)
        self.assertIn("органайзер", filtered[0]["normalized_name"])

    def test_whole_category_secondary_filter_narrows_bulk_twisted_pair_by_markers(self):
        features = self.matcher._extract_query_features(
            "Кабель витая пара, LSZH, неэкранированный, категория 6, внешний"
        )
        candidates = [
            {
                "name": "Кабель витая пара cat6 U/UTP LSZH outdoor 305m",
                "normalized_name": "кабель витая пара cat6 u/utp lszh outdoor 305m",
                "branch_path": "телеком > кабели > витая пара > cat6",
                "entity_type": "bulk_twisted_pair",
                "item_markers": {"category": "cat6", "shielding": "utp", "cable_environment": "outdoor"},
            },
            {
                "name": "Кабель витая пара cat6 U/UTP LSZH indoor 305m",
                "normalized_name": "кабель витая пара cat6 u/utp lszh indoor 305m",
                "branch_path": "телеком > кабели > витая пара > cat6",
                "entity_type": "bulk_twisted_pair",
                "item_markers": {"category": "cat6", "shielding": "utp", "cable_environment": "indoor"},
            },
            {
                "name": "Кабель витая пара cat6a U/UTP LSZH outdoor 305m",
                "normalized_name": "кабель витая пара cat6a u/utp lszh outdoor 305m",
                "branch_path": "телеком > кабели > витая пара > cat6",
                "entity_type": "bulk_twisted_pair",
                "item_markers": {"category": "cat6a", "shielding": "utp", "cable_environment": "outdoor"},
            },
            {
                "name": "Кабель витая пара cat6 F/UTP LSZH outdoor 305m",
                "normalized_name": "кабель витая пара cat6 f/utp lszh outdoor 305m",
                "branch_path": "телеком > кабели > витая пара > cat6",
                "entity_type": "bulk_twisted_pair",
                "item_markers": {"category": "cat6", "shielding": "ftp", "cable_environment": "outdoor"},
            },
        ]

        filtered = self.matcher._apply_whole_category_secondary_filter(features, candidates)

        self.assertEqual(len(filtered), 1)
        self.assertIn("u/utp", filtered[0]["normalized_name"])
        self.assertIn("outdoor", filtered[0]["normalized_name"])

    def test_whole_category_secondary_filter_narrows_brush_panel_by_entry_signal(self):
        features = self.matcher._extract_query_features("Щеточный ввод для ввода кабеля")
        candidates = [
            {
                "name": "Щеточный ввод для ввода кабеля 1U",
                "normalized_name": "щеточный ввод для ввода кабеля 1u",
                "branch_path": "телеком > аксессуары > шкафные аксессуары",
                "entity_type": "rack_brush_panel",
                "item_markers": {"mount_kind": "brush_panel", "rack_unit": "1"},
            },
            {
                "name": "Щеточная панель 1U 19 inch",
                "normalized_name": "щеточная панель 1u 19 inch",
                "branch_path": "телеком > аксессуары > шкафные аксессуары",
                "entity_type": "rack_brush_panel",
                "item_markers": {"mount_kind": "brush_panel", "rack_unit": "1"},
            },
            {
                "name": "Панель-заглушка 1U 19 inch",
                "normalized_name": "панель заглушка 1u 19 inch",
                "branch_path": "телеком > аксессуары > шкафные аксессуары",
                "entity_type": "rack_blank_panel",
                "item_markers": {"mount_kind": "blank_panel", "rack_unit": "1"},
            },
        ]

        filtered = self.matcher._apply_whole_category_secondary_filter(features, candidates)

        self.assertEqual(len(filtered), 1)
        self.assertIn("ввод", filtered[0]["normalized_name"])

    def test_patch_cord_assembly_candidate_accepts_patch_like_bulk_cable(self):
        self.matcher.match_mode = MATCH_MODE_ASSEMBLY
        features = self.matcher._extract_query_features("Медный патч-корд категории 6а экранированный (3м)")
        candidate = {
            "name": "Витая пара ParLan Patch S/FTP Cat 6A PVC 4х2х0.60",
            "normalized_name": "витая пара parlan patch s/ftp cat 6a pvc 4х2х0.60",
            "branch_path": "электрика > кабели",
            "entity_type": "bulk_twisted_pair",
            "item_markers": {"category": "cat6a", "shielding": "ftp"},
        }

        self.assertTrue(self.matcher._is_patch_cord_assembly_candidate(features, candidate))

    def test_patch_cord_assembly_candidate_rejects_plain_bulk_cable_without_patch_signal(self):
        self.matcher.match_mode = MATCH_MODE_ASSEMBLY
        features = self.matcher._extract_query_features("Медный патч-корд категории 6 неэкранированный (2м)")
        candidate = {
            "name": "Витая пара U/UTP Cat 6 PVC 305м",
            "normalized_name": "витая пара u/utp cat 6 pvc 305м",
            "branch_path": "электрика > кабели",
            "entity_type": "bulk_twisted_pair",
            "item_markers": {"category": "cat6", "shielding": "utp"},
        }

        self.assertFalse(self.matcher._is_patch_cord_assembly_candidate(features, candidate))

    def test_article_match_sanity_rejects_tray_query_against_light_fixture(self):
        features = self.matcher._extract_query_features(
            "Лоток перфорированный 100х50 L=3000мм, артикул 35262"
        )
        candidate = {
            "name": "Светильник светодиодный ДСО-Т03-13-30-3K-IP20",
            "normalized_name": "светильник светодиодный дсо т03 13 30 3k ip20",
            "branch_path": "свет > светильники",
            "entity_type": "other",
            "item_markers": {},
        }

        reason = self.matcher._article_match_sanity_reason(features, candidate)

        self.assertEqual(reason, "article_query_candidate_domain_mismatch")

    def test_article_match_sanity_accepts_tray_query_against_tray_candidate(self):
        features = self.matcher._extract_query_features(
            "Лоток перфорированный 100х50 L=3000мм, артикул 3526210HDZ"
        )
        candidate = {
            "name": "Лоток перфорированный 100х50 L=3000мм толщина 1.0мм горячеоцинкованный",
            "normalized_name": "лоток перфорированный 100х50 l 3000мм толщина 1 0мм горячеоцинкованный",
            "branch_path": "листовые лотки горячеоцинкованные",
            "entity_type": "other",
            "item_markers": {},
        }

        reason = self.matcher._article_match_sanity_reason(features, candidate)

        self.assertEqual(reason, "")

    def test_article_match_sanity_rejects_dimension_mismatch_for_tray_query(self):
        features = self.matcher._extract_query_features(
            "Ответвитель DL 200x50 в комплекте с крепежными элементами, артикул 36238K"
        )
        candidate = {
            "name": "Ответвитель DL 300/50 в комплекте с крепежными элементами необходимыми для монтажа",
            "normalized_name": "ответвитель dl 300/50 в комплекте с крепежными элементами необходимыми для монтажа",
            "branch_path": "кабельные лотки > аксессуары",
            "entity_type": "other",
            "item_markers": {},
        }

        reason = self.matcher._article_match_sanity_reason(features, candidate)

        self.assertEqual(reason, "article_query_candidate_dimension_mismatch")

    def test_article_match_sanity_rejects_holder_query_against_wheel_candidate(self):
        features = self.matcher._extract_query_features(
            "Держатель оцинкованный односторонний D=25-26 (100 шт.), артикул 53344"
        )
        candidate = {
            "name": "Колесо поворотное, диаметр 200мм, грузоподъемность 230кг, черная резина, сталь",
            "normalized_name": "колесо поворотное диаметр 200мм грузоподъемность 230кг черная резина сталь",
            "branch_path": "складское оборудование > колеса",
            "entity_type": "other",
            "item_markers": {},
        }

        reason = self.matcher._article_match_sanity_reason(features, candidate)

        self.assertEqual(reason, "article_query_candidate_domain_mismatch")

    def test_exact_mode_rejects_weak_resolution_for_cable_family(self):
        self.matcher.match_mode = "exact"
        features = self.matcher._extract_query_features("Кабель ВВГнг(A)-LS 4x4")

        self.assertTrue(self.matcher._should_reject_weak_resolution_in_exact_mode(features))

    def test_analog_mode_allows_weak_resolution_for_cable_family(self):
        self.matcher.match_mode = "analog"
        features = self.matcher._extract_query_features("Кабель ВВГнг(A)-LS 4x4")

        self.assertFalse(self.matcher._should_reject_weak_resolution_in_exact_mode(features))

    def test_weak_gemini_result_rejected_for_exact_mode_cable_query(self):
        self.matcher.match_mode = "exact"
        features = self.matcher._extract_query_features("Кабель ВВГнг(A)-LS 4x4")
        gemini_result = {"compatibility_status": "weakly_compatible"}

        accepted = self.matcher._should_accept_weak_gemini_result(gemini_result, [], features, "heuristic_fallback")

        self.assertFalse(accepted)

    def test_weak_gemini_result_rejected_after_article_lookup_sanity_rejection(self):
        self.matcher.match_mode = "exact"
        features = self.matcher._extract_query_features(
            "Держатель оцинкованный односторонний D=25-26 (100 шт.), артикул 53344"
        )
        features["article_lookup_rejected_reason"] = "article_query_candidate_domain_mismatch"
        gemini_result = {"compatibility_status": "weakly_compatible"}

        accepted = self.matcher._should_accept_weak_gemini_result(gemini_result, [], features, "heuristic_fallback")

        self.assertFalse(accepted)

    def test_duckdb_whole_category_queries_do_not_use_free_gemini_without_candidates(self):
        self.matcher._uses_duckdb_query_backend = lambda: True
        features = self.matcher._extract_query_features("Заглушка для управления потоком воздуха")

        self.assertTrue(self.matcher._should_use_whole_category_retrieval(features))
        self.assertFalse(self.matcher._should_query_gemini_without_candidates(features))

    def test_weak_gemini_result_is_rejected_when_local_compatible_candidates_exist(self):
        gemini_result = {"compatibility_status": "weakly_compatible"}
        compatible_entries = [{"item": {"name": "Органайзер 1U"}, "score": 0.81}]
        features = self.matcher._extract_query_features('Горизонтальный кабельный органайзер 19" в шкаф')

        self.assertFalse(
            self.matcher._should_accept_weak_gemini_result(
                gemini_result,
                compatible_entries,
                features,
                "whole_category",
            )
        )

    def test_rj45_connector_whole_category_query_includes_cable_branch(self):
        captured: dict[str, object] = {}

        def fake_fetch_items(where_sql, params, limit=None):
            captured["where_sql"] = where_sql
            captured["params"] = list(params)
            captured["limit"] = limit
            return []

        self.matcher._duckdb_fetch_items = fake_fetch_items
        query_features = {
            "entity_type": "rj45_connector",
            "row_type": "item",
            "branch_hint": "телеком > коммутация > модули",
            "original_text": "Коннектор RJ-45, неэкранированный, категория 6",
            "markers": {"category": "cat6", "shielding": "utp", "component_kind": "connector"},
        }

        category_key, items, elapsed_ms = self.matcher._duckdb_category_candidates(query_features)

        self.assertEqual(category_key, "телеком > коммутация > модули")
        self.assertEqual(items, [])
        self.assertGreaterEqual(elapsed_ms, 0.0)
        self.assertIsNone(captured["limit"])
        self.assertIn("электрика > кабели", captured["params"])
        self.assertIn("электрика > кабели > %", captured["params"])


if __name__ == "__main__":
    unittest.main()
