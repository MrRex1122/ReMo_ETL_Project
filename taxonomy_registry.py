from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

DEFAULT_TAXONOMY_RULES_PATH = Path(__file__).with_name("taxonomy_rules.json")

DEFAULT_FAMILY_REGISTRY: Dict[str, Dict[str, Any]] = {
    "airflow_blanking_panel": {
        "entity_types": ["airflow_blanking_panel"],
        "default_branches": ["телеком > аксессуары > шкафные аксессуары > заглушки"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "same_family_gate": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 90,
            "positive_patterns": ["заглуш"],
            "required_any_tokens": [["поток", "воздуха"], ["airflow", "blanking"]],
        },
    },
    "ats_sts": {
        "entity_types": ["ats_sts"],
        "default_branches": ["телеком > питание > ats"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "same_family_gate": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 95,
            "positive_patterns": ["ats", "sts", "статическ"],
            "required_any_tokens": [["переключател"], ["transfer", "switch"]],
        },
    },
    "breaker": {
        "entity_types": ["breaker"],
        "default_branches": ["электрика > автоматы"],
        "retrieval_mode": "branch_limited",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
    },
    "bulk_twisted_pair": {
        "entity_types": ["bulk_twisted_pair"],
        "default_branches": ["телеком > кабели > витая пара"],
        "retrieval_mode": "whole_category",
        "strictness": "semi_strict",
        "strictness_overrides": [
            {
                "when_any_markers": ["category", "shielding", "cable_environment"],
                "value": "strict",
            }
        ],
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 70,
            "positive_patterns": ["витая пара", "utp", "ftp", "s/ftp", "f/utp", "u/utp"],
            "negative_patterns": ["патч корд", "patch cord"],
        },
        "secondary_filter_rules": [
            {
                "name": "bulk_category_required",
                "type": "require_marker_equal",
                "marker": "category",
                "candidate_marker": "category",
                "fallback_patterns": {
                    "cat5e": ["cat5e"],
                    "cat6": ["cat6"],
                    "cat6a": ["cat6a"],
                },
            },
            {
                "name": "bulk_shielding_required",
                "type": "require_marker_equal",
                "marker": "shielding",
                "candidate_marker": "shielding",
                "fallback_patterns": {
                    "utp": ["u/utp", "u utp", "utp", "неэкранир"],
                    "ftp": ["f/utp", "f utp", "ftp"],
                    "sftp": ["s/ftp", "sftp", "sf/utp", "f/ftp"],
                    "shielded": ["s/ftp", "sftp", "sf/utp", "f/ftp", "f/utp", "f utp", "ftp", "экранир"],
                },
            },
            {
                "name": "bulk_environment_outdoor",
                "type": "require_marker_equal",
                "when_marker_equals": {"cable_environment": "outdoor"},
                "marker": "cable_environment",
                "candidate_marker": "cable_environment",
                "fallback_patterns": {
                    "outdoor": ["outdoor", "внешн", "наружн", "улич"],
                },
            },
            {
                "name": "bulk_lszh_preferred",
                "type": "prefer_any_tokens",
                "when_query_contains_any": ["lszh"],
                "tokens": ["lszh"],
            },
            {
                "name": "bulk_designation_family_required",
                "type": "require_marker_equal",
                "marker": "designation_family",
                "candidate_marker": "designation_family",
            },
        ],
    },
    "cable": {
        "entity_types": ["cable"],
        "default_branches": ["электрика > кабели"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
    },
    "coax": {
        "entity_types": ["coax"],
        "default_branches": ["электрика > кабели"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
    },
    "floor_box": {
        "entity_types": ["floor_box"],
        "default_branches": ["телеком > аксессуары > лючки"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "same_family_gate": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 60,
            "positive_patterns": ["лючок", "напольн"],
            "required_any_tokens": [["короб"], ["box"]],
        },
    },
    "ground_bar": {
        "entity_types": ["ground_bar"],
        "default_branches": ["телеком > аксессуары > заземление"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "same_family_gate": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 60,
            "positive_patterns": ["заземл", "шин"],
            "required_any_tokens": [["заземл"], ["шин"]],
        },
    },
    "iec_power_cable": {
        "entity_types": ["iec_power_cable"],
        "default_branches": ["электрика > кабели"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 84,
            "positive_patterns": ["iec", "c13", "c14", "c19", "c20"],
            "negative_patterns": ["pdu", "блок розеток"],
            "required_any_tokens": [["кабель", "шнур", "cord"]],
        },
    },
    "keystone": {
        "entity_types": ["keystone_module", "keystone_adapter", "rj45_outlet"],
        "default_branches": ["телеком > коммутация > модули"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "allowed_cross_family_pairs": ["rj45_outlet"],
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 65,
            "positive_patterns": ["keystone", "кейстоун"],
        },
        "secondary_filter_rules": [
            {
                "name": "keystone_component_kind_preferred",
                "type": "prefer_marker_equal",
                "marker": "component_kind",
                "candidate_marker": "component_kind",
            },
            {
                "name": "keystone_category_preferred",
                "type": "prefer_marker_equal",
                "marker": "category",
                "candidate_marker": "category",
            },
        ],
    },
    "optical_cross": {
        "entity_types": ["optical_cross"],
        "default_branches": ["телеком > оптика > кроссы"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 80,
            "positive_patterns": ["оптическ", "кросс"],
        },
    },
    "optical_patch_cord": {
        "entity_types": ["optical_patch_cord"],
        "default_branches": ["телеком > кабели > оптические патч корды"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 85,
            "positive_patterns": ["оптическ", "патч корд", "patch cord"],
            "required_any_tokens": [
                ["оптическ", "волокон", "fiber"],
                ["lc", "sc", "fc", "st", "mtp", "mpo", "duplex", "simplex", "os2", "om3", "om4"],
            ],
        },
    },
    "patch_cord": {
        "entity_types": ["patch_cord"],
        "default_branches": ["телеком > кабели > патч корды"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 85,
            "positive_patterns": ["патч корд", "patch cord", "коммутационный шнур"],
            "negative_patterns": ["оптическ"],
            "required_any_tokens": [["rj45", "rj 45", "8p8c", "ethernet", "lan", "utp", "ftp", "sftp", "cat", "категор"]],
        },
    },
    "patch_panel": {
        "entity_types": ["patch_panel"],
        "default_branches": ["телеком > коммутация > патч панели"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 85,
            "positive_patterns": ["патч панел", "патч-панел", "patch panel"],
        },
    },
    "pdu": {
        "entity_types": ["pdu_basic", "pdu_metered"],
        "default_branches": ["телеком > питание > pdu"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 80,
            "positive_patterns": ["pdu", "блок розеток"],
            "negative_patterns": ["кабель", "шнур", "cord", "iec", "c13", "c14", "c19", "c20"],
        },
    },
    "rack": {
        "entity_types": ["rack"],
        "default_branches": ["телеком > шкафы"],
        "retrieval_mode": "whole_category",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "allow",
        "classifier": {
            "priority": 50,
            "positive_patterns": ["шкаф", "стойк"],
        },
        "secondary_filter_rules": [
            {
                "name": "rack_organizer_required",
                "type": "require_any_token_group",
                "when_query_contains_any": ["органайз"],
                "groups": [["органайз"]],
            }
        ],
    },
    "rack_accessory_strict": {
        "entity_types": ["rack_blank_panel", "rack_brush_panel", "rack_shelf", "rack_rail"],
        "default_branches": ["телеком > аксессуары > шкафные аксессуары"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 65,
            "positive_patterns": [
                "крышк",
                "пластин",
                "угол",
                "ответвител",
                "консол",
                "профил",
                "держател",
                "анкер",
                "крепеж",
                "хомут",
            ],
            "negative_patterns": ["полк", "щеточ", "заглуш", "rail", "рельс"],
            "required_markers": {
                "accessory_kind": [
                    "cover",
                    "connector_plate",
                    "grounding_plate",
                    "plate",
                    "corner",
                    "tee",
                    "console",
                    "profile",
                    "holder",
                    "fastener",
                ]
            },
            "returns": "rack_accessory_strict",
        },
        "secondary_filter_rules": [
            {
                "name": "rack_accessory_kind_required",
                "type": "require_marker_equal",
                "marker": "accessory_kind",
                "candidate_marker": "accessory_kind",
                "fallback_patterns": {
                    "cover": ["крышк", "cover"],
                    "connector_plate": ["соединител", "пластин"],
                    "grounding_plate": ["заземл", "пластин"],
                    "plate": ["пластин"],
                    "corner": ["угол", "corner"],
                    "tee": ["ответвител", "tee"],
                    "console": ["консол", "console"],
                    "profile": ["профил", "profile"],
                    "holder": ["держател", "хомут", "holder"],
                    "fastener": ["анкер", "крепеж", "fastener"],
                },
            },
            {
                "name": "rack_accessory_orientation_preferred",
                "type": "prefer_marker_equal",
                "marker": "orientation_kind",
                "candidate_marker": "orientation_kind",
            },
            {
                "name": "rack_accessory_position_preferred",
                "type": "prefer_marker_equal",
                "marker": "position_kind",
                "candidate_marker": "position_kind",
            },
            {
                "name": "rack_accessory_dimensions_preferred",
                "type": "prefer_dimension_overlap",
            },
            {
                "name": "rack_mount_kind_required",
                "type": "require_marker_equal",
                "marker": "mount_kind",
                "candidate_marker": "mount_kind",
                "fallback_patterns": {
                    "brush_panel": ["щеточ"],
                    "blank_panel": ["заглуш", "blanking", "blank panel"],
                    "shelf": ["полк", "shelf"],
                    "rail": ["рельс", "rail", "направля"],
                },
            },
            {
                "name": "rack_unit_preferred",
                "type": "prefer_marker_equal",
                "marker": "rack_unit",
                "candidate_marker": "rack_unit",
            },
            {
                "name": "rack_brush_entry_required",
                "type": "require_any_token_group",
                "when_marker_equals": {"mount_kind": "brush_panel"},
                "when_query_contains_any": ["ввод"],
                "groups": [["ввод", "ввода", "cable entry", "entry panel"]],
            },
            {
                "name": "rack_brush_cable_required",
                "type": "require_any_token_group",
                "when_marker_equals": {"mount_kind": "brush_panel"},
                "when_query_contains_any": ["кабел"],
                "groups": [["кабел", "cable"]],
            },
            {
                "name": "rack_blank_panel_preferred",
                "type": "prefer_any_token_group",
                "when_marker_equals": {"mount_kind": "blank_panel"},
                "when_query_contains_any": ["свободн", "юнит"],
                "groups": [["свободн", "юнит", "blanking", "blank panel"]],
            },
        ],
    },
    "rack_rail": {
        "entity_types": ["rack_rail", "rack_shelf"],
        "default_branches": ["телеком > аксессуары > шкафные аксессуары"],
        "retrieval_mode": "whole_category",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
    },
    "rack_shelf": {
        "entity_types": ["rack_shelf", "rack_rail"],
        "default_branches": ["телеком > аксессуары > шкафные аксессуары"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
    },
    "rj45_connector": {
        "entity_types": ["rj45_connector"],
        "default_branches": ["телеком > коммутация > модули", "электрика > кабели"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 70,
            "positive_patterns": ["коннектор", "rj45", "rj-45"],
            "negative_patterns": ["розетк", "адаптер", "лицевая панель"],
        },
        "secondary_filter_rules": [
            {
                "name": "rj45_connector_component_kind",
                "type": "prefer_marker_equal",
                "marker": "component_kind",
                "candidate_marker": "component_kind",
            }
        ],
    },
    "rj45_outlet": {
        "entity_types": ["rj45_outlet", "keystone_module", "keystone_adapter"],
        "default_branches": ["телеком > коммутация > модули"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "allowed_cross_family_pairs": ["keystone"],
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 70,
            "positive_patterns": ["розетк", "rj45", "rj-45"],
        },
        "secondary_filter_rules": [
            {
                "name": "rj45_outlet_component_kind",
                "type": "prefer_marker_equal",
                "marker": "component_kind",
                "candidate_marker": "component_kind",
            },
            {
                "name": "rj45_outlet_installation_kind",
                "type": "prefer_marker_equal",
                "marker": "installation_kind",
                "candidate_marker": "installation_kind",
            },
        ],
    },
    "sensor": {
        "entity_types": ["sensor", "temperature_sensor", "temperature_humidity_sensor", "reed_sensor"],
        "default_branches": ["автоматика > датчики"],
        "retrieval_mode": "whole_category",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 60,
            "positive_patterns": ["датчик"],
        },
        "secondary_filter_rules": [
            {
                "name": "sensor_temperature_humidity_required",
                "type": "require_any_token_group",
                "when_marker_equals": {"sensor_kind": "temperature_humidity"},
                "groups": [["датчик"], ["температур", "влажност"]],
            },
            {
                "name": "sensor_temperature_required",
                "type": "require_any_token_group",
                "when_marker_equals": {"sensor_kind": "temperature"},
                "groups": [["датчик"], ["температур"]],
            },
        ],
    },
    "socket": {
        "entity_types": ["socket"],
        "default_branches": ["электрика > розетки"],
        "retrieval_mode": "branch_limited",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
    },
    "soft_starter": {
        "entity_types": ["soft_starter"],
        "default_branches": ["электрика > приводы"],
        "retrieval_mode": "branch_limited",
        "strictness": "strict",
        "audited": False,
        "weak_match_policy": "reject_in_exact",
    },
    "wire": {
        "entity_types": ["wire"],
        "default_branches": ["электрика > провода"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
    },
}

DEFAULT_DOMAIN_REGISTRY: Dict[str, Any] = {
    "domains": {
        "tray": {
            "patterns": ["лоток", "крышк", "перегород", "пластин", "ответвител", "угол", "gto", "ptce", "sep"],
            "families": [],
        },
        "lighting": {
            "patterns": ["светильник", "светодиод", "треков", "дсо", "дсп", "дпо", "дку"],
            "families": [],
        },
        "software": {
            "patterns": ["программ", "лиценз", "software", "monitoring"],
            "families": [],
        },
        "monitoring_hw": {
            "patterns": ["камер", "видеокамер", "извещат", "датчик", "шкаф"],
            "families": ["sensor", "rack"],
        },
        "monitor_display": {
            "patterns": ["монитор", "display"],
            "families": [],
        },
        "rolling_hardware": {
            "patterns": ["колес", "ролик"],
            "families": [],
        },
        "fastener": {
            "patterns": ["держател", "хомут", "скоб"],
            "families": [],
        },
        "electrical_protection": {
            "patterns": ["выключател", "автоматическ", "автомат", "optidin", "bm63"],
            "families": ["breaker"],
        },
        "grounding": {
            "patterns": ["заземл", "шина", "стержень"],
            "families": ["ground_bar"],
        },
        "rack_accessory": {
            "patterns": ["полк", "рельс", "направля", "щеточ", "заглуш"],
            "families": ["rack_accessory_strict", "rack_shelf", "rack_rail"],
        },
        "cable": {
            "patterns": ["кабель", "провод", "ввг", "кгв", "кипэ", "сгпм"],
            "families": ["cable", "wire", "coax", "bulk_twisted_pair", "iec_power_cable"],
        },
    },
    "conflicts": [
        {
            "query_domains": ["tray"],
            "candidate_domains": ["lighting", "electrical_protection"],
            "reason_code": "article_query_candidate_domain_mismatch",
        },
        {
            "query_domains": ["lighting"],
            "candidate_domains": ["tray"],
            "reason_code": "article_query_candidate_domain_mismatch",
        },
        {
            "query_domains": ["software"],
            "candidate_domains": ["monitoring_hw", "lighting", "cable"],
            "reason_code": "article_query_candidate_domain_mismatch",
        },
        {
            "query_domains": ["monitor_display"],
            "candidate_domains": ["monitoring_hw", "rolling_hardware", "cable"],
            "reason_code": "article_query_candidate_domain_mismatch",
        },
        {
            "query_domains": ["fastener"],
            "candidate_domains": ["rolling_hardware"],
            "reason_code": "article_query_candidate_domain_mismatch",
        },
        {
            "query_domains": ["rolling_hardware"],
            "candidate_domains": ["fastener"],
            "reason_code": "article_query_candidate_domain_mismatch",
        },
    ],
}

DEFAULT_GEMINI_POLICY: Dict[str, Any] = {
    "candidate_tiebreaker": {
        "enabled": True,
        "margin_threshold": 0.05,
        "branch_gap_threshold": 0.15,
        "min_candidates": 2,
        "max_candidates": 8,
    },
    "article_validator": {
        "enabled": True,
        "conflict_reasons": ["article_query_candidate_domain_mismatch"],
        "max_alternatives": 2,
        "min_domain_confidence": 0.5,
    },
    "family_router": {
        "enabled": True,
        "families": ["other", "cable", "wire"],
        "min_family_confidence": 0.6,
    },
}

DEFAULT_VERIFIER_POLICY: Dict[str, Dict[str, Any]] = {
    "default": {
        "auto_accept_sources": [],
        "review_sources": [],
        "reject_row_types": ["section"],
        "compatible_default_decision": "review",
        "default_review_reason": "default_review",
    },
    "article_resolver": {
        "auto_accept_sources": [
            "article_exact",
            "article_extracted_exact",
        ],
        "review_sources": [
            "article_series_local",
        ],
        "compatible_default_decision": "review",
    },
    "cable_designation_resolver": {
        "auto_accept_sources": [
            "article_designation_exact",
            "designation_exact",
        ],
        "compatible_default_decision": "review",
    },
    "direct_exact_resolver": {
        "auto_accept_sources": [
            "name_exact",
            "normalized_name_exact",
        ],
        "compatible_default_decision": "review",
    },
    "rack_tray_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_semantic_match",
    },
    "rack_tray_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_series_match",
    },
    "rack_tray_support_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_support_series_match",
    },
    "rack_tray_holder_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_holder_series_match",
    },
    "rack_tray_console_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_console_series_match",
    },
    "rack_tray_console_universal_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_console_universal_match",
    },
    "rack_tray_console_short_article_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_console_short_article_match",
    },
    "rack_tray_profile_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_profile_series_match",
    },
    "rack_tray_fitting_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_fitting_series_match",
    },
    "rack_tray_corner_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_corner_series_match",
    },
    "rack_tray_cpo_corner_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_cpo_corner_series_match",
    },
    "rack_tray_cd_corner_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_cd_corner_series_match",
    },
    "rack_tray_branch_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_branch_series_match",
    },
    "rack_tray_tee_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_tee_series_match",
    },
    "rack_tray_dl_tee_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_dl_tee_series_match",
    },
    "rack_tray_dl_tee_100_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_dl_tee_100_series_match",
    },
    "rack_tray_dl_tee_200_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_dl_tee_200_series_match",
    },
    "rack_tray_fastener_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_fastener_series_match",
    },
    "rack_tray_channel_series_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_channel_series_match",
    },
    "rack_tray_semantic_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_semantic_match",
    },
    "rack_tray_brush_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_brush_match",
    },
    "rack_tray_organizer_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_organizer_match",
    },
    "rack_tray_shelf_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_shelf_match",
    },
    "rack_tray_plate_semantic_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_plate_match",
    },
    "grounding_review_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_grounding_match",
    },
    "grounding_ptce_review_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_grounding_ptce_match",
    },
    "telecom_semantic_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_semantic_match",
    },
    "telecom_component_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_component_match",
    },
    "telecom_panel_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_panel_match",
    },
    "telecom_block_panel_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_block_panel_match",
    },
    "telecom_block_panel_unshielded_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_block_panel_unshielded_match",
    },
    "telecom_block_panel_shielded_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_block_panel_shielded_match",
    },
    "telecom_modular_panel_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_modular_panel_match",
    },
    "telecom_modular_panel_unshielded_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_modular_panel_unshielded_match",
    },
    "telecom_modular_panel_shielded_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_modular_panel_shielded_match",
    },
    "telecom_connector_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_connector_match",
    },
    "telecom_connector_unshielded_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_connector_unshielded_match",
    },
    "telecom_connector_unshielded_cat6a_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_connector_unshielded_cat6a_match",
    },
    "telecom_connector_shielded_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_connector_shielded_match",
    },
    "telecom_connector_shielded_cat6a_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_connector_shielded_cat6a_match",
    },
    "telecom_keystone_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_keystone_match",
    },
    "telecom_keystone_unshielded_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_keystone_unshielded_match",
    },
    "telecom_keystone_unshielded_cat6a_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_keystone_unshielded_cat6a_match",
    },
    "telecom_keystone_shielded_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_keystone_shielded_match",
    },
    "telecom_keystone_shielded_cat6a_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_keystone_shielded_cat6a_match",
    },
    "telecom_construct_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_construct_match",
    },
    "telecom_channel_construct_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_channel_construct_match",
    },
    "telecom_channel_single_port_construct_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_channel_single_port_construct_match",
    },
    "telecom_channel_single_port_assembly_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_channel_single_port_assembly_match",
    },
    "telecom_channel_single_port_mount_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_channel_single_port_mount_match",
    },
    "telecom_channel_dual_port_construct_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_channel_dual_port_construct_match",
    },
    "telecom_wallbox_construct_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_wallbox_construct_match",
    },
    "telecom_wallbox_single_port_construct_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_wallbox_single_port_construct_match",
    },
    "telecom_wallbox_dual_port_construct_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_wallbox_dual_port_construct_match",
    },
    "telecom_floorbox_construct_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_floorbox_construct_match",
    },
    "telecom_floorbox_single_port_construct_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_floorbox_single_port_construct_match",
    },
    "telecom_floorbox_dual_port_construct_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_floorbox_dual_port_construct_match",
    },
    "telecom_outlet_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_outlet_match",
    },
    "telecom_pdu_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_pdu_match",
    },
    "telecom_pdu_vertical_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_pdu_vertical_match",
    },
    "telecom_pdu_metered_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_pdu_metered_match",
    },
    "telecom_airflow_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_airflow_match",
    },
    "telecom_airflow_panel_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_airflow_panel_match",
    },
    "telecom_airflow_blanking_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_airflow_blanking_match",
    },
    "telecom_airflow_free_units_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_airflow_free_units_match",
    },
    "telecom_airflow_flow_control_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_airflow_flow_control_match",
    },
    "telecom_optical_patch_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_optical_patch_match",
    },
    "telecom_optical_patch_singlemode_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_optical_patch_singlemode_match",
    },
    "telecom_optical_patch_singlemode_duplex_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_optical_patch_singlemode_duplex_match",
    },
    "telecom_optical_patch_multimode_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_optical_patch_multimode_match",
    },
    "telecom_optical_cross_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_optical_cross_match",
    },
    "telecom_optical_cross_populated_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_optical_cross_populated_match",
    },
    "telecom_optical_cross_populated_1u_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_optical_cross_populated_1u_match",
    },
    "telecom_optical_cross_populated_2u_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_optical_cross_populated_2u_match",
    },
    "telecom_optical_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_optical_match",
    },
    "telecom_infra_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_infra_match",
    },
    "semantic_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_generic_semantic_match",
    },
    "series_review_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_series_or_short_article_match",
    },
    "rack_tray_short_article_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_short_article_match",
    },
    "rack_tray_short_article_tray_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_short_article_tray_match",
    },
    "software_review_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_software_or_license_match",
    },
    "software_server_review_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_software_server_match",
    },
    "software_monitoring_review_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_software_monitoring_match",
    },
    "monitoring_review_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_monitoring_hw_match",
    },
    "monitoring_arm_review_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_monitoring_arm_match",
    },
    "monitoring_display_review_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_monitoring_display_match",
    },
    "monitoring_control_review_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_monitoring_control_match",
    },
    "sensor_review_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_sensor_match",
    },
    "fallback_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_fallback_match",
    },
    "reject_resolver": {
        "auto_accept_sources": [],
        "compatible_default_decision": "reject",
    },
}

