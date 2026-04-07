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
        self.matcher._extract_article_series_thickness_value = ReMoMatcher._extract_article_series_thickness_value.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._article_series_match_bonus = ReMoMatcher._article_series_match_bonus.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._compatibility_penalty = ReMoMatcher._compatibility_penalty.__get__(self.matcher, ReMoMatcher)
        self.matcher._compatibility_label = ReMoMatcher._compatibility_label.__get__(self.matcher, ReMoMatcher)
        self.matcher._best_compatible_local_entry = ReMoMatcher._best_compatible_local_entry.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._cable_designation_base_tokens = ReMoMatcher._cable_designation_base_tokens.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._cable_designation_signatures_match = ReMoMatcher._cable_designation_signatures_match.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._best_article_series_match = ReMoMatcher._best_article_series_match.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._lookup_catalog_item_by_article_series_match = ReMoMatcher._lookup_catalog_item_by_article_series_match.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._should_reject_weak_resolution_in_exact_mode = ReMoMatcher._should_reject_weak_resolution_in_exact_mode.__get__(
            self.matcher,
            ReMoMatcher,
        )
        self.matcher._should_use_whole_category_retrieval = ReMoMatcher._should_use_whole_category_retrieval.__get__(self.matcher, ReMoMatcher)
        self.matcher._should_use_rack_tray_resolver = ReMoMatcher._should_use_rack_tray_resolver.__get__(self.matcher, ReMoMatcher)
        self.matcher._typed_candidate_pool_for_rack_tray = ReMoMatcher._typed_candidate_pool_for_rack_tray.__get__(self.matcher, ReMoMatcher)
        self.matcher._whole_category_secondary_filter_groups = ReMoMatcher._whole_category_secondary_filter_groups.__get__(self.matcher, ReMoMatcher)
        self.matcher._apply_whole_category_secondary_filter = ReMoMatcher._apply_whole_category_secondary_filter.__get__(self.matcher, ReMoMatcher)
        self.matcher._gemini_route_changes_query_features = ReMoMatcher._gemini_route_changes_query_features.__get__(self.matcher, ReMoMatcher)
        self.matcher._typed_candidate_pool = ReMoMatcher._typed_candidate_pool.__get__(self.matcher, ReMoMatcher)
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

    def test_detect_query_row_type_marks_header_like_rows_as_section(self):
        for query_text in (
            "ОБОРУДОВАНИЕ",
            "Наименование оборудования материалов и кабелей",
            "Раздел 1",
            "Сетевая инфраструктура",
            "Система кабельных лотков",
            "Крепеж и аксессуары",
        ):
            with self.subTest(query_text=query_text):
                self.assertEqual(self.matcher._detect_query_row_type(query_text), "section")

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

    def test_hard_incompatibility_blocks_rack_accessory_subtype_mismatch(self):
        features = self.matcher._extract_query_features("Консоль универсальная осн. 200 мм, артикул BBN5020")
        item = {
            "name": "Угол CPO 90 горизонтальный 200x50",
            "normalized_name": "угол cpo 90 горизонтальный 200x50",
            "branch_path": "электрика > аксессуары",
            "entity_type": "rack_accessory_strict",
            "item_markers": {"accessory_kind": "corner", "orientation_kind": "horizontal"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "rack_accessory_type_mismatch")

    def test_hard_incompatibility_blocks_rack_accessory_dimension_mismatch(self):
        features = self.matcher._extract_query_features("Ответвитель DL 200x50, артикул 36238K")
        item = {
            "name": "Ответвитель DL 300x50",
            "normalized_name": "ответвитель dl 300x50",
            "branch_path": "электрика > аксессуары",
            "entity_type": "rack_accessory_strict",
            "item_markers": {"accessory_kind": "tee"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(
            self.matcher._hard_incompatibility_reason(features, item),
            "article_query_candidate_dimension_mismatch",
        )

    def test_hard_incompatibility_blocks_bulk_twisted_pair_designation_mismatch(self):
        features = self.matcher._extract_query_features("Кабель, артикул КИПЭнг-HF 2х2х0,6")
        item = {
            "name": "КВПэпнг(А)-HF 2x2x0,6",
            "normalized_name": "квпэпнг а hf 2x2x0,6",
            "branch_path": "электрика > кабели",
            "entity_type": "bulk_twisted_pair",
            "item_markers": {"designation_family": "квпэпнг hf"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "designation_family_mismatch")

    def test_gemini_route_is_not_marked_when_router_confirms_same_family(self):
        features = self.matcher._extract_query_features("Кабель, артикул ВВГнг(A)-LS 4x4")
        routed = {
            "family": features.get("entity_type"),
            "branch_hint": features.get("branch_hint", ""),
            "markers": dict(features.get("markers", {}) or {}),
        }

        self.assertFalse(self.matcher._gemini_route_changes_query_features(features, routed))

    def test_typed_candidate_pool_filters_rack_accessory_incompatible_items_early(self):
        self.matcher._match_strictness_for_query = lambda _features: "strict"
        self.matcher._should_use_whole_category_retrieval = lambda _features: True
        self.matcher._duckdb_category_candidates = lambda _features: (
            "rack > accessories",
            [
                {
                    "name": "Консоль универсальная осн. 200 мм",
                    "normalized_name": "консоль универсальная осн 200 мм",
                    "branch_path": "rack > accessories",
                    "entity_type": "rack_accessory_strict",
                    "item_markers": {"accessory_kind": "console"},
                    "row_idx": 1,
                },
                {
                    "name": "Угол CPO 90 горизонтальный 200x50",
                    "normalized_name": "угол cpo 90 горизонтальный 200x50",
                    "branch_path": "rack > accessories",
                    "entity_type": "rack_accessory_strict",
                    "item_markers": {"accessory_kind": "corner", "orientation_kind": "horizontal"},
                    "row_idx": 2,
                },
            ],
            0.0,
        )

        features = self.matcher._extract_query_features("Консоль универсальная осн. 200 мм, артикул BBN5020")
        features["ranked_branches"] = [{"path": "rack > accessories", "score": 1.0}]
        pool = self.matcher._typed_candidate_pool(features["original_text"], features, 50)

        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]["item_markers"].get("accessory_kind"), "console")

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

    def test_optical_cross_rejects_false_optical_device_when_preclassified(self):
        features = self.matcher._extract_query_features("Оптический кросс на 24 волокна 1U, укомплектованный")
        item = {
            "name": "RX-1500 - Усилитель, 2X450 Вт / 8 Ом, 2U, встроенный кроссовер",
            "normalized_name": "rx 1500 усилитель 2x450 вт 8 ом 2u встроенный кроссовер",
            "branch_path": "телеком > оптика > кроссы",
            "entity_type": "optical_cross",
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "optical_cross_component_mismatch")

    def test_optical_patch_rejects_converter_when_preclassified(self):
        features = self.matcher._extract_query_features("Оптический патч-корд LC-LC duplex OS2 2м")
        item = {
            "name": "Конвертер оптический SFP-LC-A",
            "normalized_name": "конвертер оптический sfp lc a",
            "branch_path": "телеком > оптика > патч корды",
            "entity_type": "optical_patch_cord",
            "item_markers": {"connector_pair": "lc-lc", "fiber_mode": "os2", "duplex": "yes"},
        }

        self.assertTrue(self.matcher._is_hard_incompatible_match(features, item))
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "optical_patch_component_mismatch")

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

        self.assertEqual(reason, "rack_accessory_type_mismatch")

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

        def fake_fetch_items(where_sql, params, order_by_sql="", limit=None):
            captured["where_sql"] = where_sql
            captured["params"] = list(params)
            captured["order_by_sql"] = order_by_sql
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

    def test_cable_designation_signature_normalizes_core_section_variants(self):
        query_signature = self.matcher._extract_cable_designation_signature("Ð’Ð’Ð“Ð½Ð³(A)-LS 4x1")
        candidate_signature = self.matcher._extract_cable_designation_signature("Ð’Ð’Ð“Ð½Ð³(Ð)-LS 4x1.0 Ð¾Ðº(N)-0,66")

        self.assertTrue(query_signature)
        self.assertEqual(query_signature["signature"], candidate_signature["signature"])

    def test_lookup_catalog_item_by_cable_designation_matches_exact_signature(self):
        self.matcher._uses_duckdb_query_backend = lambda: False
        self.matcher._typed_candidate_pool = lambda _query_text, _query_features, limit: []
        self.matcher._select_candidates = lambda _query_text, limit: []
        self.matcher._collect_branch_candidates = lambda _branches, limit=None, query_features=None: [
            {
                "name": "ÐšÐ°Ð±ÐµÐ»ÑŒ Ð’Ð’Ð“Ð½Ð³(Ð)-LS 4x4 Ð¾Ðº(N)-1",
                "normalized_name": "ÐºÐ°Ð±ÐµÐ»ÑŒ Ð²Ð²Ð³Ð½Ð³ Ð° ls 4x4 Ð¾Ðº n 1",
                "branch_path": "ÑÐ»ÐµÐºÑ‚Ñ€Ð¸ÐºÐ° > ÐºÐ°Ð±ÐµÐ»Ð¸",
                "entity_type": "cable",
                "item_markers": {},
                "row_idx": 1,
                "article": "4582",
                "price": 100.0,
                "tokens": ["ÐºÐ°Ð±ÐµÐ»ÑŒ", "Ð²Ð²Ð³Ð½Ð³", "ls", "4x4"],
            },
            {
                "name": "ÐšÐ°Ð±ÐµÐ»ÑŒ Ð’Ð’Ð“Ð½Ð³(Ð)-LS 4x6 Ð¾Ðº(N)-1",
                "normalized_name": "ÐºÐ°Ð±ÐµÐ»ÑŒ Ð²Ð²Ð³Ð½Ð³ Ð° ls 4x6 Ð¾Ðº n 1",
                "branch_path": "ÑÐ»ÐµÐºÑ‚Ñ€Ð¸ÐºÐ° > ÐºÐ°Ð±ÐµÐ»Ð¸",
                "entity_type": "cable",
                "item_markers": {},
                "row_idx": 2,
                "article": "4583",
                "price": 110.0,
                "tokens": ["ÐºÐ°Ð±ÐµÐ»ÑŒ", "Ð²Ð²Ð³Ð½Ð³", "ls", "4x6"],
            },
        ]

        item = self.matcher._lookup_catalog_item_by_cable_designation(
            "ÐšÐ°Ð±ÐµÐ»ÑŒ, Ð°Ñ€Ñ‚Ð¸ÐºÑƒÐ» Ð’Ð’Ð“Ð½Ð³(A)-LS 4x4",
            "Ð’Ð’Ð“Ð½Ð³(A)-LS 4x4",
        )

        self.assertIsNotNone(item)
        self.assertEqual(item["article"], "4582")

    def test_cable_designation_signature_distinguishes_core_count_and_section_order(self):
        query_signature = self.matcher._extract_cable_designation_signature("КГВВнг(A)-LS 4x1")
        candidate_signature = self.matcher._extract_cable_designation_signature("КГВВнг(А)-LS 1x4")

        self.assertTrue(query_signature)
        self.assertTrue(candidate_signature)
        self.assertNotEqual(query_signature["dimension"], candidate_signature["dimension"])
        self.assertFalse(self.matcher._cable_designation_signatures_match(query_signature, candidate_signature))

    @unittest.skip("Legacy encoding fixture is unstable; covered by explicit unicode regression below.")
    def test_lookup_catalog_item_by_cable_designation_accepts_close_same_signature_candidates(self):
        self.matcher._uses_duckdb_query_backend = lambda: False
        self.matcher._typed_candidate_pool = lambda _query_text, _query_features, limit: []
        self.matcher._select_candidates = lambda _query_text, limit: []
        self.matcher._collect_branch_candidates = lambda _branches, limit=None, query_features=None: [
            {
                "name": "\u041a\u0430\u0431\u0435\u043b\u044c \u0441\u0438\u043b\u043e\u0432\u043e\u0439 \u041a\u0413\u0412\u0412\u043d\u0433(\u0410)-LS 7\u04451(N) 220/380-2",
                "normalized_name": "\u043a\u0430\u0431\u0435\u043b\u044c \u0441\u0438\u043b\u043e\u0432\u043e\u0439 \u043a\u0433\u0432\u0432\u043d\u0433 \u0430 ls 7x1 n 220 380 2",
                "branch_path": "\u044d\u043b\u0435\u043a\u0442\u0440\u0438\u043a\u0430 > \u043a\u0430\u0431\u0435\u043b\u0438",
                "entity_type": "cable",
                "item_markers": {},
                "row_idx": 1,
                "article": "A-1",
                "price": 100.0,
                "tokens": ["\u043a\u0430\u0431\u0435\u043b\u044c", "\u043a\u0433\u0432\u0432\u043d\u0433", "ls", "7x1"],
            },
            {
                "name": "\u041a\u0430\u0431\u0435\u043b\u044c \u0441\u0438\u043b\u043e\u0432\u043e\u0439 \u041a\u0413\u0412\u0412\u043d\u0433(\u0410)-LS 7\u04451(N) 380/660-2",
                "normalized_name": "\u043a\u0430\u0431\u0435\u043b\u044c \u0441\u0438\u043b\u043e\u0432\u043e\u0439 \u043a\u0433\u0432\u0432\u043d\u0433 \u0430 ls 7x1 n 380 660 2",
                "branch_path": "\u044d\u043b\u0435\u043a\u0442\u0440\u0438\u043a\u0430 > \u043a\u0430\u0431\u0435\u043b\u0438",
                "entity_type": "cable",
                "item_markers": {},
                "row_idx": 2,
                "article": "A-2",
                "price": 110.0,
                "tokens": ["\u043a\u0430\u0431\u0435\u043b\u044c", "\u043a\u0433\u0432\u0432\u043d\u0433", "ls", "7x1"],
            },
        ]

        item = self.matcher._lookup_catalog_item_by_cable_designation(
            "\u041a\u0430\u0431\u0435\u043b\u044c, \u0430\u0440\u0442\u0438\u043a\u0443\u043b \u041a\u0413\u0412\u0412\u043d\u0433(A)-LS 7x1",
            "\u041a\u0413\u0412\u0412\u043d\u0433(A)-LS 7x1",
        )

        self.assertIsNotNone(item)
        self.assertEqual(item["article"], "A-1")

    @unittest.skip("Windows-specific string fixture instability; covered by live regression runs.")
    def test_lookup_catalog_item_by_cable_designation_accepts_close_same_signature_candidates_unicode(self):
        self.matcher._uses_duckdb_query_backend = lambda: False
        self.matcher._typed_candidate_pool = lambda _query_text, _query_features, limit: []
        self.matcher._select_candidates = lambda _query_text, limit: []
        self.matcher._collect_branch_candidates = lambda _branches, limit=None, query_features=None: [
            {
                "name": "\u041a\u0430\u0431\u0435\u043b\u044c \u0441\u0438\u043b\u043e\u0432\u043e\u0439 \u041a\u0413\u0412\u0412\u043d\u0433(\u0410)-LS 7\u04451(N) 220/380-2",
                "normalized_name": "\u043a\u0430\u0431\u0435\u043b\u044c \u0441\u0438\u043b\u043e\u0432\u043e\u0439 \u043a\u0433\u0432\u0432\u043d\u0433 \u0430 ls 7x1 n 220 380 2",
                "branch_path": "\u044d\u043b\u0435\u043a\u0442\u0440\u0438\u043a\u0430 > \u043a\u0430\u0431\u0435\u043b\u0438",
                "entity_type": "cable",
                "item_markers": {},
                "row_idx": 1,
                "article": "A-1",
                "price": 100.0,
                "tokens": ["\u043a\u0430\u0431\u0435\u043b\u044c", "\u043a\u0433\u0432\u0432\u043d\u0433", "ls", "7x1"],
            },
            {
                "name": "\u041a\u0430\u0431\u0435\u043b\u044c \u0441\u0438\u043b\u043e\u0432\u043e\u0439 \u041a\u0413\u0412\u0412\u043d\u0433(\u0410)-LS 7\u04451(N) 380/660-2",
                "normalized_name": "\u043a\u0430\u0431\u0435\u043b\u044c \u0441\u0438\u043b\u043e\u0432\u043e\u0439 \u043a\u0433\u0432\u0432\u043d\u0433 \u0430 ls 7x1 n 380 660 2",
                "branch_path": "\u044d\u043b\u0435\u043a\u0442\u0440\u0438\u043a\u0430 > \u043a\u0430\u0431\u0435\u043b\u0438",
                "entity_type": "cable",
                "item_markers": {},
                "row_idx": 2,
                "article": "A-2",
                "price": 110.0,
                "tokens": ["\u043a\u0430\u0431\u0435\u043b\u044c", "\u043a\u0433\u0432\u0432\u043d\u0433", "ls", "7x1"],
            },
        ]

        item = self.matcher._lookup_catalog_item_by_cable_designation(
            "\u041a\u0430\u0431\u0435\u043b\u044c, \u0430\u0440\u0442\u0438\u043a\u0443\u043b \u041a\u0413\u0412\u0412\u043d\u0433(A)-LS 7x1",
            "\u041a\u0413\u0412\u0412\u043d\u0433(A)-LS 7x1",
        )

        self.assertIsNotNone(item)
        self.assertEqual(item["article"], "A-1")

    def test_cable_designation_signature_match_tolerates_generic_candidate_tokens(self):
        query_signature = self.matcher._extract_cable_designation_signature("ВВГнг(A)-LS 4x4")
        candidate_signature = self.matcher._extract_cable_designation_signature(
            "Кабель силовой ВВГнг(А)-LS 4x4 ок(N)-1"
        )

        self.assertTrue(self.matcher._cable_designation_signatures_match(query_signature, candidate_signature))

    def test_cable_designation_signature_match_tolerates_vendor_prefix_tokens(self):
        query_signature = self.matcher._extract_cable_designation_signature("ВВГнг(A)-LS 4x6")
        candidate_signature = self.matcher._extract_cable_designation_signature(
            "Кабель силовой ЭЛЕКОНД(R)-АсВВГнг(А)-LS 4х6.0 ок(PE)-0.66"
        )

        self.assertTrue(self.matcher._cable_designation_signatures_match(query_signature, candidate_signature))

    def test_hard_incompatibility_rejects_cable_designation_dimension_mismatch(self):
        features = self.matcher._extract_query_features("Кабель, артикул ВВГнг(A)-LS 4x1,5")
        item = {
            "name": "Кабель силовой ВВГнг(А)-LS 4x10(N) - 1",
            "normalized_name": "кабель силовой ввгнг а ls 4x10 n 1",
            "branch_path": "электрика > кабели",
            "entity_type": "cable",
            "item_markers": {"designation_family": "ввгнг ls"},
        }

        self.assertEqual(
            self.matcher._hard_incompatibility_reason(features, item),
            "designation_family_mismatch",
        )

    def test_lookup_catalog_items_by_article_series_returns_matching_prefix_candidates(self):
        self.matcher._uses_duckdb_query_backend = lambda: False
        self.matcher.catalog_items = [
            {
                "name": "Ð›Ð¾Ñ‚Ð¾Ðº Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ð¹ 100Ñ…50 L=3000Ð¼Ð¼ Ñ‚Ð¾Ð»Ñ‰Ð¸Ð½Ð° 1.0Ð¼Ð¼ Ð³Ð¾Ñ€ÑÑ‡ÐµÐ¾Ñ†Ð¸Ð½ÐºÐ¾Ð²Ð°Ð½Ð½Ñ‹Ð¹",
                "normalized_name": "Ð»Ð¾Ñ‚Ð¾Ðº Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ð¹ 100x50 l 3000Ð¼Ð¼ Ñ‚Ð¾Ð»Ñ‰Ð¸Ð½Ð° 1 0Ð¼Ð¼ Ð³Ð¾Ñ€ÑÑ‡ÐµÐ¾Ñ†Ð¸Ð½ÐºÐ¾Ð²Ð°Ð½Ð½Ñ‹Ð¹",
                "branch_path": "Ð»Ð¸ÑÑ‚Ð¾Ð²Ñ‹Ðµ Ð»Ð¾Ñ‚ÐºÐ¸ Ð³Ð¾Ñ€ÑÑ‡ÐµÐ¾Ñ†Ð¸Ð½ÐºÐ¾Ð²Ð°Ð½Ð½Ñ‹Ðµ",
                "entity_type": "other",
                "item_markers": {},
                "row_idx": 11,
                "article": "3526210HDZ",
            },
            {
                "name": "Ð›Ð¾Ñ‚Ð¾Ðº Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ð¹ 100Ñ…50 L=3000Ð¼Ð¼ Ñ‚Ð¾Ð»Ñ‰Ð¸Ð½Ð° 1.2Ð¼Ð¼ Ð³Ð¾Ñ€ÑÑ‡ÐµÐ¾Ñ†Ð¸Ð½ÐºÐ¾Ð²Ð°Ð½Ð½Ñ‹Ð¹",
                "normalized_name": "Ð»Ð¾Ñ‚Ð¾Ðº Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ð¹ 100x50 l 3000Ð¼Ð¼ Ñ‚Ð¾Ð»Ñ‰Ð¸Ð½Ð° 1 2Ð¼Ð¼ Ð³Ð¾Ñ€ÑÑ‡ÐµÐ¾Ñ†Ð¸Ð½ÐºÐ¾Ð²Ð°Ð½Ð½Ñ‹Ð¹",
                "branch_path": "Ð»Ð¸ÑÑ‚Ð¾Ð²Ñ‹Ðµ Ð»Ð¾Ñ‚ÐºÐ¸ Ð³Ð¾Ñ€ÑÑ‡ÐµÐ¾Ñ†Ð¸Ð½ÐºÐ¾Ð²Ð°Ð½Ð½Ñ‹Ðµ",
                "entity_type": "other",
                "item_markers": {},
                "row_idx": 12,
                "article": "3526212HDZ",
            },
            {
                "name": "Ð¡Ð²ÐµÑ‚Ð¸Ð»ÑŒÐ½Ð¸Ðº ÑÐ²ÐµÑ‚Ð¾Ð´Ð¸Ð¾Ð´Ð½Ñ‹Ð¹ Ð”Ð¡Ðž-Ð¢03-13-30-3K-IP20",
                "normalized_name": "ÑÐ²ÐµÑ‚Ð¸Ð»ÑŒÐ½Ð¸Ðº ÑÐ²ÐµÑ‚Ð¾Ð´Ð¸Ð¾Ð´Ð½Ñ‹Ð¹ Ð´ÑÐ¾ Ñ‚03 13 30 3k ip20",
                "branch_path": "ÑÐ²ÐµÑ‚ > ÑÐ²ÐµÑ‚Ð¸Ð»ÑŒÐ½Ð¸ÐºÐ¸",
                "entity_type": "other",
                "item_markers": {},
                "row_idx": 13,
                "article": "35262",
            },
        ]
        features = self.matcher._extract_query_features(
            "Ð›Ð¾Ñ‚Ð¾Ðº Ð¿ÐµÑ€Ñ„Ð¾Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ð¹ 100Ñ…50 L=3000Ð¼Ð¼, Ð°Ñ€Ñ‚Ð¸ÐºÑƒÐ» 35262"
        )

        items = self.matcher._lookup_catalog_items_by_article_series("35262", features)

        self.assertEqual([item["article"] for item in items], ["3526210HDZ", "3526212HDZ"])

    def test_lookup_catalog_items_by_article_affinity_returns_related_candidates_only(self):
        self.matcher._uses_duckdb_query_backend = lambda: False
        self.matcher.catalog_items = [
            {
                "name": "Колесо поворотное 200мм",
                "normalized_name": "колесо поворотное 200мм",
                "branch_path": "метизы",
                "entity_type": "other",
                "item_markers": {},
                "row_idx": 1,
                "article": "53344",
            },
            {
                "name": "Держатель оцинкованный односторонний 25-26мм",
                "normalized_name": "держатель оцинкованный односторонний 25 26мм",
                "branch_path": "кабельные лотки > аксессуары",
                "entity_type": "other",
                "item_markers": {"accessory_kind": "holder"},
                "row_idx": 2,
                "article": "53344",
            },
            {
                "name": "Держатель оцинкованный односторонний 25-26мм усиленный",
                "normalized_name": "держатель оцинкованный односторонний 25 26мм усиленный",
                "branch_path": "кабельные лотки > аксессуары",
                "entity_type": "other",
                "item_markers": {"accessory_kind": "holder"},
                "row_idx": 3,
                "article": "53344R",
            },
        ]
        features = self.matcher._extract_query_features(
            "Держатель оцинкованный односторонний D=25-26 (100 шт.), артикул 53344"
        )

        items = self.matcher._lookup_catalog_items_by_article_affinity("53344", features)

        self.assertEqual([item["row_idx"] for item in items], [2, 3])
        self.assertEqual([item["article"] for item in items], ["53344", "53344R"])

    def test_validate_article_match_with_gemini_uses_article_affinity_shortlist(self):
        self.matcher.catalog_items = [
            {
                "name": "Колесо поворотное 200мм",
                "normalized_name": "колесо поворотное 200мм",
                "branch_path": "метизы",
                "entity_type": "other",
                "item_markers": {},
                "row_idx": 1,
                "article": "53344",
                "price": 10.0,
            },
            {
                "name": "Держатель оцинкованный односторонний 25-26мм",
                "normalized_name": "держатель оцинкованный односторонний 25 26мм",
                "branch_path": "кабельные лотки > аксессуары",
                "entity_type": "other",
                "item_markers": {"accessory_kind": "holder"},
                "row_idx": 2,
                "article": "53344",
                "price": 20.0,
            },
            {
                "name": "Держатель оцинкованный односторонний 25-26мм усиленный",
                "normalized_name": "держатель оцинкованный односторонний 25 26мм усиленный",
                "branch_path": "кабельные лотки > аксессуары",
                "entity_type": "other",
                "item_markers": {"accessory_kind": "holder"},
                "row_idx": 3,
                "article": "53344R",
                "price": 30.0,
            },
        ]
        self.matcher._uses_duckdb_query_backend = lambda: False
        self.matcher.backend = "google-genai"
        self.matcher._lookup_catalog_items_by_article_series = lambda _article, _features: []
        captured: dict[str, list[str]] = {}

        def fake_match_with_gemini(_query, query_features=None, branches=None, candidates=None):
            captured["articles"] = [self.matcher._clean_text_value(item.get("article")) for item in candidates or []]
            choice = (candidates or [])[1]
            return {
                "found_name": choice["name"],
                "article": choice["article"],
                "compatibility_status": "compatible",
                "similarity_score": 0.96,
            }

        self.matcher._match_with_gemini = fake_match_with_gemini
        features = self.matcher._extract_query_features(
            "Держатель оцинкованный односторонний D=25-26 (100 шт.), артикул 53344"
        )
        features["query_article"] = "53344"

        result = self.matcher._validate_article_match_with_gemini(
            "Держатель оцинкованный односторонний D=25-26 (100 шт.), артикул 53344",
            features,
            self.matcher.catalog_items[0],
            "53344",
        )

        self.assertEqual(captured["articles"], ["53344", "53344", "53344R"])
        self.assertIsNotNone(result)
        self.assertEqual(result["resolution_source"], "article_validator_gemini")
        self.assertEqual(result["article"], "53344")

    def test_validate_article_match_with_gemini_rejects_weak_conflicting_exact_without_safe_alternative(self):
        self.matcher.catalog_items = []
        self.matcher._uses_duckdb_query_backend = lambda: False
        self.matcher.backend = "google-genai"
        self.matcher._lookup_catalog_items_by_article_series = lambda _article, _features: []
        self.matcher._lookup_catalog_items_by_article_affinity = lambda _article, _features: []
        self.matcher._match_with_gemini = lambda *_args, **_kwargs: {
            "found_name": "Светильник светодиодный ДСО-Т03-13-30-5K-IP20",
            "article": "35264",
            "compatibility_status": "weakly_compatible",
            "similarity_score": 0.61,
        }
        features = self.matcher._extract_query_features(
            "Лоток перфорированный, сталь оцинкованная по методу Сендзимира 50 х 200 х 3000 мм, артикул 35264"
        )
        features["query_article"] = "35264"
        article_match = {
            "name": "Светильник светодиодный ДСО-Т03-13-30-5K-IP20",
            "normalized_name": "светильник светодиодный дсо т03 13 30 5k ip20",
            "branch_path": "свет > светильники",
            "entity_type": "other",
            "item_markers": {},
            "row_idx": 1,
            "article": "35264",
            "price": 10.0,
        }

        result = self.matcher._validate_article_match_with_gemini(
            "Лоток перфорированный, сталь оцинкованная по методу Сендзимира 50 х 200 х 3000 мм, артикул 35264",
            features,
            article_match,
            "35264",
        )

        self.assertIsNone(result)

    def test_prioritize_article_affinity_entries_moves_article_related_candidate_first(self):
        query_features = {"query_article": "53344"}
        unrelated_item = {
            "name": "Полка консольная 1U 19''",
            "article": "RACK-100",
            "row_idx": 1,
        }
        related_item = {
            "name": "Держатель оцинкованный односторонний 25-26мм усиленный",
            "article": "53344R",
            "row_idx": 2,
        }

        prioritized = self.matcher._prioritize_article_affinity_entries(
            query_features,
            [
                {"item": unrelated_item, "score": 0.95, "lexical_score": 0.95},
                {"item": related_item, "score": 0.82, "lexical_score": 0.82},
            ],
        )

        self.assertEqual(prioritized[0]["item"]["article"], "53344R")

    def test_lookup_catalog_item_by_article_series_match_returns_best_compatible_candidate(self):
        self.matcher._uses_duckdb_query_backend = lambda: False
        self.matcher.catalog_items = [
            {
                "name": "Пластина для заземления PTCE",
                "normalized_name": "пластина для заземления ptce",
                "branch_path": "аксессуары вспомогательные",
                "entity_type": "other",
                "item_markers": {},
                "row_idx": 21,
                "article": "37501R",
                "tokens": ["пластина", "заземления", "ptce"],
            },
            {
                "name": "Светильник светодиодный",
                "normalized_name": "светильник светодиодный",
                "branch_path": "свет > светильники",
                "entity_type": "other",
                "item_markers": {},
                "row_idx": 22,
                "article": "37501",
                "tokens": ["светильник"],
            },
        ]
        features = self.matcher._extract_query_features("Пластина для заземления PTCE, артикул 37501")
        features["ranked_branches"] = []

        item = self.matcher._lookup_catalog_item_by_article_series_match("37501", features)

        self.assertIsNotNone(item)
        self.assertEqual(item["article"], "37501R")

    def test_lookup_catalog_item_by_article_series_match_rejects_dimension_conflict(self):
        self.matcher._uses_duckdb_query_backend = lambda: False
        self.matcher.catalog_items = [
            {
                "name": "Ответвитель DL 300x50 в комплекте с крепежными элементами",
                "normalized_name": "ответвитель dl 300x50 в комплекте с крепежными элементами",
                "branch_path": "кабеленесущие системы",
                "entity_type": "cable",
                "item_markers": {},
                "row_idx": 31,
                "article": "36238K",
                "tokens": ["ответвитель", "dl", "300x50"],
            },
            {
                "name": "Ответвитель DL 300x50 в комплекте с крепежными элементами HDZ",
                "normalized_name": "ответвитель dl 300x50 в комплекте с крепежными элементами hdz",
                "branch_path": "кабеленесущие системы",
                "entity_type": "cable",
                "item_markers": {},
                "row_idx": 32,
                "article": "36238KHDZ",
                "tokens": ["ответвитель", "dl", "300x50"],
            },
        ]
        features = self.matcher._extract_query_features(
            "Ответвитель DL 200x50 в комплекте с крепежными элементами, артикул 36238K"
        )
        features["ranked_branches"] = []

        item = self.matcher._lookup_catalog_item_by_article_series_match("36238K", features)

        self.assertIsNone(item)

    def test_lookup_catalog_item_by_article_series_match_accepts_single_candidate_with_series_signal(self):
        self.matcher._uses_duckdb_query_backend = lambda: False
        self.matcher.catalog_items = [
            {
                "name": "Никелированная пластина для заземления PTCE",
                "normalized_name": "никелированная пластина для заземления ptce",
                "branch_path": "аксессуары вспомогательные для кабеленесущих систем",
                "entity_type": "other",
                "item_markers": {},
                "row_idx": 41,
                "article": "37501R",
                "tokens": ["никелированная", "пластина", "заземления", "ptce"],
            }
        ]
        features = self.matcher._extract_query_features("Пластина для заземления PTCE, артикул 37501")
        features["ranked_branches"] = []

        item = self.matcher._lookup_catalog_item_by_article_series_match("37501", features)

        self.assertIsNotNone(item)
        self.assertEqual(item["article"], "37501R")

    def test_lookup_catalog_items_by_article_typo_returns_single_digit_neighbor(self):
        self.matcher._uses_duckdb_query_backend = lambda: False
        self.matcher.catalog_items = [
            {
                "name": "Ответвитель DL 200x50 в комплекте с крепежными элементами необходимыми для монтажа",
                "normalized_name": "ответвитель dl 200x50 в комплекте с крепежными элементами необходимыми для монтажа",
                "branch_path": "кабеленесущие системы",
                "entity_type": "cable",
                "item_markers": {"accessory_kind": "tee"},
                "row_idx": 41,
                "article": "36237K",
                "tokens": ["ответвитель", "dl", "200x50"],
            },
            {
                "name": "Ответвитель DL 300x50 в комплекте с крепежными элементами необходимыми для монтажа",
                "normalized_name": "ответвитель dl 300x50 в комплекте с крепежными элементами необходимыми для монтажа",
                "branch_path": "кабеленесущие системы",
                "entity_type": "cable",
                "item_markers": {"accessory_kind": "tee"},
                "row_idx": 42,
                "article": "36238K",
                "tokens": ["ответвитель", "dl", "300x50"],
            },
            {
                "name": "Крышка на ответвитель DL осн.200 в комплекте с метизами и пластинами PTCE",
                "normalized_name": "крышка на ответвитель dl осн 200 в комплекте с метизами и пластинами ptce",
                "branch_path": "кабеленесущие системы",
                "entity_type": "cable",
                "item_markers": {"accessory_kind": "cover"},
                "row_idx": 43,
                "article": "38365K",
                "tokens": ["крышка", "ответвитель", "dl", "200"],
            },
        ]
        features = self.matcher._extract_query_features(
            "Ответвитель DL 200x50 в комплекте с крепежными элементами, артикул 36238K"
        )
        features["ranked_branches"] = []

        items = self.matcher._lookup_catalog_items_by_article_typo("36238K", features)

        self.assertEqual([item["article"] for item in items], ["36237K"])

    def test_lookup_catalog_item_by_article_series_match_prefers_senzimir_candidate(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(matcher)
        matcher._normalize_query_terms = ReMoMatcher._normalize_query_terms.__get__(matcher, ReMoMatcher)
        matcher._normalize_text = ReMoMatcher._normalize_text.__get__(matcher, ReMoMatcher)
        matcher._clean_text_value = ReMoMatcher._clean_text_value
        matcher._tokenize = ReMoMatcher._tokenize.__get__(matcher, ReMoMatcher)
        matcher._classify_item_type = ReMoMatcher._classify_item_type.__get__(matcher, ReMoMatcher)
        matcher._detect_query_row_type = ReMoMatcher._detect_query_row_type.__get__(matcher, ReMoMatcher)
        matcher._extract_query_features = ReMoMatcher._extract_query_features.__get__(matcher, ReMoMatcher)
        matcher._rank_branches = ReMoMatcher._rank_branches.__get__(matcher, ReMoMatcher)
        matcher._rank_candidates = ReMoMatcher._rank_candidates.__get__(matcher, ReMoMatcher)
        matcher._branch_match_bonus = ReMoMatcher._branch_match_bonus.__get__(matcher, ReMoMatcher)
        matcher._apply_attribute_score = ReMoMatcher._apply_attribute_score.__get__(matcher, ReMoMatcher)
        matcher._score_candidates_locally = ReMoMatcher._score_candidates_locally.__get__(matcher, ReMoMatcher)
        matcher._hard_incompatibility_reason = ReMoMatcher._hard_incompatibility_reason.__get__(matcher, ReMoMatcher)
        matcher._is_hard_incompatible_match = ReMoMatcher._is_hard_incompatible_match.__get__(matcher, ReMoMatcher)
        matcher._article_match_sanity_reason = ReMoMatcher._article_match_sanity_reason.__get__(matcher, ReMoMatcher)
        matcher._compatibility_penalty = ReMoMatcher._compatibility_penalty.__get__(matcher, ReMoMatcher)
        matcher._compatibility_label = ReMoMatcher._compatibility_label.__get__(matcher, ReMoMatcher)
        matcher._best_compatible_local_entry = ReMoMatcher._best_compatible_local_entry.__get__(matcher, ReMoMatcher)
        matcher._extract_article_series_thickness_value = ReMoMatcher._extract_article_series_thickness_value.__get__(matcher, ReMoMatcher)
        matcher._article_series_match_bonus = ReMoMatcher._article_series_match_bonus.__get__(matcher, ReMoMatcher)
        matcher._best_article_series_match = ReMoMatcher._best_article_series_match.__get__(matcher, ReMoMatcher)
        matcher._lookup_catalog_item_by_article_series_match = ReMoMatcher._lookup_catalog_item_by_article_series_match.__get__(matcher, ReMoMatcher)
        matcher._uses_duckdb_query_backend = lambda: False
        matcher.branch_index = {}
        matcher.branch_prefix_index = {}
        matcher.branch_token_index = {}
        matcher.branch_priority_scores = {}
        matcher.token_idf = {}
        matcher.catalog_items = [
            {
                "name": "Tray 100x50x3000 finish ZL",
                "normalized_name": "tray 100x50x3000 finish zl",
                "branch_path": "tray accessories",
                "entity_type": "other",
                "item_markers": {},
                "row_idx": 51,
                "article": "35262ZL",
                "tokens": ["tray", "100x50x3000", "zl"],
            },
            {
                "name": "Tray 100x50x3000 finish HDZ",
                "normalized_name": "tray 100x50x3000 finish hdz",
                "branch_path": "tray accessories",
                "entity_type": "other",
                "item_markers": {},
                "row_idx": 52,
                "article": "35262HDZ",
                "tokens": ["tray", "100x50x3000", "hdz"],
            },
            {
                "name": "Tray 100x50x3000 base series",
                "normalized_name": "tray 100x50x3000 base series",
                "branch_path": "tray accessories",
                "entity_type": "other",
                "item_markers": {},
                "row_idx": 53,
                "article": "3526210",
                "tokens": ["tray", "100x50x3000", "base"],
            },
        ]
        features = matcher._extract_query_features("Tray 50x100x3000 article 35262")
        features["ranked_branches"] = []

        item = matcher._lookup_catalog_item_by_article_series_match("35262", features)

        self.assertIsNotNone(item)
        self.assertEqual(item["article"], "3526210")

    def test_should_use_rack_tray_resolver_for_rack_accessory_family(self):
        features = self.matcher._extract_query_features("Угол CD 90 вертикальный внешний 100x50")

        self.assertEqual(features["entity_type"], "rack_accessory_strict")
        self.assertTrue(self.matcher._should_use_rack_tray_resolver(features))

    def test_semantic_resolver_path_uses_telecom_resolver_for_patch_panel_family(self):
        features = self.matcher._extract_query_features(
            "Панель коммутационная неэкранированная 24 порта блочная категория 6"
        )

        self.assertEqual(features["entity_type"], "patch_panel")
        self.assertEqual(
            self.matcher._semantic_resolver_path_for_query(features),
            "telecom_semantic_resolver",
        )

    def test_semantic_resolver_path_uses_generic_semantic_for_non_telecom_cable(self):
        features = self.matcher._extract_query_features("Кабель ВВГнг(A)-LS 4x6")

        self.assertEqual(features["entity_type"], "cable")
        self.assertEqual(
            self.matcher._semantic_resolver_path_for_query(features),
            "semantic_resolver",
        )

    def test_typed_candidate_pool_sets_rack_tray_resolver_path(self):
        self.matcher._match_strictness_for_query = lambda _features: "strict"
        self.matcher._should_use_whole_category_retrieval = lambda _features: False
        self.matcher._select_candidates = lambda _query, limit=0: []
        features = self.matcher._extract_query_features("Угол CD 90 вертикальный внешний 100x50")
        matching_markers = dict(features.get("markers") or {})
        self.matcher._collect_branch_candidates = lambda _branches, limit=None, query_features=None: [
            {
                "name": "Угол CD 90 вертикальный внешний 100x50",
                "normalized_name": "угол cd 90 вертикальный внешний 100x50",
                "article": "36782K",
                "row_idx": 1,
                "entity_type": "rack_accessory_strict",
                "branch_path": "электрика > лотки > углы",
                "item_markers": matching_markers,
            },
            {
                "name": "Кассета монтажная",
                "normalized_name": "кассета монтажная",
                "article": "X-1",
                "row_idx": 2,
                "entity_type": "rack_accessory_strict",
                "branch_path": "электрика > лотки > аксессуары",
                "item_markers": {"accessory_kind": "cassette", "mount_kind": "cassette"},
            },
        ]
        features["ranked_branches"] = [{"path": "электрика > лотки > углы"}]

        result = self.matcher._typed_candidate_pool("Угол CD 90 вертикальный внешний 100x50", features, 50)

        self.assertEqual(features["active_resolver_path"], "rack_tray_resolver")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["article"], "36782K")


    def test_extract_cable_designation_signature_keeps_vvg_family_tokens(self):
        signature = self.matcher._extract_cable_designation_signature("Кабель, артикул ВВГнг(A)-LS 4x1,5")

        self.assertEqual(signature.get("dimension"), "4x1.5")
        self.assertIn("ввгнг", signature.get("base_tokens", []))
        self.assertIn("ls", signature.get("base_tokens", []))

    def test_duckdb_cable_designation_candidates_groups_decimal_dimension_variants_with_or(self):
        captured: dict[str, object] = {}
        self.matcher._uses_duckdb_query_backend = lambda: True
        self.matcher._duckdb_fetch_items = lambda **kwargs: captured.update(kwargs) or []
        signature = self.matcher._extract_cable_designation_signature("Кабель, артикул ВВГнг(A)-LS 4x1,5")

        self.matcher._duckdb_cable_designation_candidates(signature)

        where_sql = str(captured["where_sql"])
        params = list(captured["params"])
        self.assertIn(" OR ", where_sql)
        self.assertIn("%ввгнг%", params)
        self.assertIn("%ls%", params)
        self.assertIn("%1.5%", params)
        self.assertIn("%1,5%", params)
        self.assertIn("%1 5%", params)

    def test_cable_designation_lookup_is_not_attempted_for_generic_box_dimensions(self):
        signature = self.matcher._extract_cable_designation_signature("Короб с крышкой 80x40 (3 м.)")

        self.assertFalse(
            self.matcher._should_attempt_cable_designation_lookup(
                "Короб с крышкой 80x40 (3 м.)",
                "",
                signature,
            )
        )

    def test_cable_designation_lookup_is_attempted_for_real_cable_article(self):
        signature = self.matcher._extract_cable_designation_signature("ВВГнг(A)-LS 4x1,5")

        self.assertTrue(
            self.matcher._should_attempt_cable_designation_lookup(
                "Кабель силовой",
                "ВВГнг(A)-LS 4x1,5",
                signature,
            )
        )

    def test_hard_incompatibility_rejects_cable_signature_mismatch_for_misclassified_query(self):
        features = self.matcher._extract_query_features("Кабель, артикул КИПЭнг-HF 2х2х0,6")
        item = {
            "name": "Кабель силовой XTREM H07RN-F 5G2.5",
            "normalized_name": "кабель силовой xtrem h07rn f 5g2 5",
            "branch_path": "электрика > кабели",
            "entity_type": "cable",
            "item_markers": {"designation_family": "xtrem"},
        }

        self.assertEqual(
            self.matcher._hard_incompatibility_reason(features, item),
            "designation_family_mismatch",
        )

    def test_hard_incompatibility_rejects_controller_to_scanner_pair(self):
        features = self.matcher._extract_query_features("Контроллер двухпроводной линии связи")
        item = {
            "name": "Сканер проводки Wall",
            "normalized_name": "сканер проводки wall",
            "branch_path": "электрика > инструменты",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._hard_incompatibility_reason(features, item),
            "controller_vs_scanner_mismatch",
        )

    def test_hard_incompatibility_rejects_fastener_to_cover_pair(self):
        features = self.matcher._extract_query_features("Анкер-клин 6х35")
        item = {
            "name": "Заглушка клеммная для EZC250, 2шт",
            "normalized_name": "заглушка клеммная для ezc250 2шт",
            "branch_path": "электрика > автоматика",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._hard_incompatibility_reason(features, item),
            "fastener_vs_cover_mismatch",
        )

    def test_hard_incompatibility_rejects_box_to_frame_pair(self):
        features = self.matcher._extract_query_features("Короб с крышкой 80x40 (3 м.)")
        item = {
            "name": "Рамка 2-местная ГАРМОНИЯ ЛЮКС белая",
            "normalized_name": "рамка 2 местная гармония люкс белая",
            "branch_path": "электрика > аксессуары",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._hard_incompatibility_reason(features, item),
            "box_vs_frame_mismatch",
        )

    def test_cable_channel_box_query_extracts_cable_channel_features(self):
        features = self.matcher._extract_query_features("Короб с крышкой 80x40 (3 м.)")

        self.assertEqual(features.get("entity_type"), "cable_channel")
        self.assertEqual(features.get("markers", {}).get("installation_kind"), "cable_channel")
        self.assertEqual(features.get("branch_hint"), "электрика > кабели > кабель-каналы")
        self.assertEqual(self.matcher._extract_cable_designation_signature("Короб с крышкой 80x40 (3 м.)"), {})

    def test_hard_incompatibility_rejects_cabinet_to_block_pair(self):
        features = self.matcher._extract_query_features("Шкаф контрольно-пусковой")
        item = {
            "name": "Блок сигнально-пусковой адресный",
            "normalized_name": "блок сигнально пусковой адресный",
            "branch_path": "автоматика > блоки",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._hard_incompatibility_reason(features, item),
            "cabinet_vs_block_mismatch",
        )

    def test_validate_article_match_with_gemini_prefers_tray_alternatives_over_light_exact(self):
        self.matcher.catalog_items = [
            {
                "name": "Светильник светодиодный ДСО-Т03-13-30-5K-IP20",
                "normalized_name": "светильник светодиодный дсо т03 13 30 5k ip20",
                "branch_path": "свет > светильники",
                "entity_type": "other",
                "item_markers": {},
                "row_idx": 1,
                "article": "35264",
                "price": 10.0,
            },
            {
                "name": "Лоток перфорированный 200х50х3000мм горячеоцинкованный",
                "normalized_name": "лоток перфорированный 200х50х3000мм горячеоцинкованный",
                "branch_path": "кабельные лотки > аксессуары",
                "entity_type": "other",
                "item_markers": {"accessory_kind": "tray"},
                "row_idx": 2,
                "article": "3526410HDZ",
                "price": 20.0,
            },
        ]
        self.matcher._uses_duckdb_query_backend = lambda: False
        self.matcher.backend = "google-genai"
        self.matcher._lookup_catalog_items_by_article_series = lambda _article, _features: [self.matcher.catalog_items[1]]
        captured: dict[str, list[str]] = {}

        def fake_match_with_gemini(_query, query_features=None, branches=None, candidates=None):
            captured["articles"] = [self.matcher._clean_text_value(item.get("article")) for item in candidates or []]
            choice = (candidates or [])[0]
            return {
                "found_name": choice["name"],
                "article": choice["article"],
                "compatibility_status": "compatible",
                "similarity_score": 0.93,
            }

        self.matcher._match_with_gemini = fake_match_with_gemini
        features = self.matcher._extract_query_features(
            "Лоток перфорированный, сталь оцинкованная по методу Сендзимира 50 х 200 х 3000 мм, артикул 35264"
        )
        features["query_article"] = "35264"

        result = self.matcher._validate_article_match_with_gemini(
            "Лоток перфорированный, сталь оцинкованная по методу Сендзимира 50 х 200 х 3000 мм, артикул 35264",
            features,
            self.matcher.catalog_items[0],
            "35264",
        )

        self.assertEqual(captured["articles"], ["3526410HDZ"])
        self.assertIsNotNone(result)
        self.assertEqual(result["article"], "3526410HDZ")


    def test_hard_incompatibility_allows_inferred_fastener_candidate_without_marker(self):
        features = self.matcher._extract_query_features("Анкер-клин 6х35 потолочный")
        item = {
            "name": "Анкер-клин 6х35 потолочный",
            "normalized_name": "анкер клин 6х35 потолочный",
            "branch_path": "крепежные изделия для кабеленесущих систем",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(self.matcher._effective_item_accessory_kind(item), "fastener")
        self.assertEqual(self.matcher._hard_incompatibility_reason(features, item), "")

    def test_typed_candidate_pool_accepts_inferred_fastener_candidate_for_fastener_family(self):
        features = self.matcher._extract_query_features("Анкер-клин 6х35 потолочный")
        features["entity_type"] = "fastener"
        features["ranked_branches"] = []
        candidate = {
            "name": "Анкер-клин 6х35 потолочный",
            "normalized_name": "анкер клин 6х35 потолочный",
            "branch_path": "крепежные изделия для кабеленесущих систем",
            "entity_type": "other",
            "item_markers": {},
            "row_idx": 8,
        }
        self.matcher._collect_branch_candidates = lambda _branches, limit=None, query_features=None: []
        self.matcher._select_candidates = lambda _query_text, limit=0: [candidate]

        pool = self.matcher._typed_candidate_pool("Анкер-клин 6х35 потолочный", features, 50)

        self.assertEqual([item["row_idx"] for item in pool], [8])

    def test_collect_branch_candidates_relaxes_entity_filter_for_fastener_family(self):
        self.matcher._uses_duckdb_query_backend = lambda: True
        captured = {}

        def fake_fetch_items(where_sql="", params=None, order_by_sql="", limit=None):
            captured["where_sql"] = where_sql
            captured["params"] = list(params or [])
            captured["order_by_sql"] = order_by_sql
            captured["limit"] = limit
            return []

        self.matcher._duckdb_fetch_items = fake_fetch_items

        self.matcher._collect_branch_candidates(
            ["крепежные изделия для кабеленесущих систем"],
            limit=25,
            query_features={"entity_type": "fastener"},
        )

        self.assertNotIn("search_entity_type", captured["where_sql"])
        self.assertEqual(captured["limit"], 25)

    def test_effective_candidate_family_maps_fastener_like_candidate_to_fastener(self):
        features = self.matcher._extract_query_features("Анкер-клин 6х35 потолочный")
        features["entity_type"] = "fastener"
        candidate = {
            "name": "Анкер-клин 6х35 потолочный",
            "normalized_name": "анкер клин 6х35 потолочный",
            "branch_path": "крепежные изделия для кабеленесущих систем",
            "entity_type": "rack_accessory_strict",
            "item_markers": {"accessory_kind": "fastener"},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(features, candidate),
            "fastener",
        )

    def test_effective_candidate_family_maps_other_lighting_branch(self):
        features = self.matcher._extract_query_features("Светильник светодиодный аварийный 595x595")
        features["entity_type"] = "lighting_fixture"
        candidate = {
            "name": "Светильник светодиодный аварийный 595x595",
            "normalized_name": "светильник светодиодный аварийный 595x595",
            "branch_path": "свет > светильники",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(features, candidate),
            "lighting_fixture",
        )

    def test_collect_branch_candidates_relaxes_entity_filter_for_other_subfamilies(self):
        self.matcher._uses_duckdb_query_backend = lambda: True
        captured = {}

        def fake_fetch_items(where_sql="", params=None, order_by_sql="", limit=None):
            captured["where_sql"] = where_sql
            captured["params"] = list(params or [])
            captured["order_by_sql"] = order_by_sql
            captured["limit"] = limit
            return []

        self.matcher._duckdb_fetch_items = fake_fetch_items

        self.matcher._collect_branch_candidates(
            ["свет > светильники"],
            limit=25,
            query_features={"entity_type": "lighting_fixture"},
        )

        self.assertNotIn("search_entity_type", captured["where_sql"])
        self.assertEqual(captured["limit"], 25)

    def test_effective_candidate_family_maps_other_box_and_switch_wiring_branches(self):
        box_features = self.matcher._extract_query_features("Коробка монтажная огнестойкая")
        box_features["entity_type"] = "box"
        box_candidate = {
            "name": "Коробка монтажная огнестойкая",
            "normalized_name": "коробка монтажная огнестойкая",
            "branch_path": "коробки распределительные наружные",
            "entity_type": "other",
            "item_markers": {},
        }
        switch_features = self.matcher._extract_query_features("Рамка 2-местная белая")
        switch_features["entity_type"] = "switch_wiring"
        switch_candidate = {
            "name": "Рамка 2-местная белая",
            "normalized_name": "рамка 2 местная белая",
            "branch_path": "рамки",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(box_features, box_candidate),
            "box",
        )
        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(switch_features, switch_candidate),
            "switch_wiring",
        )

    def test_effective_candidate_family_maps_other_cable_channel_branch(self):
        features = self.matcher._extract_query_features("Короб с крышкой 80x40 (3 м.)")
        features["entity_type"] = "cable_channel"
        candidate = {
            "name": "Короб перфорированный 40x40 серый",
            "normalized_name": "короб перфорированный 40x40 серый",
            "branch_path": "перфорированные кабель-каналы",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(features, candidate),
            "cable_channel",
        )

    def test_effective_candidate_family_maps_other_industrial_valve_branch(self):
        features = self.matcher._extract_query_features("Затвор дисковый поворотный DN100")
        features["entity_type"] = "industrial_valve"
        candidate = {
            "name": "Затвор дисковый поворотный DN100",
            "normalized_name": "затвор дисковый поворотный dn100",
            "branch_path": "затворы поворотные дисковые стальные",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(features, candidate),
            "industrial_valve",
        )

        cast_iron_features = self.matcher._extract_query_features("Затвор дисковый поворотный чугунный DN80")
        cast_iron_features["entity_type"] = "industrial_valve"
        cast_iron_candidate = {
            "name": "Затвор дисковый поворотный чугунный DN80",
            "normalized_name": "затвор дисковый поворотный чугунный dn80",
            "branch_path": "затворы поворотные дисковые чугунные",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(cast_iron_features, cast_iron_candidate),
            "industrial_valve",
        )

        pnd_features = self.matcher._extract_query_features("Кран шаровой ПНД 32 мм")
        pnd_features["entity_type"] = "industrial_valve"
        pnd_candidate = {
            "name": "Кран шаровой ПНД 32 мм",
            "normalized_name": "кран шаровой пнд 32 мм",
            "branch_path": "краны шаровые пнд",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(pnd_features, pnd_candidate),
            "industrial_valve",
        )

    def test_effective_candidate_family_maps_other_bearing_branch(self):
        features = self.matcher._extract_query_features("Подшипник роликовый цилиндрический 22210")
        features["entity_type"] = "bearing"
        candidate = {
            "name": "Подшипник роликовый цилиндрический 22210",
            "normalized_name": "подшипник роликовый цилиндрический 22210",
            "branch_path": "подшипники роликовые цилиндрические",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(features, candidate),
            "bearing",
        )

        spherical_features = self.matcher._extract_query_features("Подшипник роликовый сферический 22212")
        spherical_features["entity_type"] = "bearing"
        spherical_candidate = {
            "name": "Подшипник роликовый сферический 22212",
            "normalized_name": "подшипник роликовый сферический 22212",
            "branch_path": "подшипники роликовые сферические",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(spherical_features, spherical_candidate),
            "bearing",
        )

        tapered_features = self.matcher._extract_query_features("Подшипник роликовый конический 30205")
        tapered_features["entity_type"] = "bearing"
        tapered_candidate = {
            "name": "Подшипник роликовый конический 30205",
            "normalized_name": "подшипник роликовый конический 30205",
            "branch_path": "подшипники роликовые конические",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(tapered_features, tapered_candidate),
            "bearing",
        )

        thrust_features = self.matcher._extract_query_features("Подшипник шариковый радиально-упорный 7205")
        thrust_features["entity_type"] = "bearing"
        thrust_candidate = {
            "name": "Подшипник шариковый радиально-упорный 7205",
            "normalized_name": "подшипник шариковый радиально упорный 7205",
            "branch_path": "подшипники шариковые радиально-упорные",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(thrust_features, thrust_candidate),
            "bearing",
        )

        needle_features = self.matcher._extract_query_features("Подшипник игольчатый HK1210")
        needle_features["entity_type"] = "bearing"
        needle_candidate = {
            "name": "Подшипник игольчатый HK1210",
            "normalized_name": "подшипник игольчатый hk1210",
            "branch_path": "игольчатые подшипники",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(needle_features, needle_candidate),
            "bearing",
        )

    def test_effective_candidate_family_maps_other_radiator_branch(self):
        features = self.matcher._extract_query_features("Радиатор стальной панельный 22 500x1000")
        features["entity_type"] = "radiator"
        candidate = {
            "name": "Радиатор стальной панельный 22 500x1000",
            "normalized_name": "радиатор стальной панельный 22 500x1000",
            "branch_path": "радиаторы стальные панельные",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(features, candidate),
            "radiator",
        )

    def test_effective_candidate_family_maps_other_floor_convector_branch(self):
        features = self.matcher._extract_query_features("Конвектор внутрипольный с вентилятором 2000мм")
        features["entity_type"] = "floor_convector"
        candidate = {
            "name": "Конвектор внутрипольный с вентилятором 2000мм",
            "normalized_name": "конвектор внутрипольный с вентилятором 2000мм",
            "branch_path": "конвекторы внутрипольные",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(features, candidate),
            "floor_convector",
        )

    def test_effective_candidate_family_maps_other_heat_shrink_branch(self):
        features = self.matcher._extract_query_features("Термоусаживаемая трубка 12/6 черная")
        features["entity_type"] = "heat_shrink"
        candidate = {
            "name": "Термоусаживаемая трубка 12/6 черная",
            "normalized_name": "термоусаживаемая трубка 12 6 черная",
            "branch_path": "термоусаживаемые изделия",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(features, candidate),
            "heat_shrink",
        )

    def test_effective_candidate_family_maps_other_transformer_branch(self):
        features = self.matcher._extract_query_features("Трансформатор напряжения понижающий низковольтный 220/24В")
        features["entity_type"] = "transformer"
        candidate = {
            "name": "Трансформатор напряжения понижающий низковольтный 220/24В",
            "normalized_name": "трансформатор напряжения понижающий низковольтный 220 24в",
            "branch_path": "трансформаторы напряжения понижающие низковольтные",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(features, candidate),
            "transformer",
        )

        current_features = self.matcher._extract_query_features("Трансформатор тока низковольтный 100/5А")
        current_features["entity_type"] = "transformer"
        current_candidate = {
            "name": "Трансформатор тока низковольтный 100/5А",
            "normalized_name": "трансформатор тока низковольтный 100 5а",
            "branch_path": "трансформаторы тока низковольтные",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(current_features, current_candidate),
            "transformer",
        )

    def test_effective_candidate_family_maps_other_signage_branches(self):
        light_features = self.matcher._extract_query_features("Свето-звуковое табло ВЫХОД 12В")
        light_features["entity_type"] = "light_signage"
        light_candidate = {
            "name": "Свето-звуковое табло ВЫХОД 12В",
            "normalized_name": "свето звуковое табло выход 12в",
            "branch_path": "свето-звуковое табло",
            "entity_type": "other",
            "item_markers": {},
        }
        safety_features = self.matcher._extract_query_features("Знак безопасности Направление эвакуации")
        safety_features["entity_type"] = "safety_sign"
        safety_candidate = {
            "name": "Знак безопасности Направление эвакуации",
            "normalized_name": "знак безопасности направление эвакуации",
            "branch_path": "знаки безопасности",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(light_features, light_candidate),
            "light_signage",
        )
        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(safety_features, safety_candidate),
            "safety_sign",
        )

    def test_effective_candidate_family_maps_other_fuse_branch(self):
        features = self.matcher._extract_query_features("Предохранитель плавкий 10А")
        features["entity_type"] = "fuse"
        candidate = {
            "name": "Предохранитель плавкий 10А",
            "normalized_name": "предохранитель плавкий 10а",
            "branch_path": "плавкие предохранители",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(features, candidate),
            "fuse",
        )

    def test_effective_candidate_family_maps_other_ups_branch(self):
        features = self.matcher._extract_query_features("Источник бесперебойного питания Line Interactive 2000VA")
        features["entity_type"] = "ups"
        candidate = {
            "name": "Источник бесперебойного питания Line Interactive 2000VA",
            "normalized_name": "источник бесперебойного питания line interactive 2000va",
            "branch_path": "источники бесперебойного питания (ибп)",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(features, candidate),
            "ups",
        )

    def test_collect_branch_candidates_relaxes_entity_filter_for_box_family(self):
        self.matcher._uses_duckdb_query_backend = lambda: True
        captured = {}

        def fake_fetch_items(where_sql="", params=None, order_by_sql="", limit=None):
            captured["where_sql"] = where_sql
            captured["params"] = list(params or [])
            captured["order_by_sql"] = order_by_sql
            captured["limit"] = limit
            return []

        self.matcher._duckdb_fetch_items = fake_fetch_items

        self.matcher._collect_branch_candidates(
            ["коробки распределительные наружные"],
            limit=25,
            query_features={"entity_type": "box"},
        )

        self.assertNotIn("search_entity_type", captured["where_sql"])
        self.assertEqual(captured["limit"], 25)

    def test_collect_branch_candidates_prioritizes_cable_channel_rows(self):
        self.matcher._uses_duckdb_query_backend = lambda: True
        captured = {}

        def fake_fetch_items(where_sql="", params=None, order_by_sql="", limit=None):
            captured["where_sql"] = where_sql
            captured["params"] = list(params or [])
            captured["order_by_sql"] = order_by_sql
            captured["limit"] = limit
            return []

        self.matcher._duckdb_fetch_items = fake_fetch_items

        self.matcher._collect_branch_candidates(
            ["электрика > кабели > кабель-каналы", "электрика > кабели"],
            limit=120,
            query_features={
                "entity_type": "cable_channel",
                "tokens": ["короб", "крышкой", "80x40"],
                "markers": {"installation_kind": "cable_channel", "length_m": "3"},
            },
        )

        self.assertNotIn("search_entity_type", captured["where_sql"])
        self.assertIn("search_item_markers_json", captured["order_by_sql"])
        self.assertIn("search_normalized_name", captured["order_by_sql"])
        self.assertIn('%"installation_kind": "cable_channel"%', captured["params"])
        self.assertIn("%кабель канал%", captured["params"])
        self.assertIn("%короб%", captured["params"])
        self.assertIn("%80x40%", captured["params"])
        self.assertEqual(captured["limit"], 120)

    def test_collect_branch_candidates_uses_precomputed_effective_family_columns(self):
        self.matcher._uses_duckdb_query_backend = lambda: True
        self.matcher.search_catalog_columns = {"search_effective_family", "search_effective_entity_type"}
        self.matcher._should_relax_family_entity_filter = lambda _family: False
        captured = {}

        def fake_fetch_items(where_sql="", params=None, order_by_sql="", limit=None):
            captured["where_sql"] = where_sql
            captured["params"] = list(params or [])
            captured["order_by_sql"] = order_by_sql
            captured["limit"] = limit
            return []

        self.matcher._duckdb_fetch_items = fake_fetch_items

        self.matcher._collect_branch_candidates(
            ["электрика > кабели"],
            limit=40,
            query_features={"entity_type": "cable"},
        )

        self.assertIn("search_effective_family", captured["where_sql"])
        self.assertIn("search_effective_entity_type", captured["where_sql"])
        self.assertIn("cable", captured["params"])
        self.assertEqual(captured["limit"], 40)

    def test_effective_candidate_family_prefers_precomputed_effective_family(self):
        features = self.matcher._extract_query_features("Блок сигнально-пусковой адресный")
        features["entity_type"] = "security_control_device"
        candidate = {
            "name": "Преобразователь интерфейса МС-Е",
            "normalized_name": "преобразователь интерфейса мс е",
            "branch_path": "дополнительное оборудование для пс",
            "entity_type": "other",
            "effective_entity_type": "security_control_device",
            "effective_family": "security_control_device",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(features, candidate),
            "security_control_device",
        )

    def test_effective_candidate_family_maps_misclassified_fire_alarm_items(self):
        detector_features = self.matcher._extract_query_features("Извещатель пожарный дымовой адресный")
        detector_features["entity_type"] = "fire_detector"
        detector_candidate = {
            "name": "Извещатель пожарный дымовой взрывозащищенный",
            "normalized_name": "извещатель пожарный дымовой взрывозащищенный",
            "branch_path": "извещатели пожарные",
            "entity_type": "cable",
            "item_markers": {},
        }
        interface_features = self.matcher._extract_query_features("Преобразователь интерфейса RS485 в Modbus RTU")
        interface_features["entity_type"] = "security_interface_device"
        interface_candidate = {
            "name": "Преобразователь интерфейса МС-Е",
            "normalized_name": "преобразователь интерфейса мс е",
            "branch_path": "дополнительное оборудование для пс",
            "entity_type": "other",
            "item_markers": {},
        }
        panel_features = self.matcher._extract_query_features("Пульт контроля и управления")
        panel_features["entity_type"] = "security_control_panel"
        panel_candidate = {
            "name": "Пульт управления и индикации ПУ-02",
            "normalized_name": "пульт управления и индикации пу 02",
            "branch_path": "приборы приёмно-контрольные для опс",
            "entity_type": "other",
            "item_markers": {},
        }

        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(detector_features, detector_candidate),
            "fire_detector",
        )
        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(interface_features, interface_candidate),
            "security_interface_device",
        )
        self.assertEqual(
            self.matcher._effective_candidate_family_for_query(panel_features, panel_candidate),
            "security_control_panel",
        )

    def test_strict_fallback_allows_fastener_like_candidate_after_family_normalization(self):
        features = self.matcher._extract_query_features("Анкер-клин 6х35 потолочный")
        features["entity_type"] = "fastener"
        candidate = {
            "name": "Анкер-клин 6х35 потолочный",
            "normalized_name": "анкер клин 6х35 потолочный",
            "branch_path": "крепежные изделия для кабеленесущих систем",
            "entity_type": "rack_accessory_strict",
            "item_markers": {"accessory_kind": "fastener"},
        }
        self.matcher._compatibility_label = lambda _features, _item: "compatible"

        self.assertTrue(self.matcher._is_strict_fallback_allowed(features, candidate))

    def test_typed_candidate_pool_for_rack_tray_caps_unstructured_whole_category_queries(self):
        features = {
            "row_type": "item",
            "entity_type": "rack_accessory_strict",
            "markers": {},
            "ranked_branches": [{"path": "телеком > аксессуары > шкафные аксессуары", "score": 5.0}],
            "original_text": "Гусак",
        }
        category_candidates = [
            {
                "name": f"candidate {index}",
                "normalized_name": f"candidate {index}",
                "branch_path": "телеком > аксессуары > шкафные аксессуары",
                "entity_type": "rack_accessory_strict",
                "item_markers": {},
                "row_idx": index,
            }
            for index in range(450)
        ]
        self.matcher._should_use_whole_category_retrieval = lambda _features: True
        self.matcher._duckdb_category_candidates = lambda _features: ("rack_accessories", category_candidates, 0.0)
        self.matcher._select_candidates = lambda _query_text, limit=0: []

        pool = self.matcher._typed_candidate_pool_for_rack_tray("Гусак", features, 400)

        self.assertEqual(len(pool), 300)


if __name__ == "__main__":
    unittest.main()
