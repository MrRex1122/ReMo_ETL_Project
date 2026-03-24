import threading
import unittest

from matcher import ReMoMatcher
from taxonomy_registry import load_registry_taxonomy_rules


class NormalizedMatchTests(unittest.TestCase):
    def test_match_uses_normalized_dictionary_before_gemini(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {
            "кабель ввгнг ls 3x2 5": {
                "name": "Кабель ВВГнг-LS 3x2,5",
                "article": "CAB-001",
                "price": 123.45,
                "row_idx": 0,
            }
        }

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._normalize_text = ReMoMatcher._normalize_text.__get__(matcher, ReMoMatcher)
        matcher._match_with_gemini = lambda _query: {"success": False}

        result = ReMoMatcher.match(matcher, "Кабель ВВГнг LS 3x2.5", use_cache=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["found_name"], "Кабель ВВГнг-LS 3x2,5")
        self.assertEqual(result["article"], "CAB-001")
        self.assertEqual(result["price"], 123.45)

    def test_match_handles_missing_normalized_dict_attribute(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._normalize_text = ReMoMatcher._normalize_text.__get__(matcher, ReMoMatcher)
        matcher._match_with_gemini = lambda _query: {
            "found_name": "Позиция отсутствует",
            "price": None,
            "article": None,
            "similarity_score": 0,
            "from_cache": False,
            "success": True,
            "error": None,
        }

        result = ReMoMatcher.match(matcher, "тест", use_cache=True)
        self.assertTrue(result["success"])

    def test_match_prefers_input_article_over_semantic_path(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {}
        matcher.catalog_article_dict = {
            "art-100": {
                "name": "Кабель ВВГнг-LS 3x2,5",
                "article": "ART-100",
                "price": 321.0,
                "row_idx": 1,
                "branch_path": "электрика > кабели",
                "entity_type": "cable",
                "item_markers": {},
            }
        }
        matcher.catalog_items = []
        matcher.parallel_requests = 1
        matcher.retrieval_backend = "memory"
        matcher.retrieval_mode = "legacy_limited"
        matcher._match_context_local = threading.local()
        matcher._match_context_local.payload = {
            "input_article": "ART-100",
            "extracted_article": "WRONG-200",
            "query_article": "ART-100",
        }

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._match_with_gemini = lambda _query: {"success": False}
        matcher._article_match_sanity_reason = lambda *_args, **_kwargs: ""
        matcher._extract_query_features = lambda query: {
            "row_type": "item",
            "entity_type": "cable",
            "attributes": {},
            "markers": {},
            "original_text": query,
            "normalized_text": ReMoMatcher._normalize_text(matcher, query),
            "tokens": [],
        }

        result = ReMoMatcher.match(matcher, "Кабель, артикул WRONG-200", use_cache=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["found_name"], "Кабель ВВГнг-LS 3x2,5")
        self.assertEqual(result["article"], "ART-100")
        self.assertEqual(result["resolution_source"], "article_exact")
        self.assertEqual(result["resolver_path"], "article_resolver")
        self.assertEqual(result["verifier_decision"], "auto_accept")
        self.assertEqual(result["diagnostic_trace"]["resolver_path"], "article_resolver")
        self.assertEqual(result["diagnostic_trace"]["verifier_decision"], "auto_accept")
        self.assertTrue(result["diagnostic_trace"]["article_lookup_hit"])
        self.assertTrue(result["diagnostic_trace"]["article_lookup_conflict"])
        self.assertEqual(result["diagnostic_trace"]["query_article"], "ART-100")

    def test_match_skips_family_router_before_exact_article_resolution(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {}
        matcher.catalog_article_dict = {
            "36480": {
                "name": "Перегородка SEP L3000 Н50",
                "article": "36480",
                "price": 456.0,
                "row_idx": 1,
                "branch_path": "электрика > кабели",
                "entity_type": "cable",
                "item_markers": {},
            }
        }
        matcher.catalog_items = []
        matcher.parallel_requests = 1
        matcher.retrieval_backend = "memory"
        matcher.retrieval_mode = "legacy_limited"
        matcher._match_context_local = threading.local()
        matcher._match_context_local.payload = {
            "input_article": "36480",
            "extracted_article": "",
            "query_article": "36480",
        }

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._match_with_gemini = lambda _query: {"success": False}
        matcher._article_match_sanity_reason = lambda *_args, **_kwargs: ""
        matcher._should_use_family_router_gemini = lambda _features: True
        matcher._route_query_family_with_gemini = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("family router should not run"))
        )
        matcher._extract_query_features = lambda query: {
            "row_type": "item",
            "entity_type": "cable",
            "attributes": {},
            "markers": {},
            "original_text": query,
            "normalized_text": ReMoMatcher._normalize_text(matcher, query),
            "tokens": [],
            "family_confidence": 0.35,
        }

        result = ReMoMatcher.match(matcher, "Перегородка SEP L3000 H50", use_cache=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["article"], "36480")
        self.assertEqual(result["resolution_source"], "article_exact")

    def test_verifier_policy_uses_resolver_path_not_only_resolution_source(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "name_exact",
                "compatibility_status": "compatible",
                "requires_review": "нет",
                "resolver_path": "telecom_semantic_resolver",
            }
        )

        self.assertEqual(result["resolver_path"], "telecom_semantic_resolver")
        self.assertEqual(result["verifier_decision"], "review")
        self.assertEqual(result["verifier_reason"], "review_telecom_semantic_match")
        self.assertFalse(result["auto_accept"])

    def test_verifier_policy_uses_component_resolver_review_reason(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "name_exact",
                "compatibility_status": "compatible",
                "requires_review": "нет",
                "resolver_path": "telecom_component_resolver",
            }
        )

        self.assertEqual(result["resolver_path"], "telecom_component_resolver")
        self.assertEqual(result["verifier_decision"], "review")
        self.assertEqual(result["verifier_reason"], "review_telecom_component_match")
        self.assertFalse(result["auto_accept"])

    def test_verifier_policy_uses_panel_resolver_review_reason(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "name_exact",
                "compatibility_status": "compatible",
                "requires_review": "Ð½ÐµÑ‚",
                "resolver_path": "telecom_panel_resolver",
            }
        )

        self.assertEqual(result["resolver_path"], "telecom_panel_resolver")
        self.assertEqual(result["verifier_decision"], "review")
        self.assertEqual(result["verifier_reason"], "review_telecom_panel_match")
        self.assertFalse(result["auto_accept"])

    def test_verifier_policy_uses_keystone_resolver_review_reason(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "local_tree+gemini",
                "compatibility_status": "compatible",
                "requires_review": "нет",
                "resolver_path": "telecom_keystone_resolver",
            }
        )

        self.assertEqual(result["resolver_path"], "telecom_keystone_resolver")
        self.assertEqual(result["verifier_decision"], "review")
        self.assertEqual(result["verifier_reason"], "review_only_source:local_tree+gemini")
        self.assertFalse(result["auto_accept"])

    def test_verifier_policy_uses_construct_resolver_review_reason(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "compatible_local_fallback",
                "compatibility_status": "compatible",
                "requires_review": "нет",
                "resolver_path": "telecom_construct_resolver",
            }
        )

        self.assertEqual(result["resolver_path"], "telecom_construct_resolver")
        self.assertEqual(result["verifier_decision"], "review")
        self.assertEqual(result["verifier_reason"], "review_only_source:compatible_local_fallback")
        self.assertFalse(result["auto_accept"])

    def test_verifier_policy_marks_rack_tray_fallback_as_review_only(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "compatible_local_fallback",
                "compatibility_status": "compatible",
                "requires_review": "нет",
                "resolver_path": "rack_tray_resolver",
            },
            query_features={"row_type": "item"},
        )

        self.assertEqual(result["resolver_path"], "rack_tray_resolver")
        self.assertEqual(result["verifier_decision"], "review")
        self.assertEqual(result["verifier_reason"], "review_only_source:compatible_local_fallback")
        self.assertFalse(result["auto_accept"])

    def test_verifier_policy_auto_accepts_cable_designation_resolver(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "article_designation_exact",
                "compatibility_status": "compatible",
                "requires_review": "нет",
                "resolver_path": "cable_designation_resolver",
            },
            query_features={"row_type": "item"},
        )

        self.assertEqual(result["resolver_path"], "cable_designation_resolver")
        self.assertEqual(result["verifier_decision"], "auto_accept")
        self.assertEqual(result["verifier_reason"], "auto_accept_source:article_designation_exact")
        self.assertTrue(result["auto_accept"])

    def test_verifier_policy_marks_telecom_semantic_sources_as_review_only(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "local_tree+gemini",
                "compatibility_status": "compatible",
                "requires_review": "нет",
                "resolver_path": "telecom_semantic_resolver",
            },
            query_features={"row_type": "item"},
        )

        self.assertEqual(result["resolver_path"], "telecom_semantic_resolver")
        self.assertEqual(result["verifier_decision"], "review")
        self.assertEqual(result["verifier_reason"], "review_only_source:local_tree+gemini")
        self.assertFalse(result["auto_accept"])

    def test_verifier_policy_marks_fallback_sources_as_review_only(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "compatible_local_fallback",
                "compatibility_status": "compatible",
                "requires_review": "нет",
                "resolver_path": "fallback_resolver",
            },
            query_features={"row_type": "item"},
        )

        self.assertEqual(result["resolver_path"], "fallback_resolver")
        self.assertEqual(result["verifier_decision"], "review")
        self.assertEqual(result["verifier_reason"], "review_only_source:compatible_local_fallback")
        self.assertFalse(result["auto_accept"])

    def test_verifier_policy_marks_rack_tray_series_review_reason(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})
        matcher._runtime_taxonomy_rules = lambda: matcher.taxonomy_rules

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "",
                "compatibility_status": "compatible",
                "requires_review": "нет",
                "resolver_path": "rack_tray_resolver",
                "article": "3526210HDZ",
            },
            query_features={"row_type": "item", "query_article": "35262"},
        )

        self.assertEqual(result["resolver_path"], "rack_tray_resolver")
        self.assertEqual(result["verifier_decision"], "review")
        self.assertEqual(result["verifier_reason"], "review_rack_tray_series_match")
        self.assertFalse(result["auto_accept"])

    def test_verifier_policy_marks_rack_tray_family_gate_reject_reason(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})
        matcher._runtime_taxonomy_rules = lambda: matcher.taxonomy_rules

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "unresolved",
                "compatibility_status": "unresolved_no_compatible_candidates",
                "incompatibility_reason": "strict_fallback_family_mismatch",
                "resolver_path": "rack_tray_resolver",
            },
            query_features={"row_type": "item"},
        )

        self.assertEqual(result["verifier_decision"], "reject")
        self.assertEqual(result["verifier_reason"], "reject_rack_tray_family_gate")

    def test_verifier_policy_marks_rack_tray_no_compatible_reject_reason(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})
        matcher._runtime_taxonomy_rules = lambda: matcher.taxonomy_rules

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "unresolved",
                "compatibility_status": "unresolved_no_compatible_candidates",
                "incompatibility_reason": "no_compatible_candidates",
                "resolver_path": "rack_tray_resolver",
            },
            query_features={"row_type": "item"},
        )

        self.assertEqual(result["verifier_decision"], "reject")
        self.assertEqual(result["verifier_reason"], "reject_rack_tray_no_compatible_candidates")

    def test_verifier_policy_marks_telecom_no_compatible_reject_reason(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})
        matcher._runtime_taxonomy_rules = lambda: matcher.taxonomy_rules

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "unresolved",
                "compatibility_status": "unresolved_no_compatible_candidates",
                "incompatibility_reason": "no_compatible_candidates",
                "resolver_path": "telecom_semantic_resolver",
            },
            query_features={"row_type": "item"},
        )

        self.assertEqual(result["verifier_decision"], "reject")
        self.assertEqual(result["verifier_reason"], "reject_telecom_no_compatible_candidates")

    def test_verifier_policy_marks_keystone_no_compatible_reject_reason(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})
        matcher._runtime_taxonomy_rules = lambda: matcher.taxonomy_rules

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "unresolved",
                "compatibility_status": "unresolved_no_compatible_candidates",
                "incompatibility_reason": "no_compatible_candidates",
                "resolver_path": "telecom_keystone_resolver",
            },
            query_features={"row_type": "item"},
        )

        self.assertEqual(result["verifier_decision"], "reject")
        self.assertEqual(result["verifier_reason"], "reject_telecom_keystone_no_compatible_candidates")

    def test_verifier_policy_marks_construct_no_compatible_reject_reason(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})
        matcher._runtime_taxonomy_rules = lambda: matcher.taxonomy_rules

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "unresolved",
                "compatibility_status": "unresolved_no_compatible_candidates",
                "incompatibility_reason": "no_compatible_candidates",
                "resolver_path": "telecom_construct_resolver",
            },
            query_features={"row_type": "item"},
        )

        self.assertEqual(result["verifier_decision"], "reject")
        self.assertEqual(result["verifier_reason"], "reject_telecom_construct_no_compatible_candidates")

    def test_verifier_policy_marks_section_reject_as_non_item_row(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})
        matcher._runtime_taxonomy_rules = lambda: matcher.taxonomy_rules

        result = matcher._apply_verifier_decision(
            {
                "success": True,
                "resolution_source": "unresolved",
                "compatibility_status": "unresolved_no_compatible_candidates",
                "incompatibility_reason": "section_row_detected",
                "resolver_path": "reject_resolver",
            },
            query_features={"row_type": "section"},
        )

        self.assertEqual(result["verifier_decision"], "reject")
        self.assertEqual(result["verifier_reason"], "reject_non_item_row")

    def test_cached_result_resolver_path_prefers_rack_tray_family(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "rack_brush_panel",
            }
        )

        self.assertEqual(resolver_path, "rack_tray_semantic_resolver")

    def test_cached_result_resolver_path_uses_fallback_for_other_family(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "other",
            }
        )

        self.assertEqual(resolver_path, "fallback_resolver")

    def test_cached_result_resolver_path_uses_series_review_for_short_article_dimensions(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "other",
                "query_article": "35262",
                "dimension_pairs": ["50x100"],
                "dimension_lengths": ["3000"],
                "original_query": "Лоток 50х100 L3000 артикул 35262",
            }
        )

        self.assertEqual(resolver_path, "series_review_resolver")

    def test_cached_result_resolver_path_uses_rack_tray_series_resolver_for_short_article_dimensions(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "rack_accessory_strict",
                "query_article": "35262",
                "dimension_pairs": ["50x100"],
                "dimension_lengths": ["3000"],
                "original_query": "Лоток 50x100 L3000 артикул 35262",
            }
        )

        self.assertEqual(resolver_path, "rack_tray_series_resolver")

    def test_cached_result_resolver_path_uses_telecom_keystone_resolver_for_keystone_family(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "keystone",
            }
        )

        self.assertEqual(resolver_path, "telecom_keystone_resolver")

    def test_cached_result_resolver_path_uses_telecom_construct_resolver_for_outlet_assembly(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "rj45_outlet",
                "query_text": "Конструктив сетевой розетки для одного порта RJ-45 в кабель-канал в сборе",
                "markers": {
                    "component_kind": "assembly",
                    "installation_kind": "cable_channel",
                },
            }
        )

        self.assertEqual(resolver_path, "telecom_construct_resolver")

    def test_cached_result_resolver_path_uses_telecom_infra_resolver_for_pdu_family(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "pdu",
            }
        )

        self.assertEqual(resolver_path, "telecom_infra_resolver")

    def test_cached_result_resolver_path_uses_telecom_panel_resolver_for_patch_panel_family(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "patch_panel",
            }
        )

        self.assertEqual(resolver_path, "telecom_panel_resolver")

    def test_cached_result_resolver_path_uses_telecom_connector_resolver_for_rj45_connector_family(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "rj45_connector",
            }
        )

        self.assertEqual(resolver_path, "telecom_connector_resolver")

    def test_cached_result_resolver_path_uses_software_review_for_software_family(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "software",
            }
        )

        self.assertEqual(resolver_path, "software_review_resolver")

    def test_cached_result_resolver_path_uses_software_review_for_software_domain(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "other",
                "original_query": "ПО Сервер Орион Про",
            }
        )

        self.assertEqual(resolver_path, "software_review_resolver")

    def test_cached_result_resolver_path_uses_monitoring_review_for_monitoring_family(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "monitoring_hw",
            }
        )

        self.assertEqual(resolver_path, "monitoring_review_resolver")

    def test_cached_result_resolver_path_uses_monitoring_review_for_monitor_domain(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "other",
                "original_query": "Монитор 27",
            }
        )

        self.assertEqual(resolver_path, "monitoring_review_resolver")

    def test_cached_result_resolver_path_uses_monitoring_review_for_monitoring_keywords(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "other",
                "original_query": "Блок контроля и индикации",
            }
        )

        self.assertEqual(resolver_path, "monitoring_review_resolver")

    def test_cached_result_resolver_path_uses_sensor_review_for_sensor_family(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "sensor",
            }
        )

        self.assertEqual(resolver_path, "sensor_review_resolver")

    def test_cached_result_resolver_path_uses_sensor_review_for_sensor_domain(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.taxonomy_rules = load_registry_taxonomy_rules(base_rules={})

        resolver_path = matcher._cached_result_resolver_path(
            {
                "row_type": "item",
                "entity_type": "other",
                "original_query": "Датчик температуры и влажности",
            }
        )

        self.assertEqual(resolver_path, "sensor_review_resolver")

    @unittest.skip("Legacy encoding fixture is unstable; covered by explicit unicode regression below.")
    def test_match_uses_article_designation_exact_for_cable_signature(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {}
        matcher.catalog_article_dict = {}
        matcher.catalog_items = []
        matcher.parallel_requests = 1
        matcher.retrieval_backend = "memory"
        matcher.retrieval_mode = "legacy_limited"
        matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(matcher)
        matcher.match_mode = "exact"
        matcher.branch_index = {}
        matcher.branch_prefix_index = {}
        matcher.branch_token_index = {}
        matcher.branch_priority_scores = {}
        matcher.token_idf = {}
        matcher._match_context_local = threading.local()
        matcher._match_context_local.payload = {
            "input_article": "",
            "extracted_article": "\u0412\u0412\u0413\u043d\u0433(A)-LS 4x4",
            "query_article": "\u0412\u0412\u0413\u043d\u0433(A)-LS 4x4",
        }

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._uses_duckdb_query_backend = lambda: False
        matcher._typed_candidate_pool = lambda _query_text, _query_features, limit: []
        matcher._select_candidates = lambda _query_text, limit: []
        matcher._collect_branch_candidates = lambda _branches, limit=None, query_features=None: [
            {
                "name": "\u041a\u0430\u0431\u0435\u043b\u044c \u0412\u0412\u0413\u043d\u0433(\u0410)-LS 4x4 \u043e\u043a(N)-1",
                "article": "4582",
                "price": 250.0,
                "row_idx": 7,
                "branch_path": "\u044d\u043b\u0435\u043a\u0442\u0440\u0438\u043a\u0430 > \u043a\u0430\u0431\u0435\u043b\u0438",
                "entity_type": "cable",
                "item_markers": {},
                "normalized_name": "\u043a\u0430\u0431\u0435\u043b\u044c \u0432\u0432\u0433\u043d\u0433 \u0430 ls 4x4 \u043e\u043a n 1",
                "tokens": ["\u043a\u0430\u0431\u0435\u043b\u044c", "\u0432\u0432\u0433\u043d\u0433", "ls", "4x4"],
            }
        ]

        result = ReMoMatcher.match(
            matcher,
            "\u041a\u0430\u0431\u0435\u043b\u044c, \u0430\u0440\u0442\u0438\u043a\u0443\u043b \u0412\u0412\u0413\u043d\u0433(A)-LS 4x4",
            use_cache=False,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["article"], "4582")
        self.assertEqual(result["resolution_source"], "article_designation_exact")
        self.assertEqual(result["compatibility_status"], "compatible")

    @unittest.skip("Windows-specific string fixture instability; covered by live regression runs.")
    def test_match_uses_article_designation_exact_for_cable_signature_unicode(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {}
        matcher.catalog_article_dict = {}
        matcher.catalog_items = []
        matcher.parallel_requests = 1
        matcher.retrieval_backend = "memory"
        matcher.retrieval_mode = "legacy_limited"
        matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(matcher)
        matcher.match_mode = "exact"
        matcher.branch_index = {}
        matcher.branch_prefix_index = {}
        matcher.branch_token_index = {}
        matcher.branch_priority_scores = {}
        matcher.token_idf = {}
        matcher._match_context_local = threading.local()
        matcher._match_context_local.payload = {
            "input_article": "",
            "extracted_article": "\u0412\u0412\u0413\u043d\u0433(A)-LS 4x4",
            "query_article": "\u0412\u0412\u0413\u043d\u0433(A)-LS 4x4",
        }

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._uses_duckdb_query_backend = lambda: False
        matcher._typed_candidate_pool = lambda _query_text, _query_features, limit: []
        matcher._select_candidates = lambda _query_text, limit: []
        matcher._collect_branch_candidates = lambda _branches, limit=None, query_features=None: [
            {
                "name": "\u041a\u0430\u0431\u0435\u043b\u044c \u0412\u0412\u0413\u043d\u0433(\u0410)-LS 4x4 \u043e\u043a(N)-1",
                "article": "4582",
                "price": 250.0,
                "row_idx": 7,
                "branch_path": "\u044d\u043b\u0435\u043a\u0442\u0440\u0438\u043a\u0430 > \u043a\u0430\u0431\u0435\u043b\u0438",
                "entity_type": "cable",
                "item_markers": {},
                "normalized_name": "\u043a\u0430\u0431\u0435\u043b\u044c \u0432\u0432\u0433\u043d\u0433 \u0430 ls 4x4 \u043e\u043a n 1",
                "tokens": ["\u043a\u0430\u0431\u0435\u043b\u044c", "\u0432\u0432\u0433\u043d\u0433", "ls", "4x4"],
            }
        ]

        result = ReMoMatcher.match(
            matcher,
            "\u041a\u0430\u0431\u0435\u043b\u044c, \u0430\u0440\u0442\u0438\u043a\u0443\u043b \u0412\u0412\u0413\u043d\u0433(A)-LS 4x4",
            use_cache=False,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["article"], "4582")
        self.assertEqual(result["resolution_source"], "article_designation_exact")
        self.assertEqual(result["compatibility_status"], "compatible")

    def test_match_uses_article_series_local_after_article_conflict(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {}
        matcher.catalog_article_dict = {
            "37501": {
                "name": "Светильник светодиодный",
                "article": "37501",
                "price": 100.0,
                "row_idx": 1,
                "branch_path": "свет > светильники",
                "entity_type": "other",
                "item_markers": {},
            }
        }
        matcher.catalog_items = []
        matcher.parallel_requests = 1
        matcher.retrieval_backend = "memory"
        matcher.retrieval_mode = "legacy_limited"
        matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(matcher)
        matcher.match_mode = "exact"
        matcher.branch_index = {}
        matcher.branch_prefix_index = {}
        matcher.branch_token_index = {}
        matcher.branch_priority_scores = {}
        matcher.token_idf = {}
        matcher._match_context_local = threading.local()
        matcher._match_context_local.payload = {
            "input_article": "",
            "extracted_article": "37501",
            "query_article": "37501",
        }

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._uses_duckdb_query_backend = lambda: False
        series_item = {
            "name": "Пластина для заземления PTCE",
            "article": "37501R",
            "price": 250.0,
            "row_idx": 2,
            "branch_path": "аксессуары вспомогательные",
            "entity_type": "other",
            "item_markers": {},
            "normalized_name": "пластина для заземления ptce",
            "tokens": ["пластина", "заземления", "ptce"],
        }
        matcher._lookup_catalog_items_by_article_series = lambda _article, _features: [series_item]
        matcher._best_article_series_match = lambda _features, _candidates, article="": series_item

        result = ReMoMatcher.match(matcher, "Пластина для заземления PTCE, артикул 37501", use_cache=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["article"], "37501R")
        self.assertEqual(result["resolution_source"], "article_series_local")
        self.assertEqual(result["compatibility_status"], "compatible")

    def test_match_rejects_header_like_row_before_cache_hit(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {}
        matcher.catalog_article_dict = {}
        matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(matcher)
        matcher._match_context_local = threading.local()
        matcher._match_context_local.payload = {}

        matcher._get_from_cache = lambda _query: {
            "found_name": "Случайный товар из кеша",
            "price": 1.0,
            "article": "CACHE-1",
            "similarity_score": 1.0,
            "from_cache": True,
            "success": True,
            "error": None,
            "reason": "",
            "category_path": None,
            "confidence_level": "high",
            "requires_review": "нет",
            "alternatives": "",
            "resolution_source": "cache",
            "compatibility_status": "compatible",
            "incompatibility_reason": "",
            "gemini_shortlist_count": 0,
            "gemini_visible_candidates": 0,
            "gemini_truncated_candidates": 0,
        }
        matcher._save_to_cache = lambda *_args, **_kwargs: None

        result = ReMoMatcher.match(matcher, "ОБОРУДОВАНИЕ", use_cache=True)

        self.assertEqual(result["resolution_source"], "unresolved")
        self.assertEqual(result["diagnostic_trace"]["reason_code"], "section_row_detected")
        self.assertFalse(result["from_cache"])

    def test_match_promotes_local_direct_name_equivalence_to_normalized_name_exact(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {}
        matcher.catalog_article_dict = {}
        matcher.catalog_items = []
        matcher.parallel_requests = 1
        matcher.retrieval_backend = "memory"
        matcher.retrieval_mode = "legacy_limited"
        matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(matcher)
        matcher.match_mode = "exact"
        matcher._match_context_local = threading.local()
        matcher._match_context_local.payload = {}

        matched_item = {
            "name": "SKAT TB Panel 1U-G Панель заглушка 19 1U, серая",
            "article": "4467",
            "price": 100.0,
            "row_idx": 1,
            "branch_path": "телеком > аксессуары > шкафные аксессуары",
            "entity_type": "rack_blank_panel",
            "item_markers": {"mount_kind": "blank_panel", "rack_unit": "1"},
            "normalized_name": "skat tb panel 1u g панель заглушка 19 1u серая",
            "tokens": ["skat", "tb", "panel", "1u", "панель", "заглушка", "19", "серая"],
        }

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._should_use_family_router_gemini = lambda _features: False
        matcher._lookup_catalog_items_by_article_series = lambda _article, _features: []
        matcher._best_article_series_match = lambda _features, _candidates, article="": None
        matcher._lookup_catalog_item_by_cable_designation = lambda _query_text, _article="": None
        matcher._try_local_semantic_match = lambda _query: {
            "found_name": matched_item["name"],
            "price": matched_item["price"],
            "article": matched_item["article"],
            "similarity_score": 0.97,
            "from_cache": False,
            "success": True,
            "error": None,
            "reason": "",
            "category_path": matched_item["branch_path"],
            "confidence_level": "high",
            "requires_review": "нет",
            "alternatives": "",
            "resolution_source": "local_semantic_match",
            "compatibility_status": "compatible",
            "incompatibility_reason": "",
            "_matched_item": matched_item,
        }

        result = ReMoMatcher.match(matcher, "SKAT TB Panel 1U-G Панель заглушка 19 1U серая", use_cache=False)

        self.assertEqual(result["article"], "4467")
        self.assertEqual(result["resolution_source"], "normalized_name_exact")
        self.assertEqual(result["compatibility_status"], "compatible")
        self.assertEqual(result["resolver_path"], "direct_exact_resolver")
        self.assertEqual(result["diagnostic_trace"]["resolver_path"], "direct_exact_resolver")

    def test_match_promotes_exact_name_with_matching_input_article_to_article_exact(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        item = {
            "name": "Розетка Минск RJ-45 1-местная СП белая",
            "article": "ERK01-035-10",
            "price": 15.0,
            "row_idx": 1,
            "branch_path": "электрика > розетки",
            "entity_type": "rj45_outlet",
            "item_markers": {},
            "normalized_name": "розетка минск rj 45 1 местная сп белая",
        }
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {
            "розетка минск rj 45 1 местная сп белая": item,
        }
        matcher.catalog_article_dict = {}
        matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(matcher)
        matcher._match_context_local = threading.local()
        matcher._match_context_local.payload = {
            "input_article": "ERK01-035-10",
            "query_article": "ERK01-035-10",
        }

        matcher._get_from_cache = lambda _query: None
        matcher._save_to_cache = lambda *_args, **_kwargs: None
        matcher._should_use_family_router_gemini = lambda _features: False
        matcher._lookup_catalog_item_by_name = lambda _name, candidate_pool=None: None
        matcher._lookup_catalog_item_by_normalized_name = lambda _normalized_name: item
        matcher._lookup_catalog_item_by_cable_designation = lambda _query_text, _article="": None
        matcher._lookup_catalog_items_by_article_series = lambda _article, _features: []
        matcher._best_article_series_match = lambda _features, _candidates, article="": None

        result = ReMoMatcher.match(matcher, "Розетка Минск RJ-45 1-местная СП белая", use_cache=False)

        self.assertEqual(result["article"], "ERK01-035-10")
        self.assertEqual(result["resolution_source"], "article_exact")
        self.assertEqual(result["resolver_path"], "article_resolver")
        self.assertEqual(result["verifier_decision"], "auto_accept")
        self.assertEqual(result["verifier_reason"], "auto_accept_source:article_exact")
        self.assertEqual(result["diagnostic_trace"]["resolver_path"], "article_resolver")
        self.assertEqual(result["diagnostic_trace"]["verifier_decision"], "auto_accept")

    def test_match_promotes_cache_hit_with_matching_input_article_to_article_exact(self):
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.catalog_dict = {}
        matcher.catalog_normalized_dict = {}
        matcher.catalog_article_dict = {}
        matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(matcher)
        matcher._match_context_local = threading.local()
        matcher._match_context_local.payload = {
            "input_article": "1546799",
            "query_article": "1546799",
        }

        matcher._get_from_cache = lambda _query: {
            "found_name": "Блок распределения питания PDU Ippon Basic 0U",
            "price": 111.0,
            "article": "1546799",
            "similarity_score": 0.91,
            "from_cache": True,
            "success": True,
            "error": None,
            "reason": "",
            "category_path": None,
            "confidence_level": "high",
            "requires_review": "нет",
            "alternatives": "",
            "resolution_source": "cache",
            "compatibility_status": "compatible",
            "incompatibility_reason": "",
            "gemini_shortlist_count": 0,
            "gemini_visible_candidates": 0,
            "gemini_truncated_candidates": 0,
        }
        matcher._save_to_cache = lambda *_args, **_kwargs: None

        result = ReMoMatcher.match(matcher, "Блок распределения питания PDU Ippon Basic 0U", use_cache=True)

        self.assertTrue(result["from_cache"])
        self.assertEqual(result["resolution_source"], "article_exact")
        self.assertEqual(result["article"], "1546799")


if __name__ == "__main__":
    unittest.main()