DEFAULT_AUDIT_SCOPE: Dict[str, Any] = {
    "audited_families": [
        "airflow_blanking_panel",
        "ats_sts",
        "bulk_twisted_pair",
        "cable",
        "coax",
        "floor_box",
        "ground_bar",
        "iec_power_cable",
        "keystone",
        "optical_cross",
        "optical_patch_cord",
        "patch_cord",
        "patch_panel",
        "rack",
        "rack_accessory_strict",
        "rack_rail",
        "rack_shelf",
        "rj45_connector",
        "rj45_outlet",
        "sensor",
        "wire",
    ],
    "family_groups": {
        "patch_panel": "patch_panel",
        "patch_cord": "patch_cord",
        "keystone": "keystone_rj45",
        "keystone_adapter": "keystone_rj45",
        "rj45_connector": "keystone_rj45",
        "rj45_outlet": "keystone_rj45",
        "bulk_twisted_pair": "twisted_pair",
        "iec_power_cable": "iec_power_cable",
        "optical_cross": "optical_cross",
        "optical_patch_cord": "optical_patch_cord",
        "ats_sts": "ats_sts",
        "airflow_blanking_panel": "airflow_accessories",
        "rack_accessory_strict": "rack_accessories",
        "rack_shelf": "rack_accessories",
        "rack_rail": "rack_accessories",
        "cable": "electrical_cable",
        "wire": "electrical_cable",
        "coax": "electrical_cable",
        "ground_bar": "grounding",
        "floor_box": "floor_box",
        "rack": "rack",
        "sensor": "sensor",
    },
    "family_group_labels": {
        "patch_panel": "patch_panel",
        "patch_cord": "patch_cord",
        "keystone_rj45": "keystone/rj45",
        "twisted_pair": "twisted_pair",
        "iec_power_cable": "iec_power_cable",
        "optical_cross": "optical_cross",
        "optical_patch_cord": "optical_patch_cord",
        "ats_sts": "ats_sts",
        "airflow_accessories": "airflow/accessories",
        "rack_accessories": "rack accessories",
        "electrical_cable": "electrical cable",
        "grounding": "grounding",
        "floor_box": "floor_box",
        "rack": "rack",
        "sensor": "sensor",
    },
}

DEFAULT_TAXONOMY_EXTENSIONS: Dict[str, Any] = {
    "family_registry": DEFAULT_FAMILY_REGISTRY,
    "domain_registry": DEFAULT_DOMAIN_REGISTRY,
    "gemini_policy": DEFAULT_GEMINI_POLICY,
    "verifier_policy": DEFAULT_VERIFIER_POLICY,
    "audit_scope": DEFAULT_AUDIT_SCOPE,
}


def clean_registry_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def normalize_registry_text(text: Any) -> str:
    normalized = clean_registry_text(text).lower().replace("ё", "е")
    normalized = re.sub(r"[^\w\dа-я]+", " ", normalized, flags=re.IGNORECASE)
    return " ".join(normalized.split())


def merge_registry_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = merge_registry_dicts(existing, value)
        else:
            merged[key] = value
    return merged


def load_registry_taxonomy_rules(
    *,
    base_rules: Mapping[str, Any] | None = None,
    path: str | Path | None = None,
) -> Dict[str, Any]:
    path_raw = str(path or os.getenv("REMO_TAXONOMY_RULES_PATH") or DEFAULT_TAXONOMY_RULES_PATH)
    resolved_path = Path(path_raw)
    rules = merge_registry_dicts(dict(base_rules or {}), DEFAULT_TAXONOMY_EXTENSIONS)
    if not resolved_path.exists():
        return rules
    try:
        loaded = json.loads(resolved_path.read_text(encoding="utf-8"))
    except Exception:
        return rules
    if not isinstance(loaded, dict):
        return rules
    return merge_registry_dicts(rules, loaded)


def family_registry(rules: Mapping[str, Any] | None) -> Dict[str, Dict[str, Any]]:
    return dict((rules or {}).get("family_registry", {}) or {})


def entity_family_for_type(entity_type: str, rules: Mapping[str, Any] | None) -> str:
    normalized = clean_registry_text(entity_type).lower()
    if not normalized:
        return ""
    for family_name, spec in family_registry(rules).items():
        entity_types = [clean_registry_text(item).lower() for item in spec.get("entity_types", [])]
        if normalized == family_name or normalized in entity_types:
            return family_name
    return normalized


def family_spec_for(entity_family: str, rules: Mapping[str, Any] | None) -> Dict[str, Any]:
    family_name = entity_family_for_type(entity_family, rules)
    return dict(family_registry(rules).get(family_name, {}) or {})


def family_entity_types(entity_family: str, rules: Mapping[str, Any] | None) -> set[str]:
    family_name = entity_family_for_type(entity_family, rules)
    spec = family_spec_for(family_name, rules)
    entity_types = {
        clean_registry_text(item).lower()
        for item in spec.get("entity_types", [])
        if clean_registry_text(item)
    }
    if not entity_types and family_name:
        entity_types.add(family_name)
    return entity_types


def family_default_branches(
    entity_family: str,
    rules: Mapping[str, Any] | None,
    *,
    branch_hint: str = "",
) -> list[str]:
    family_name = entity_family_for_type(entity_family, rules)
    defaults: list[str] = []
    cleaned_hint = clean_registry_text(branch_hint).lower()
    if cleaned_hint and cleaned_hint != "прочее":
        defaults.append(cleaned_hint)
    for branch_path in family_spec_for(family_name, rules).get("default_branches", []) or []:
        normalized = clean_registry_text(branch_path).lower()
        if normalized and normalized not in defaults:
            defaults.append(normalized)
    return defaults or (["прочее"] if family_name else [])


def family_retrieval_mode(entity_family: str, rules: Mapping[str, Any] | None) -> str:
    mode = clean_registry_text(family_spec_for(entity_family, rules).get("retrieval_mode")).lower()
    return mode or "branch_limited"


def is_whole_category_family(entity_family: str, rules: Mapping[str, Any] | None) -> bool:
    return family_retrieval_mode(entity_family, rules) == "whole_category"


def family_strictness(
    entity_family: str,
    rules: Mapping[str, Any] | None,
    *,
    markers: Mapping[str, Any] | None = None,
) -> str:
    spec = family_spec_for(entity_family, rules)
    normalized_markers = {clean_registry_text(key): clean_registry_text(value) for key, value in (markers or {}).items()}
    for override in spec.get("strictness_overrides", []) or []:
        when_any_markers = [clean_registry_text(item) for item in override.get("when_any_markers", []) or []]
        if when_any_markers and any(normalized_markers.get(marker_name) for marker_name in when_any_markers):
            override_value = clean_registry_text(override.get("value")).lower()
            if override_value:
                return override_value
    strictness = clean_registry_text(spec.get("strictness")).lower()
    return strictness or "generic"


def family_weak_match_policy(entity_family: str, rules: Mapping[str, Any] | None) -> str:
    value = clean_registry_text(family_spec_for(entity_family, rules).get("weak_match_policy")).lower()
    return value or "allow"


def family_requires_same_family_gate(entity_family: str, rules: Mapping[str, Any] | None) -> bool:
    return bool(family_spec_for(entity_family, rules).get("same_family_gate"))


def allowed_cross_family_pairs(rules: Mapping[str, Any] | None) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for family_name, spec in family_registry(rules).items():
        for other in spec.get("allowed_cross_family_pairs", []) or []:
            normalized_other = entity_family_for_type(clean_registry_text(other), rules)
            if family_name and normalized_other:
                pairs.add((family_name, normalized_other))
    return pairs


def family_secondary_filter_rules(entity_family: str, rules: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    raw_rules = family_spec_for(entity_family, rules).get("secondary_filter_rules", []) or []
    return [dict(rule) for rule in raw_rules if isinstance(rule, dict)]


def audited_families(rules: Mapping[str, Any] | None) -> set[str]:
    configured = {
        entity_family_for_type(item, rules)
        for item in ((rules or {}).get("audit_scope", {}) or {}).get("audited_families", [])
        if clean_registry_text(item)
    }
    if configured:
        return configured
    return {
        family_name
        for family_name, spec in family_registry(rules).items()
        if bool(spec.get("audited"))
    }


def audit_family_groups(rules: Mapping[str, Any] | None) -> Dict[str, str]:
    raw = ((rules or {}).get("audit_scope", {}) or {}).get("family_groups", {}) or {}
    prepared: Dict[str, str] = {}
    for family_name, group_name in raw.items():
        normalized_family = entity_family_for_type(clean_registry_text(family_name), rules)
        normalized_group = clean_registry_text(group_name).lower()
        if normalized_family and normalized_group:
            prepared[normalized_family] = normalized_group
    return prepared


def audit_family_group_labels(rules: Mapping[str, Any] | None) -> Dict[str, str]:
    raw = ((rules or {}).get("audit_scope", {}) or {}).get("family_group_labels", {}) or {}
    return {
        clean_registry_text(group_name).lower(): clean_registry_text(label)
        for group_name, label in raw.items()
        if clean_registry_text(group_name) and clean_registry_text(label)
    }


def gemini_policy_value(
    rules: Mapping[str, Any] | None,
    policy_name: str,
    field_name: str,
    default: Any = None,
) -> Any:
    gemini_policy = ((rules or {}).get("gemini_policy", {}) or {}).get(policy_name, {}) or {}
    value = gemini_policy.get(field_name)
    return default if value is None else value


def verifier_policy_for_resolver(
    rules: Mapping[str, Any] | None,
    resolver_path: str,
) -> Dict[str, Any]:
    root = (rules or {}).get("verifier_policy", {}) or {}
    default_policy = dict(root.get("default", {}) or {})
    resolver_policy = dict(root.get(clean_registry_text(resolver_path), {}) or {})
    return merge_registry_dicts(default_policy, resolver_policy)


def verifier_auto_accept_sources(
    rules: Mapping[str, Any] | None,
    resolver_path: str,
) -> set[str]:
    policy = verifier_policy_for_resolver(rules, resolver_path)
    return {
        clean_registry_text(item)
        for item in (policy.get("auto_accept_sources", []) or [])
        if clean_registry_text(item)
    }


def verifier_review_sources(
    rules: Mapping[str, Any] | None,
    resolver_path: str,
) -> set[str]:
    policy = verifier_policy_for_resolver(rules, resolver_path)
    return {
        clean_registry_text(item)
        for item in (policy.get("review_sources", []) or [])
        if clean_registry_text(item)
    }


def verifier_reject_row_types(
    rules: Mapping[str, Any] | None,
    resolver_path: str,
) -> set[str]:
    policy = verifier_policy_for_resolver(rules, resolver_path)
    return {
        clean_registry_text(item).lower()
        for item in (policy.get("reject_row_types", []) or [])
        if clean_registry_text(item)
    }


def verifier_compatible_default_decision(
    rules: Mapping[str, Any] | None,
    resolver_path: str,
    default: str = "review",
) -> str:
    policy = verifier_policy_for_resolver(rules, resolver_path)
    decision = clean_registry_text(policy.get("compatible_default_decision")).lower()
    if decision in {"auto_accept", "review", "reject"}:
        return decision
    return default


def verifier_default_review_reason(
    rules: Mapping[str, Any] | None,
    resolver_path: str,
    default: str = "default_review",
) -> str:
    policy = verifier_policy_for_resolver(rules, resolver_path)
    reason = clean_registry_text(policy.get("default_review_reason"))
    return reason or default


def _patterns_match(text: str, patterns: Iterable[str]) -> int:
    count = 0
    for pattern in patterns:
        normalized = normalize_registry_text(pattern)
        if normalized and normalized in text:
            count += 1
    return count


def classify_entity_type_from_registry(
    text: str,
    *,
    rules: Mapping[str, Any] | None,
    markers: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    normalized_text = normalize_registry_text(text)
    marker_values = {clean_registry_text(key): clean_registry_text(value).lower() for key, value in (markers or {}).items()}
    candidates: list[tuple[float, dict[str, Any]]] = []
    for family_name, spec in family_registry(rules).items():
        classifier = dict(spec.get("classifier", {}) or {})
        if not classifier:
            continue
        positive_patterns = classifier.get("positive_patterns", []) or []
        negative_patterns = classifier.get("negative_patterns", []) or []
        required_markers = classifier.get("required_markers", {}) or {}
        required_any_tokens = classifier.get("required_any_tokens", []) or []
        if negative_patterns and _patterns_match(normalized_text, negative_patterns):
            continue
        positive_hits = _patterns_match(normalized_text, positive_patterns)
        if positive_patterns and positive_hits == 0:
            continue
        if required_any_tokens:
            if not all(any(normalize_registry_text(token) in normalized_text for token in token_group) for token_group in required_any_tokens):
                continue
        marker_ok = True
        for marker_name, allowed_values in required_markers.items():
            candidate_value = marker_values.get(clean_registry_text(marker_name))
            normalized_allowed = {
                clean_registry_text(item).lower()
                for item in (allowed_values if isinstance(allowed_values, (list, tuple, set)) else [allowed_values])
                if clean_registry_text(item)
            }
            if normalized_allowed and candidate_value not in normalized_allowed:
                marker_ok = False
                break
        if not marker_ok:
            continue
        priority = float(classifier.get("priority", 0.0) or 0.0)
        confidence = min(0.99, 0.45 + (positive_hits * 0.15) + (0.1 if required_any_tokens else 0.0) + (priority / 1000.0))
        candidates.append(
            (
                priority + positive_hits,
                {
                    "family": family_name,
                    "entity_type": clean_registry_text(classifier.get("returns")) or family_name,
                    "confidence": confidence,
                },
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def infer_domain_match(
    text: str,
    *,
    entity_family: str = "",
    rules: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized_text = normalize_registry_text(text)
    family_name = entity_family_for_type(entity_family, rules)
    best_label = ""
    best_score = 0.0
    best_hits = 0
    for label, spec in (((rules or {}).get("domain_registry", {}) or {}).get("domains", {}) or {}).items():
        patterns = spec.get("patterns", []) or []
        families = {entity_family_for_type(item, rules) for item in spec.get("families", []) or [] if clean_registry_text(item)}
        hits = _patterns_match(normalized_text, patterns)
        score = float(hits)
        if family_name and family_name in families:
            score += 1.5
        if score > best_score:
            best_label = clean_registry_text(label).lower()
            best_score = score
            best_hits = hits
    confidence = min(0.99, 0.35 + (best_score * 0.15)) if best_score > 0 else 0.0
    return {
        "label": best_label,
        "confidence": confidence,
        "pattern_hits": best_hits,
        "family": family_name,
    }


def domain_conflict_reason(
    query_text: str,
    candidate_text: str,
    *,
    query_family: str = "",
    candidate_family: str = "",
    rules: Mapping[str, Any] | None,
    min_confidence: float = 0.35,
) -> str:
    query_domain = infer_domain_match(query_text, entity_family=query_family, rules=rules)
    candidate_domain = infer_domain_match(candidate_text, entity_family=candidate_family, rules=rules)
    if query_domain["confidence"] < min_confidence or candidate_domain["confidence"] < min_confidence:
        return ""
    query_label = clean_registry_text(query_domain.get("label")).lower()
    candidate_label = clean_registry_text(candidate_domain.get("label")).lower()
    if not query_label or not candidate_label or query_label == candidate_label:
        return ""
    for rule in (((rules or {}).get("domain_registry", {}) or {}).get("conflicts", []) or []):
        query_domains = {clean_registry_text(item).lower() for item in rule.get("query_domains", []) or [] if clean_registry_text(item)}
        candidate_domains = {clean_registry_text(item).lower() for item in rule.get("candidate_domains", []) or [] if clean_registry_text(item)}
        if query_label in query_domains and candidate_label in candidate_domains:
            return clean_registry_text(rule.get("reason_code")) or "article_query_candidate_domain_mismatch"
    return ""
