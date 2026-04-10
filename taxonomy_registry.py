from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
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
        "default_branches": ["электрика > автоматы", "рубильники"],
        "retrieval_mode": "branch_limited",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
    },
    "surge_protector": {
        "entity_types": ["surge_protector"],
        "default_branches": ["ограничители импульсного перенапряжения силовые модульные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 58,
            "positive_patterns": [
                "ограничитель импульсного перенапряжения",
                "ограничители импульсного перенапряжения",
                "перенапряжен",
                "узип",
                "spd",
                "surge protector",
                "surge arrester",
            ],
            "negative_patterns": ["предохранител", "автомат", "рубильник"],
        },
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
    "fastener": {
        "entity_types": ["fastener"],
        "default_branches": ["крепежные изделия для кабеленесущих систем"],
        "retrieval_mode": "branch_limited",
        "strictness": "strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 72,
            "positive_patterns": ["анкер", "болт", "шуруп", "шпильк", "дюбел", "гайк", "шайб", "крепеж"],
        },
    },
    "box": {
        "entity_types": ["box"],
        "default_branches": [
            "коробки распределительные наружные",
            "коробки распределительные внутренние",
            "коробки установочные",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 62,
            "positive_patterns": ["коробка", "монтажная коробка", "распределительная коробка", "установочная коробка"],
            "negative_patterns": ["лючок", "кабель-канал", "кабель канал", "rj45", "keystone", "патч"],
            "required_any_tokens": [["коробка"], ["распредел", "монтажн", "установоч", "распаеч", "огнестойк"]],
        },
    },
    "box_accessory": {
        "entity_types": ["box_accessory"],
        "default_branches": [
            "аксессуары и комплектующие для коробок",
            "аксессуары для установочных коробок",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 58,
            "positive_patterns": ["аксессуар", "комплектующ", "принадлежн"],
            "negative_patterns": ["rj45", "keystone", "патч", "кабель-канал", "кабель канал"],
            "required_any_tokens": [["аксессуар", "комплектующ", "принадлежн"], ["короб"]],
        },
    },
    "distribution_enclosure": {
        "entity_types": ["distribution_enclosure"],
        "default_branches": [
            "корпуса учетно-распределительные встраиваемые металлические",
            "корпуса учетно-распределительные навесные металлические",
            "корпуса распределительные встраиваемые пластиковые",
            "корпуса распределительные навесные пластиковые",
            "корпуса распределительные встраиваемые",
            "корпуса распределительные навесные",
            "корпуса учетно-распределительные навесные пластиковые",
            "корпуса щитов монтажных металлических",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 60,
            "positive_patterns": [
                "щит распределительный",
                "силовой щит",
                "щит с монтажной панелью",
                "щит этажный",
                "встраиваемый щит",
                "навесной щит",
                "электрощит",
                "корпус распределительный",
                "корпус учетно-распределительный",
                "корпус для модульных устройств",
                "корпус мультимедиа",
                "корпуса щитов монтажных металлических",
                "бокс модульный",
                "щрв",
                "щрн",
                "щурв",
                "щурн",
                "щмп",
                "distribution enclosure",
                "distribution board",
            ],
            "negative_patterns": [
                "заглуш",
                "рамк",
                "аксессуар",
                "комплектующ",
                "козырек",
                "кожух",
                "петл",
                "замок",
                "окно герметичное",
                "ограничитель угла открытия двери",
                "комплект для навески",
                "комплект для монтажа щитов",
                "щитовые аксессуары",
                "дополнительные двери",
                "din-рейк",
                "din рейк",
            ],
            "required_any_tokens": [["щит", "щиток", "корпус", "бокс", "щрв", "щрн", "щурв", "щурн", "щмп"], ["распредел", "учет", "встраив", "навес", "модул", "электрощит", "этажн", "монтажн", "мультимедиа"]],
        },
    },
    "reactive_power_compensator": {
        "entity_types": ["reactive_power_compensator"],
        "default_branches": [
            "устройства компенсации реактивной мощности 0.4кв",
            "конденсаторные установки",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 54,
            "positive_patterns": [
                "устройство компенсации реактивной мощности",
                "компенсация реактивной мощности",
                "конденсаторная установка",
                "конденсаторные установки",
                "укрм",
                "reactive power compensation",
                "capacitor bank",
            ],
            "negative_patterns": ["конденсатор пусковой", "конденсатор моторный", "single capacitor"],
            "required_any_tokens": [
                ["реактивн", "capacitor", "укрм", "конденсаторн"],
                ["мощност", "компенсац", "установк", "bank"],
            ],
        },
    },
    "switchboard_accessory": {
        "entity_types": ["switchboard_accessory"],
        "default_branches": [
            "вспомогательные щитовые аксессуары",
            "материалы для оформления и вспомогательные щитовые аксессуары",
            "дополнительные двери",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 61,
            "positive_patterns": [
                "вспомогательные щитовые аксессуары",
                "материалы для оформления и вспомогательные щитовые аксессуары",
                "дополнительные двери",
                "дверь внутренняя щмп",
                "козырек защитный щмп",
                "комплект для навески щмп",
                "панель монтажная",
                "окно герметичное",
                "ограничитель угла открытия двери",
                "петли для корпусов",
                "щитовые аксессуары",
                "switchboard accessory",
                "enclosure accessory",
            ],
            "negative_patterns": [
                "печатная плата",
                "pcb",
                "rj45",
                "keystone",
                "патч",
            ],
            "required_any_tokens": [
                ["щит", "щитка", "щита", "щитовые", "щмп", "щурн", "корпус"],
                ["аксессуар", "петл", "козырек", "крепеж", "замок", "окно", "переходник", "кожух", "планка", "уголок", "комплект"],
            ],
        },
    },
    "cable_channel": {
        "entity_types": ["cable_channel"],
        "default_branches": [
            "электрика > кабели > кабель-каналы",
            "перфорированные кабель-каналы",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 61,
            "positive_patterns": [
                "кабель-канал",
                "кабель канал",
                "перфорированный короб",
                "перфокороб",
                "перфорированные кабель-каналы",
            ],
            "negative_patterns": [
                "коробка",
                "лючок",
                "rj45",
                "keystone",
                "патч",
                "угол",
                "тройник",
                "заглуш",
                "крышк",
                "ответвител",
                "переходник",
                "соединител",
                "накладк",
                "подвес",
                "креплен",
            ],
        },
    },
    "switch_wiring": {
        "entity_types": ["switch_wiring", "socket"],
        "default_branches": [
            "выключатели скрытого монтажа",
            "выключатели открытого монтажа",
            "переключатели скрытого монтажа",
            "переключатели открытого монтажа",
            "розетки скрытого монтажа",
            "розетки открытого монтажа",
            "клавиши",
            "накладки",
            "рамки",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 60,
            "positive_patterns": ["выключател", "переключател", "розетк", "рамк", "клавиш", "диммер"],
            "negative_patterns": ["rj45", "keystone", "патч", "pdu", "блок розеток", "zero u", "лючок", "кабель-канал", "кабель канал", "удлинител", "сетевой фильтр", "штепсель", "вилка"],
        },
    },
    "lighting_fixture": {
        "entity_types": ["lighting_fixture"],
        "default_branches": [
            "свет > светильники",
            "люстры под лампу",
            "ленты светодиодные 12в",
            "ленты светодиодные 24в",
            "ленты светодиодные 220в",
            "профиль для светодиодной ленты",
            "блок питания и драйвер для светодиодной ленты",
            "лампы светодиодные е27, е14, е40",
            "лампы светодиодные g, gx, gu",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 56,
            "positive_patterns": ["светильник", "люстра", "прожектор", "светодиодн", "дво", "дсо", "дсп", "дпо", "дку"],
            "negative_patterns": ["световое табло", "табло выход"],
        },
    },
    "tray_sheet": {
        "entity_types": ["tray_sheet"],
        "default_branches": [
            "листовые лотки оцинкованные (метод сендзимира)",
            "листовые лотки горячеоцинкованные (метод погружения)",
            "листовые лотки с покрытием цинк-ламель",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "лоток",
                "крышк",
                "ответвител",
                "угол",
                "консол",
                "пластин",
                "перегород",
                "листов",
                "ptce",
                "gto",
                "sep",
            ],
            "negative_patterns": ["светильник", "реле", "контактор"],
        },
    },
    "contactor_starter": {
        "entity_types": ["contactor_starter"],
        "default_branches": ["контакторы магнитные", "пускатели магнитные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 58,
            "positive_patterns": ["контактор", "пускател"],
        },
    },
    "control_relay": {
        "entity_types": ["control_relay"],
        "default_branches": ["промежуточные реле"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 54,
            "positive_patterns": ["реле"],
            "negative_patterns": ["рельс", "rack rail", "тепловое реле"],
        },
    },
    "light_signage": {
        "entity_types": ["light_signage"],
        "default_branches": ["световое табло", "свето-звуковое табло"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 57,
            "positive_patterns": ["табло", "выход", "exit", "свето-звуков"],
            "required_any_tokens": [["табло", "выход", "exit"], ["светов", "свето", "эвакуац", "аварийн", "звуков"]],
        },
    },
    "safety_sign": {
        "entity_types": ["safety_sign"],
        "default_branches": ["знаки безопасности"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 56,
            "positive_patterns": ["знак", "знаки безопасности", "эвакуац"],
            "required_any_tokens": [["знак"], ["безопас", "эвакуац", "пиктограмм"]],
            "negative_patterns": ["табло", "оповещател", "извещател"],
        },
    },
    "fire_detector": {
        "entity_types": ["fire_detector"],
        "default_branches": [
            "извещатели пожарные",
            "извещатели охранные",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 69,
            "positive_patterns": ["извещател"],
            "negative_patterns": ["оповещател", "комплект", "креплен", "кроншт", "табло"],
        },
    },
    "fire_annunciator": {
        "entity_types": ["fire_annunciator"],
        "default_branches": [
            "световой оповещатель",
            "звуковой оповещатель",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 68,
            "positive_patterns": ["оповещател"],
            "negative_patterns": ["табло", "извещател"],
        },
    },
    "fire_alarm_device": {
        "entity_types": ["fire_alarm_device"],
        "default_branches": [
            "извещатели пожарные",
            "извещатели охранные",
            "световой оповещатель",
            "звуковой оповещатель",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 63,
            "positive_patterns": ["извещател", "оповещател"],
            "negative_patterns": ["комплект", "креплен", "кроншт", "табло"],
        },
    },
    "security_interface_device": {
        "entity_types": ["security_interface_device"],
        "default_branches": [
            "дополнительное оборудование для пс",
            "дополнительное оборудование систем оповещения",
            "дополнительное оборудование для ос",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 68,
            "required_any_tokens": [
                ["преобразователь", "повторитель", "интерфейс"],
                ["rs485", "modbus", "ethernet", "интерфейс", "протокол"],
            ],
        },
    },
    "security_control_panel": {
        "entity_types": ["security_control_panel"],
        "default_branches": [
            "приборы приёмно-контрольные для опс",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 67,
            "required_any_tokens": [
                ["пульт", "панель", "блок"],
                ["управл", "контрол", "индикац"],
            ],
            "negative_patterns": ["интерфейс", "modbus", "rs485", "резервного питания", "блок реле", "бру", "акб"],
        },
    },
    "security_module_device": {
        "entity_types": ["security_module_device"],
        "default_branches": [
            "дополнительное оборудование для пс",
            "приборы приёмно-контрольные для опс",
            "дополнительное оборудование для ос",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 66,
            "required_any_tokens": [
                ["модуль", "блок", "устройство"],
                ["пуск", "коммутац", "линии связи", "нагрузк", "изолир", "разветв", "адресн", "реле", "релейн", "бру"],
            ],
            "negative_patterns": ["интерфейс", "modbus", "rs485", "пульт", "индикац", "промежуточное реле", "промежуточные реле", "реле контроля напряжения", "тепловое реле"],
        },
    },
    "security_control_device": {
        "entity_types": ["security_control_device"],
        "default_branches": [
            "приборы приёмно-контрольные для опс",
            "дополнительное оборудование для пс",
            "дополнительное оборудование систем оповещения",
            "дополнительное оборудование для ос",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 61,
            "required_any_tokens": [
                ["пульт", "блок", "модуль", "преобразователь", "устройство"],
                ["контрол", "интерфейс", "сигнальн", "пуск", "коммутац", "линии связи", "адресн", "нагрузк", "изолир", "разветв"],
            ],
        },
    },
    "security_software": {
        "entity_types": ["security_software"],
        "default_branches": ["программное обеспечение опс"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 66,
            "positive_patterns": [
                "орион про",
                "программное обеспечение",
                "генератор отчетов",
                "администратор базы данных",
                "по сервер",
                "по мониторинга",
            ],
        },
    },
    "power_backup": {
        "entity_types": ["power_backup"],
        "default_branches": [
            "аккумуляторы стационарные",
            "аккумуляторы для автомобиля",
            "дополнительное оборудование для ос",
            "приборы приёмно-контрольные для опс",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 59,
            "positive_patterns": [
                "источник питания",
                "аккумулятор",
                "аккумуляторная батарея",
                "батарея",
                "блок резервного питания",
                "резервный источник питания",
                "резервированн источник питания",
            ],
        },
    },
    "firestop_material": {
        "entity_types": ["firestop_material"],
        "default_branches": ["защитные составы", "проходки огнестойкие"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 60,
            "positive_patterns": ["огнезащит", "герметик", "пена", "проходк", "огнестойк"],
            "negative_patterns": ["кабельная линия", "коробка"],
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
    "neutral_busbar": {
        "entity_types": ["neutral_busbar"],
        "default_branches": ["нулевые шины на din-рейку"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "нулевая шина",
                "нулевые шины",
                "шина нулевая",
                "neutral bus",
                "n busbar",
            ],
            "negative_patterns": [
                "заземл",
                "pe",
                "клемм",
                "клеммник",
                "terminal block",
            ],
            "required_any_tokens": [["нулев", "neutral"], ["шин", "bus"]],
        },
    },
    "industrial_valve": {
        "entity_types": ["industrial_valve"],
        "default_branches": [
            "затворы поворотные дисковые стальные",
            "затворы поворотные дисковые чугунные",
            "краны шаровые стальные",
            "краны шаровые латунные для воды",
            "краны шаровые пнд",
            "клапаны электромагнитные (соленоидные)",
            "клапаны регулирующие чугунные",
            "клапаны запорные (вентили) стальные",
            "клапаны обратные чугунные",
            "задвижки чугунные клиновые",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 54,
            "positive_patterns": [
                "затвор",
                "butterfly valve",
                "ball valve",
                "кран шаров",
                "краны шаров",
                "клапан электромагнитн",
                "соленоид",
                "клапан регулирующ",
                "клапаны регулирующ",
                "вентиль",
                "клапан запорн",
                "клапан обратн",
                "задвижк",
            ],
        },
    },
    "industrial_pump": {
        "entity_types": ["industrial_pump"],
        "default_branches": ["промышленные вертикальные центробежные насосы"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 54,
            "positive_patterns": [
                "насос",
                "pump",
                "центробежный насос",
                "вертикальный насос",
            ],
            "negative_patterns": [
                "клапан",
                "затвор",
                "кран шаровой",
                "электродвигатель",
                "преобразователь частоты",
                "частотный привод",
            ],
            "required_any_tokens": [["насос", "pump"]],
        },
    },
    "thread_tap": {
        "entity_types": ["thread_tap"],
        "default_branches": ["метчики"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "метчик",
                "метчики",
                "tap",
                "thread tap",
                "машинно ручной метчик",
            ],
            "negative_patterns": [
                "сверл",
                "плашк",
                "держател",
                "вороток",
                "набор сверл",
                "drill",
                "die holder",
            ],
            "required_any_tokens": [["метчик", "tap"]],
        },
    },
    "thread_die": {
        "entity_types": ["thread_die"],
        "default_branches": ["плашки"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "плашка",
                "плашки",
                "thread die",
                "round die",
            ],
            "negative_patterns": [
                "метчик",
                "сверл",
                "держател",
                "вороток",
                "tap",
                "thread tap",
                "die holder",
            ],
            "required_any_tokens": [["плашк", "thread die", "round die"]],
        },
    },
    "thread_gauge": {
        "entity_types": ["thread_gauge"],
        "default_branches": ["резьбомеры"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "резьбомер",
                "резьбомеры",
                "thread gauge",
                "screw pitch gauge",
                "шаблон резьбы",
            ],
            "negative_patterns": [
                "метчик",
                "плашк",
                "калибр",
                "штангенцирк",
                "индикатор",
                "клещи",
            ],
            "required_any_tokens": [["резьбомер", "thread gauge", "pitch gauge", "шаблон резьбы"]],
        },
    },
    "threading_tool_set": {
        "entity_types": ["threading_tool_set"],
        "default_branches": ["наборы резьбонарезного инструмента"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "наборы резьбонарезного инструмента",
                "набор резьбонарезного инструмента",
                "threading tool set",
                "tap and die set",
            ],
            "negative_patterns": [
                "резьбомер",
                "сверл",
                "коронк",
                "фрез",
            ],
            "required_any_tokens": [["набор", "set"], ["резьбонарез", "threading", "tap and die"]],
        },
    },
    "file_tool": {
        "entity_types": ["file_tool"],
        "default_branches": ["напильники"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "напильник",
                "напильники",
                "надфиль",
                "надфили",
                "hand file",
                "metal file",
            ],
            "negative_patterns": [
                "маникюр",
                "пилка для ногтей",
                "рашпиль по дереву",
            ],
            "required_any_tokens": [["напиль", "надфил", "file"]],
        },
    },
    "socket_head_set": {
        "entity_types": ["socket_head_set"],
        "default_branches": ["торцевые головки и наборы головок"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "торцевая головка",
                "торцевые головки",
                "торцевых головок",
                "набор торцевых головок",
                "набор головок",
                "socket set",
                "socket wrench",
            ],
            "negative_patterns": [
                "головка блока",
                "головка цилиндра",
                "торцевая фреза",
                "битодержатель",
                "бита",
            ],
            "required_any_tokens": [["торцев", "socket"], ["головк", "набор"]],
        },
    },
    "drive_belt": {
        "entity_types": ["drive_belt"],
        "default_branches": ["ремни клиновые приводные", "ремни узкоклиновые"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "ремень клиновой",
                "ремни клиновые",
                "ремень узкоклиновой",
                "ремни узкоклиновые",
                "v-belt",
                "drive belt",
            ],
            "negative_patterns": [
                "ремень безопасности",
                "брючный ремень",
                "поясной ремень",
                "сумка",
                "одежда",
            ],
            "required_any_tokens": [["ремень", "belt"], ["клинов", "узкоклинов", "v-belt"]],
        },
    },
    "brass_threaded_fitting": {
        "entity_types": ["brass_threaded_fitting"],
        "default_branches": ["фитинги резьбовые латунные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "фитинг резьбовой латунный",
                "фитинги резьбовые латунные",
                "латунный фитинг",
                "brass fitting",
                "threaded fitting",
            ],
            "negative_patterns": [
                "полипропилен",
                "ппр",
                "ppr",
                "пнд",
                "press",
                "пресс",
                "обжим",
                "сварной",
            ],
            "required_any_tokens": [["фитинг", "fitting"], ["латун", "brass", "резьб", "threaded"]],
        },
    },
    "polypropylene_fitting": {
        "entity_types": ["polypropylene_fitting"],
        "default_branches": ["фитинги для полипропиленовых труб"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "фитинги для полипропиленовых труб",
                "фитинг полипропиленовый",
                "полипропиленовый фитинг",
                "ppr fitting",
                "pp-r fitting",
            ],
            "negative_patterns": [
                "латун",
                "brass",
                "резьбовой латунный",
                "обжим",
                "пресс",
                "press",
            ],
            "required_any_tokens": [["фитинг", "fitting"], ["полипропилен", "ppr", "pp-r"]],
        },
    },
    "axial_pex_fitting": {
        "entity_types": ["axial_pex_fitting"],
        "default_branches": ["фитинги аксиальные для pex, pert"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "фитинги аксиальные для pex",
                "фитинги аксиальные для pert",
                "фитинг аксиальный",
                "аксиальный фитинг",
                "pex fitting",
                "pert fitting",
            ],
            "negative_patterns": [
                "компрессион",
                "пнд",
                "латун",
                "полипропилен",
                "ppr",
                "press fitting",
                "пресс фитинг",
                "пресс-фитинг",
            ],
            "required_any_tokens": [["фитинг", "fitting"], ["аксиаль", "pex", "pert"]],
        },
    },
    "pnd_compression_fitting": {
        "entity_types": ["pnd_compression_fitting"],
        "default_branches": ["фитинги компрессионные для пнд труб пластиковые"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "фитинги компрессионные для пнд труб пластиковые",
                "компрессионный фитинг пнд",
                "фитинг пнд компрессионный",
                "pnd compression fitting",
                "pe compression fitting",
            ],
            "negative_patterns": [
                "аксиаль",
                "pex",
                "pert",
                "латун",
                "полипропилен",
                "ppr",
                "press fitting",
                "пресс фитинг",
                "пресс-фитинг",
            ],
            "required_any_tokens": [["фитинг", "fitting"], ["компрессион", "пнд", "compression"]],
        },
    },
    "metal_turning_tool": {
        "entity_types": ["metal_turning_tool"],
        "default_branches": ["резцы по металлу"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "резец по металлу",
                "резцы по металлу",
                "токарный резец",
                "lathe tool",
                "turning tool",
            ],
            "negative_patterns": [
                "сверл",
                "коронк",
                "диск",
                "плашк",
                "метчик",
                "зенкер",
            ],
            "required_any_tokens": [["резец", "lathe", "turning"], ["металл", "metal", "токар"]],
        },
    },
    "milling_cutter": {
        "entity_types": ["milling_cutter"],
        "default_branches": ["фрезы для станков"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "фреза",
                "фрезы для станков",
                "концевая фреза",
                "кольцевая фреза",
                "milling cutter",
            ],
            "negative_patterns": ["фрезер", "ручной", "router", "коронка", "сверло", "диск"],
            "required_any_tokens": [["фрез", "milling"]],
        },
    },
    "router_bit": {
        "entity_types": ["router_bit"],
        "default_branches": ["фрезы и наборы фрез для ручных фрезеров"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "фрезы и наборы фрез для ручных фрезеров",
                "фреза для ручного фрезера",
                "набор фрез для ручного фрезера",
                "router bit",
                "router cutter",
            ],
            "negative_patterns": ["фрезы для станков", "milling cutter", "коронка", "сверло", "диск"],
            "required_any_tokens": [["фрез", "router"], ["ручн", "фрезер", "router"]],
        },
    },
    "workwear": {
        "entity_types": ["workwear"],
        "default_branches": ["костюмы летние", "костюмы утепленные", "костюмы сварщика", "брюки, полукомбинезоны", "куртки утепленные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "костюм летний",
                "костюмы летние",
                "костюм утепленный",
                "костюмы утепленные",
                "костюм сварщика",
                "костюмы сварщика",
                "полукомбинезон рабочий",
                "полукомбинезоны рабочие",
                "брюки рабочие",
                "куртка утепленная",
                "куртки утепленные",
                "workwear suit",
                "workwear jacket",
                "workwear overall",
            ],
            "negative_patterns": [
                "купальник",
                "маскарад",
                "карнавальн",
            ],
            "required_any_tokens": [["костюм", "suit", "полукомбинез", "брюк", "куртк", "jacket", "overall", "workwear"], ["летн", "утеплен", "рабоч", "сварщ", "workwear"]],
        },
    },
    "safety_footwear": {
        "entity_types": ["safety_footwear"],
        "default_branches": ["ботинки рабочие", "полуботинки рабочие", "ботинки утепленные", "сапоги резиновые"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "ботинки рабочие",
                "полуботинки рабочие",
                "ботинки утепленные",
                "сапоги резиновые",
                "защитная обувь",
                "рабочие сапоги",
                "защитные сапоги",
                "work boots",
                "safety shoes",
            ],
            "negative_patterns": ["кроссовк", "тапк", "сандал", "домашн"],
            "required_any_tokens": [["ботин", "полуботин", "сапог", "обув", "boots", "shoes"], ["рабоч", "защит", "утепл", "резин", "safety", "work"]],
        },
    },
    "protective_gloves": {
        "entity_types": ["protective_gloves"],
        "default_branches": ["антипорезные и защитные перчатки"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "антипорезные перчатки",
                "защитные перчатки",
                "перчатки защитные",
                "перчатки защитные антипорезные",
                "рабочие перчатки",
                "protective gloves",
                "cut resistant gloves",
            ],
            "negative_patterns": [
                "боксерские",
                "варежки",
                "митенки",
            ],
            "required_any_tokens": [["перчат", "gloves"], ["защит", "антипорез", "resistant", "work"]],
        },
    },
    "safety_glasses": {
        "entity_types": ["safety_glasses"],
        "default_branches": ["защитные очки"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "защитные очки",
                "очки защитные",
                "safety glasses",
                "protective eyewear",
            ],
            "negative_patterns": ["очки виртуальной реальности", "солнцезащитные", "маска сварщика", "щиток лицевой"],
            "required_any_tokens": [["очк", "glasses", "eyewear"], ["защит", "safety", "protective"]],
        },
    },
    "protective_helmet": {
        "entity_types": ["protective_helmet"],
        "default_branches": ["каски"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": ["каска", "каски", "защитная каска", "safety helmet", "hard hat"],
            "negative_patterns": ["мотошлем", "велошлем", "шлем сварщика", "маска сварщика"],
            "required_any_tokens": [["каск", "helmet", "hat"], ["защит", "safety", "hard"]],
        },
    },
    "combination_wrench": {
        "entity_types": ["combination_wrench"],
        "default_branches": ["комбинированные ключи"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "комбинированный ключ",
                "ключ комбинированный",
                "комбинированные ключи",
                "рожково накидной ключ",
                "ключ рожково накидной",
                "combination wrench",
                "combination spanner",
            ],
            "negative_patterns": [
                "имбус",
                "шестигранник",
                "разводной",
                "трубный ключ",
                "ключ доступа",
            ],
            "required_any_tokens": [["ключ", "wrench", "spanner"], ["комбинирован", "рожково", "накидн", "combination"]],
        },
    },
    "open_end_wrench": {
        "entity_types": ["open_end_wrench"],
        "default_branches": ["рожковые ключи"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "рожковый ключ",
                "рожковые ключи",
                "ключ рожковый",
                "open end wrench",
                "open-end wrench",
                "open end spanner",
            ],
            "negative_patterns": [
                "комбинирован",
                "накидн",
                "имбус",
                "шестигран",
                "разводной",
                "трубный ключ",
                "ключ доступа",
            ],
            "required_any_tokens": [["ключ", "wrench", "spanner"], ["рожков", "open end"]],
        },
    },
    "ring_wrench": {
        "entity_types": ["ring_wrench"],
        "default_branches": ["накидные ключи"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "накидной ключ",
                "накидные ключи",
                "ключ накидной",
                "ring wrench",
                "box wrench",
                "box-end wrench",
            ],
            "negative_patterns": [
                "комбинирован",
                "рожков",
                "имбус",
                "шестигран",
                "разводной",
                "трубный ключ",
                "ключ доступа",
            ],
            "required_any_tokens": [["ключ", "wrench", "spanner"], ["накид", "ring", "box"]],
        },
    },
    "adjustable_wrench": {
        "entity_types": ["adjustable_wrench"],
        "default_branches": ["разводные ключи"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "разводной ключ",
                "разводные ключи",
                "ключ разводной",
                "adjustable wrench",
                "crescent wrench",
            ],
            "negative_patterns": [
                "комбинирован",
                "рожков",
                "накидн",
                "имбус",
                "шестигран",
                "трубный ключ",
                "ключ доступа",
            ],
            "required_any_tokens": [["ключ", "wrench"], ["развод", "adjustable", "crescent"]],
        },
    },
    "hex_key": {
        "entity_types": ["hex_key"],
        "default_branches": ["ключи имбусовые шестигранные (hex)"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "имбусовый ключ",
                "имбусовые ключи",
                "ключ имбусовый",
                "ключ шестигранный",
                "шестигранные ключи",
                "hex key",
                "allen key",
            ],
            "negative_patterns": [
                "бит",
                "битодержатель",
                "torx",
                "рожков",
                "накидн",
                "ключ доступа",
            ],
            "required_any_tokens": [["ключ", "key"], ["имбус", "шестигран", "hex", "allen"]],
        },
    },
    "caliper": {
        "entity_types": ["caliper"],
        "default_branches": ["штангенциркули"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "штангенциркуль",
                "штангенциркули",
                "vernier caliper",
                "digital caliper",
            ],
            "negative_patterns": [
                "суппорт",
                "скоба",
                "индикатор часового типа",
            ],
            "required_any_tokens": [["штангенцирк", "caliper"]],
        },
    },
    "micrometer": {
        "entity_types": ["micrometer"],
        "default_branches": ["микрометры"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "микрометр",
                "микрометры",
                "outside micrometer",
                "digital micrometer",
            ],
            "negative_patterns": ["микрометрический винт", "головка микрометрическая"],
            "required_any_tokens": [["микрометр", "micrometer"]],
        },
    },
    "bore_gauge": {
        "entity_types": ["bore_gauge"],
        "default_branches": ["нутромеры"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "нутромер",
                "нутромеры",
                "bore gauge",
                "inside gauge",
            ],
            "negative_patterns": ["микрометр", "штангенциркуль", "резьбомер", "индикатор часового типа"],
            "required_any_tokens": [["нутромер", "bore gauge", "inside gauge"]],
        },
    },
    "tape_measure": {
        "entity_types": ["tape_measure"],
        "default_branches": ["измерительные рулетки"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "измерительная рулетка",
                "измерительные рулетки",
                "рулетка",
                "tape measure",
                "measuring tape",
            ],
            "negative_patterns": ["рулетка казино", "рулетка игровая"],
            "required_any_tokens": [["рулетк", "tape measure", "measuring tape"]],
        },
    },
    "spirit_level": {
        "entity_types": ["spirit_level"],
        "default_branches": ["уровни пузырьковые"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "уровень пузырьковый",
                "уровни пузырьковые",
                "строительный уровень",
                "spirit level",
                "bubble level",
            ],
            "negative_patterns": ["лазерный", "нивелир", "уровнемер"],
            "required_any_tokens": [["уров", "level"], ["пузырьк", "строительн", "spirit", "bubble"]],
        },
    },
    "paint_roller": {
        "entity_types": ["paint_roller"],
        "default_branches": ["валики"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "малярный валик",
                "валик малярный",
                "валики",
                "paint roller",
                "roller cover",
            ],
            "negative_patterns": ["подшипник", "валик подшипника", "прижимной ролик", "ролик натяжной"],
            "required_any_tokens": [["валик", "roller"], ["маляр", "paint", "велюр", "поролон", "микрофиб"]],
        },
    },
    "paint_brush": {
        "entity_types": ["paint_brush"],
        "default_branches": ["кисти плоские флейцевые"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "кисть плоская флейцевая",
                "кисти плоские флейцевые",
                "кисть флейцевая",
                "флейцевая кисть",
                "paint brush",
                "flat brush",
            ],
            "negative_patterns": ["зубная щетка", "крацовка", "корщетка"],
            "required_any_tokens": [["кист", "brush"], ["флейц", "плоск", "paint", "flat"]],
        },
    },
    "wood_saw_blade": {
        "entity_types": ["wood_saw_blade"],
        "default_branches": ["пильные диски по дереву"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "пильный диск по дереву",
                "пильные диски по дереву",
                "диск по дереву",
                "saw blade wood",
                "wood saw blade",
            ],
            "negative_patterns": [
                "алмазн",
                "отрезн",
                "затвор дисковый",
                "тормозной диск",
            ],
            "required_any_tokens": [["диск", "blade"], ["дерев", "wood", "пильн", "saw"]],
        },
    },
    "diamond_blade": {
        "entity_types": ["diamond_blade"],
        "default_branches": ["алмазные диски"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "алмазный диск",
                "алмазные диски",
                "diamond blade",
                "diamond cutting disc",
            ],
            "negative_patterns": [
                "алмазная коронка",
                "затвор дисковый",
                "тормозной диск",
                "пильный диск по дереву",
            ],
            "required_any_tokens": [["алмаз", "diamond"], ["диск", "blade", "disc"]],
        },
    },
    "abrasive_cutting_disc": {
        "entity_types": ["abrasive_cutting_disc"],
        "default_branches": ["абразивные отрезные диски"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "абразивный отрезной диск",
                "абразивные отрезные диски",
                "абразивный отрезной круг",
                "круг абразивный отрезной",
                "отрезной диск",
                "отрезной круг",
                "cutting disc",
                "cut-off wheel",
            ],
            "negative_patterns": ["алмазн", "пильный", "тормозной диск", "затвор дисковый"],
            "required_any_tokens": [["отрезн", "cutting", "cut-off"], ["диск", "disc", "wheel"]],
        },
    },
    "hook_loop_sanding_disc": {
        "entity_types": ["hook_loop_sanding_disc"],
        "default_branches": ["круги шлифовальные на липучке"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "круг шлифовальный на липучке",
                "круги шлифовальные на липучке",
                "диск шлифовальный на липучке",
                "hook loop sanding disc",
                "sanding disc hook and loop",
            ],
            "negative_patterns": ["отрезн", "алмазн", "пильный", "полировальн", "лепестков"],
            "required_any_tokens": [["круг", "диск", "disc"], ["шлиф", "sanding"], ["липуч", "hook", "loop"]],
        },
    },
    "wire_brush_tool": {
        "entity_types": ["wire_brush_tool"],
        "default_branches": ["корщетки"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "корщетка",
                "корщетки",
                "крацовка",
                "щетка крацовка",
                "wire brush wheel",
                "cup brush",
            ],
            "negative_patterns": ["кисть", "paint brush", "зубная щетка", "щетка стеклоочистителя"],
            "required_any_tokens": [["корщет", "крацов", "wire brush", "cup brush"]],
        },
    },
    "printer_cartridge": {
        "entity_types": ["printer_cartridge"],
        "default_branches": ["картриджи для печатной техники"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "картридж для печатной техники",
                "картриджи для печатной техники",
                "картридж для принтера",
                "тонер картридж",
                "print cartridge",
                "printer cartridge",
                "toner cartridge",
            ],
            "negative_patterns": [
                "смеситель",
                "фильтр картридж",
                "картридж для фильтра",
                "чернильница",
                "печатная плата",
            ],
            "required_any_tokens": [["картридж", "cartridge"], ["принтер", "печат", "printer", "toner"]],
        },
    },
    "phillips_screwdriver": {
        "entity_types": ["phillips_screwdriver"],
        "default_branches": ["крестовые отвертки"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "крестовая отвертка",
                "отвертка крестовая",
                "крестовые отвертки",
                "отвертка phillips",
                "phillips screwdriver",
                "pozidriv screwdriver",
            ],
            "negative_patterns": [
                "шлицевая отвертка",
                "torx",
                "имбус",
                "битодержатель",
                "бита",
            ],
            "required_any_tokens": [["отвертк", "screwdriver"], ["крест", "phillips", "pozidriv", "pz", "ph"]],
        },
    },
    "slotted_screwdriver": {
        "entity_types": ["slotted_screwdriver"],
        "default_branches": ["шлицевые отвертки"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "шлицевая отвертка",
                "отвертка шлицевая",
                "шлицевые отвертки",
                "slotted screwdriver",
                "flat screwdriver",
            ],
            "negative_patterns": [
                "крестов",
                "phillips",
                "pozidriv",
                "torx",
                "имбус",
                "битодержатель",
                "бита",
            ],
            "required_any_tokens": [["отвертк", "screwdriver"], ["шлицев", "slotted", "flat"]],
        },
    },
    "screwdriver_set": {
        "entity_types": ["screwdriver_set"],
        "default_branches": ["наборы отверток"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "набор отверток",
                "наборы отверток",
                "screwdriver set",
                "set of screwdrivers",
            ],
            "negative_patterns": ["битодержатель", "набор бит", "torx bit", "phillips bit"],
            "required_any_tokens": [["набор", "set"], ["отвертк", "screwdriver"]],
        },
    },
    "cutting_pliers": {
        "entity_types": ["cutting_pliers"],
        "default_branches": ["бокорезы и кусачки"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "бокорез",
                "бокорезы",
                "кусачки",
                "диагональные кусачки",
                "side cutter",
                "diagonal cutter",
                "nipper",
            ],
            "negative_patterns": ["болторез", "клещи переставные", "клещи обжимные", "плоскогубцы"],
        },
    },
    "long_nose_pliers": {
        "entity_types": ["long_nose_pliers"],
        "default_branches": ["длинногубцы, утконосы и круглогубцы"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "длинногубцы",
                "утконосы",
                "круглогубцы",
                "needle nose pliers",
                "long nose pliers",
                "round nose pliers",
            ],
            "negative_patterns": ["бокорез", "кусачки", "болторез", "клещи обжимные", "клещи токоизмерительные"],
            "required_any_tokens": [["губц", "pliers", "утконос", "круглогуб"], ["длинн", "needle", "long", "round"]],
        },
    },
    "crimping_tool": {
        "entity_types": ["crimping_tool"],
        "default_branches": ["ручные пресс-клещи и кримперы"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "ручные пресс-клещи и кримперы",
                "пресс-клещи",
                "пресс клещи",
                "кримпер",
                "клещи для обжима",
                "обжимные клещи",
                "crimping tool",
                "crimping pliers",
            ],
            "negative_patterns": ["токоизмер", "clamp meter", "переставные", "болторез", "длинногубцы"],
            "required_any_tokens": [["клещ", "кримпер", "crimp"], ["обжим", "пресс", "гильз", "наконеч", "terminal"]],
        },
    },
    "clamp_tool": {
        "entity_types": ["clamp_tool"],
        "default_branches": ["струбцины"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "струбцина",
                "струбцины",
                "bar clamp",
                "f-clamp",
                "g-clamp",
                "clamping tool",
            ],
            "negative_patterns": ["clamp meter", "токоизмер", "хомут", "клемм"],
            "required_any_tokens": [["струбцин", "clamp"]],
        },
    },
    "manual_puller": {
        "entity_types": ["manual_puller"],
        "default_branches": ["съемники ручные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "съемник",
                "съемники ручные",
                "puller tool",
                "gear puller",
                "bearing puller",
            ],
            "negative_patterns": ["экстрактор", "домкрат", "подъемник", "магнитный съемник"],
            "required_any_tokens": [["съемник", "puller"]],
        },
    },
    "holiday_lighting": {
        "entity_types": ["holiday_lighting"],
        "default_branches": ["гирлянды"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 50,
            "positive_patterns": [
                "гирлянда",
                "гирлянды",
                "belt-light",
                "belt light",
                "бахрома",
                "дюралайт",
                "string light",
                "fairy light",
            ],
            "negative_patterns": [
                "кабель питания",
                "шнур питания",
                "удлинитель для гирлянды",
                "аксессуары для дюралайта",
                "аксессуары для белт-лайт",
            ],
            "required_any_tokens": [["гирлянд", "бахром", "дюралайт", "belt", "fairy"], ["led", "light", "свет", "нить", "занавес", "e27"]],
        },
    },
    "enclosure_panel": {
        "entity_types": ["enclosure_panel"],
        "default_branches": ["панели и платы монтажные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 50,
            "positive_patterns": [
                "панели и платы монтажные",
                "панель монтажная",
                "плата монтажная",
                "панель боковая",
                "панель задняя",
                "mounting panel",
                "mounting plate",
            ],
            "negative_patterns": [
                "печатная плата",
                "клеммный зажим для печатной платы",
                "pcb",
            ],
            "required_any_tokens": [["панел", "плат"], ["монтаж", "боков", "задн", "разделит"]],
        },
    },
    "pipe_connector": {
        "entity_types": ["pipe_connector"],
        "default_branches": ["соединители для труб"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 50,
            "positive_patterns": [
                "соединители для труб",
                "соединитель для труб",
                "муфта соединительная",
                "муфта вводная",
                "муфта гибкая труба-труба",
                "втулка соединительная",
                "pipe connector",
                "coupling for pipe",
            ],
            "negative_patterns": [
                "фитинг",
                "тройник",
                "угольник",
                "аксессуары для труб",
            ],
            "required_any_tokens": [["соедин", "муфт", "втулк", "connector", "coupling"], ["труб", "pipe"]],
        },
    },
    "pipe_clamp": {
        "entity_types": ["pipe_clamp"],
        "default_branches": ["хомуты для труб"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "хомуты для труб",
                "хомут для труб",
                "трубный хомут",
                "pipe clamp",
                "pipe hanger",
            ],
            "negative_patterns": ["кабельная стяжка", "хомут червячный", "хомут силовой", "strut clamp"],
            "required_any_tokens": [["хомут", "clamp", "hanger"], ["труб", "pipe"]],
        },
    },
    "sewer_fitting": {
        "entity_types": ["sewer_fitting"],
        "default_branches": ["фитинги для наружной канализации", "фитинги для внутренней канализации", "фитинги шумопоглощающие для канализации"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "фитинги для наружной канализации",
                "фитинги для внутренней канализации",
                "канализационный фитинг",
                "отвод для наружной канализации",
                "отвод для внутренней канализации",
                "тройник канализационный",
                "муфта канализационная",
                "ревизия канализационная",
                "крестовина канализационная",
                "переход канализационный",
                "фитинг шумопоглощающий для канализации",
                "фитинги шумопоглощающие для канализации",
                "sewer fitting",
                "drain fitting",
            ],
            "negative_patterns": ["pex", "pert", "пнд", "полипропилен", "латун", "трубный хомут", "сифон"],
            "required_any_tokens": [
                ["фитинг", "fitting", "отвод", "тройник", "муфта", "ревизи", "крестовин", "переход"],
                ["канализ", "sewer", "drain", "наружн", "внутрен"],
            ],
        },
    },
    "siphon": {
        "entity_types": ["siphon"],
        "default_branches": ["сифоны"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": ["сифон", "сифоны", "siphon", "bottle trap", "trap for sink"],
            "negative_patterns": ["фитинг", "канализационная труба", "трап", "дренажный клапан"],
            "required_any_tokens": [["сифон", "siphon", "trap"]],
        },
    },
    "lighting_support_foundation": {
        "entity_types": ["lighting_support_foundation"],
        "default_branches": ["закладные детали фундамента опор и мачт освещения"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 50,
            "positive_patterns": [
                "закладные детали фундамента опор и мачт освещения",
                "закладная деталь фундамента",
                "анкерный закладной элемент",
                "закладная анкерная",
                "foundation anchor for lighting pole",
            ],
            "negative_patterns": [
                "кабель",
                "светильник",
                "кронштейн светильника",
            ],
            "required_any_tokens": [["закладн", "анкер", "foundation"], ["опор", "мачт", "освещ", "pole"]],
        },
    },
    "door_window_hardware": {
        "entity_types": ["door_window_hardware"],
        "default_branches": ["фурнитура для замков, дверей и окон"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 49,
            "positive_patterns": [
                "фурнитура для замков, дверей и окон",
                "дверной глазок",
                "глазок дверной",
                "шарнир-петля",
                "броненакладка",
                "вертушка",
                "газовый лифт",
                "door hardware",
                "window hardware",
            ],
            "negative_patterns": [
                "дверной доводчик электромагнитный",
                "замок электромеханический",
            ],
            "required_any_tokens": [["двер", "окон", "замк", "hardware"], ["петл", "глазок", "накладк", "лифт", "вертуш"]],
        },
    },
    "auto_repair_tool": {
        "entity_types": ["auto_repair_tool"],
        "default_branches": ["специальный инструмент для авторемонта"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 49,
            "positive_patterns": [
                "специальный инструмент для авторемонта",
                "инструмент для авторемонта",
                "вакуумметр",
                "ареометр",
                "маслосборный",
                "противооткатный башмак",
                "авторемонтный инструмент",
            ],
            "negative_patterns": [
                "автомобильная лампа",
                "автомобильный кабель",
                "автоэлектрика",
            ],
            "required_any_tokens": [["авторемонт", "вакуумметр", "ареометр", "маслосбор", "башмак"], ["инструмент", "tool", "адаптер", "шприц", "ванна"]],
        },
    },
    "torx_bit": {
        "entity_types": ["torx_bit"],
        "default_branches": ["биты torx"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "бита torx",
                "биты torx",
                "torx bit",
                "бит torx",
            ],
            "negative_patterns": [
                "отвертка",
                "битодержатель",
                "шлицев",
                "крестов",
                "phillips",
                "pozidriv",
            ],
            "required_any_tokens": [["бит", "бита", "bit"], ["torx"]],
        },
    },
    "phillips_bit": {
        "entity_types": ["phillips_bit"],
        "default_branches": ["биты крест ph (phillips)"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "биты крест ph",
                "бита крест ph",
                "бита крест",
                "бита ph",
                "биты phillips",
                "phillips bit",
                "pozidriv bit",
                "бита pz",
            ],
            "negative_patterns": [
                "отвертка",
                "битодержатель",
                "torx",
                "шлицев",
                "имбус",
            ],
            "required_any_tokens": [["бит", "бита", "bit"], ["крест", "ph", "phillips", "pozidriv", "pz"]],
        },
    },
    "hex_bit": {
        "entity_types": ["hex_bit"],
        "default_branches": ["биты шестигранные hex"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "биты шестигранные hex",
                "бита шестигранная",
                "hex bit",
                "allen bit",
            ],
            "negative_patterns": ["отвертка", "битодержатель", "торкс", "torx", "phillips", "шлицев"],
            "required_any_tokens": [["бит", "бита", "bit"], ["шестигран", "hex", "allen"]],
        },
    },
    "self_tapping_screw": {
        "entity_types": ["self_tapping_screw"],
        "default_branches": ["саморезы универсальные", "саморезы гипсокартон-дерево", "саморезы гипсокартон-металл"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "саморез универсальный",
                "саморезы универсальные",
                "универсальный саморез",
                "универсальные саморезы",
                "саморез гипсокартон-дерево",
                "саморезы гипсокартон-дерево",
                "саморез гипсокартон-металл",
                "саморезы гипсокартон-металл",
                "саморез для гипсокартона",
                "drywall screw",
                "self-tapping screw",
                "self tapping screw",
            ],
            "negative_patterns": [
                "шуруповерт",
                "бита",
                "битодержатель",
                "анкер",
                "дюбель",
            ],
            "required_any_tokens": [["саморез", "screw"], ["универс", "tapping", "гипсокартон", "drywall"]],
        },
    },
    "drill_bit_metal": {
        "entity_types": ["drill_bit_metal"],
        "default_branches": ["сверла по металлу"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "сверло по металлу",
                "сверла по металлу",
                "drill bit",
                "metal drill",
                "hss drill",
            ],
            "negative_patterns": [
                "метчик",
                "плашк",
                "коронк",
                "зенкер",
                "держател",
                "tap",
                "thread tap",
            ],
            "required_any_tokens": [["сверл", "drill"], ["металл", "metal", "hss"]],
        },
    },
    "wood_drill_bit": {
        "entity_types": ["wood_drill_bit"],
        "default_branches": ["сверла по дереву"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "сверло по дереву",
                "сверла по дереву",
                "wood drill",
                "brad point",
                "auger bit",
            ],
            "negative_patterns": ["металл", "metal", "бетон", "concrete", "коронк", "бур", "sds", "метчик", "tap"],
            "required_any_tokens": [["сверл", "drill"], ["дерев", "wood", "brad", "auger"]],
        },
    },
    "masonry_drill_bit": {
        "entity_types": ["masonry_drill_bit"],
        "default_branches": ["буры sds-plus", "буры sds-max", "сверла по бетону"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "бур sds-plus",
                "бур sds plus",
                "бур sds-max",
                "бур sds max",
                "сверло по бетону",
                "сверла по бетону",
                "masonry drill",
                "concrete drill",
            ],
            "negative_patterns": [
                "коронк",
                "зубил",
                "металл",
                "metal",
                "hss",
                "дерев",
                "wood",
                "tap",
                "thread tap",
            ],
            "required_any_tokens": [["бур", "сверл", "drill"], ["sds", "бетон", "concrete", "masonry"]],
        },
    },
    "concrete_hole_saw": {
        "entity_types": ["concrete_hole_saw"],
        "default_branches": ["коронки по бетону"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "коронка по бетону",
                "коронки по бетону",
                "алмазная коронка по бетону",
                "diamond hole saw",
                "core bit",
            ],
            "negative_patterns": [
                "металл",
                "metal",
                "дерев",
                "wood",
                "bi-metal",
                "бур",
                "sds",
                "drill bit",
                "сверло",
            ],
            "required_any_tokens": [["коронк", "hole saw", "core bit"], ["бетон", "concrete", "алмаз"]],
        },
    },
    "hole_saw": {
        "entity_types": ["hole_saw"],
        "default_branches": ["коронки"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "коронка",
                "коронки",
                "кольцевая коронка",
                "удлинитель для коронок",
                "hole saw",
                "bi-metal hole saw",
            ],
            "negative_patterns": [
                "по бетону",
                "алмазная коронка по бетону",
                "sds",
                "бур",
                "сверло",
            ],
            "required_any_tokens": [["коронк", "hole saw"]],
        },
    },
    "countersink_tool": {
        "entity_types": ["countersink_tool"],
        "default_branches": ["зенкеры и зенковки"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "зенкер",
                "зенковка",
                "зенкеры и зенковки",
                "countersink",
                "countersink bit",
            ],
            "negative_patterns": ["сверло", "коронка", "развертка", "метчик"],
            "required_any_tokens": [["зенкер", "зенков", "countersink"]],
        },
    },
    "sds_chisel": {
        "entity_types": ["sds_chisel"],
        "default_branches": ["зубила sds-plus", "зубила sds-max"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "зубило sds-plus",
                "зубило sds plus",
                "зубило sds-max",
                "зубило sds max",
                "пика sds-plus",
                "пика sds plus",
                "пика sds-max",
                "пика sds max",
                "sds chisel",
                "sds point",
            ],
            "negative_patterns": [
                "бур",
                "сверл",
                "коронк",
                "drill",
                "hole saw",
                "core bit",
                "металл",
                "metal",
                "дерев",
                "wood",
            ],
            "required_any_tokens": [["зубил", "пик", "chisel", "point"], ["sds"]],
        },
    },
    "bearing": {
        "entity_types": ["bearing"],
        "default_branches": [
            "подшипники роликовые цилиндрические",
            "подшипники роликовые сферические",
            "подшипники роликовые конические",
            "подшипники шариковые радиальные",
            "подшипники шариковые радиально-упорные",
            "упорные подшипники",
            "самоустанавливающиеся шарикоподшипники",
            "игольчатые подшипники",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 53,
            "positive_patterns": [
                "подшип",
                "bearing",
                "роликов",
                "шариков",
                "радиальн",
                "цилиндрическ",
                "упорн",
                "самоустанавлива",
            ],
            "required_any_tokens": [["подшип", "bearing"]],
        },
    },
    "radiator": {
        "entity_types": ["radiator"],
        "default_branches": ["радиаторы стальные панельные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": ["радиатор", "radiator", "панельн"],
        },
    },
    "floor_convector": {
        "entity_types": ["floor_convector"],
        "default_branches": ["конвекторы внутрипольные", "конвекторы напольные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": ["конвектор", "convector", "внутрипол", "напольн"],
            "required_any_tokens": [["конвектор", "convector"], ["внутрипол", "напольн", "floor"]],
        },
    },
    "heating_mat": {
        "entity_types": ["heating_mat"],
        "default_branches": ["нагревательные маты"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "нагревательный мат",
                "нагревательные маты",
                "тёплый пол мат",
                "теплый пол мат",
                "heating mat",
            ],
            "negative_patterns": ["кабель нагревательный", "терморегулятор", "тепловентилятор", "коврик"],
            "required_any_tokens": [["мат", "mat"], ["нагрев", "тёплый пол", "теплый пол", "heating"]],
        },
    },
    "storage_water_heater": {
        "entity_types": ["storage_water_heater"],
        "default_branches": ["водонагреватели электрические накопительные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "водонагреватель накопительный",
                "водонагреватели электрические накопительные",
                "электрический накопительный водонагреватель",
                "бойлер",
                "storage water heater",
            ],
            "negative_patterns": ["проточный", "газовый", "теплообменник"],
            "required_any_tokens": [["водонагрев", "бойлер", "water heater"], ["накоп", "storage", "electric"]],
        },
    },
    "electric_convector": {
        "entity_types": ["electric_convector"],
        "default_branches": ["конвекторы электрические"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "конвекторы электрические",
                "электрический конвектор",
                "электроконвектор",
                "electric convector",
                "electric heater convector",
            ],
            "negative_patterns": ["внутрипольный", "напольный", "floor convector", "радиатор"],
            "required_any_tokens": [["конвектор", "convector"], ["электр", "электро", "electric"]],
        },
    },
    "floor_heating_manifold": {
        "entity_types": ["floor_heating_manifold"],
        "default_branches": ["коллекторные группы для теплого пола"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "коллекторные группы для теплого пола",
                "коллектор для теплого пола",
                "группа для теплого пола",
                "floor heating manifold",
                "underfloor manifold",
            ],
            "negative_patterns": ["коллекторный шкаф", "водоснабжение", "манометр"],
            "required_any_tokens": [["коллектор", "manifold"], ["тепл", "пола", "floor", "underfloor"]],
        },
    },
    "heat_shrink": {
        "entity_types": ["heat_shrink"],
        "default_branches": ["термоусаживаемые изделия"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": ["термоусаж", "термоусад", "heat shrink", "shrink tube"],
        },
    },
    "pipe_insulation": {
        "entity_types": ["pipe_insulation"],
        "default_branches": ["изоляция из вспененного каучука трубная", "изоляция из вспененного полиэтилена трубная"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "изоляция из вспененного каучука трубная",
                "изоляция из вспененного полиэтилена трубная",
                "трубная изоляция",
                "вспененного каучука",
                "вспененного полиэтилена",
                "pipe insulation",
                "rubber pipe insulation",
                "polyethylene pipe insulation",
            ],
            "negative_patterns": ["кабель", "электро", "самоклеящ", "изоляционная лента"],
            "required_any_tokens": [["изоляц", "insulation", "каучук", "rubber", "полиэтилен", "polyethylene"], ["труб", "pipe"]],
        },
    },
    "transformer": {
        "entity_types": ["transformer"],
        "default_branches": ["трансформаторы напряжения понижающие низковольтные", "трансформаторы тока низковольтные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": ["трансформатор", "transformer", "понижающ", "низковольтн", "трансформатор тока"],
        },
    },
    "ups": {
        "entity_types": ["ups"],
        "default_branches": ["источники бесперебойного питания (ибп)"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 55,
            "positive_patterns": ["источник бесперебойного питания", "ибп", "ups", "line interactive", "online ups", "uninterruptible"],
        },
    },
    "pressure_gauge": {
        "entity_types": ["pressure_gauge"],
        "default_branches": ["манометры"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": ["манометр", "pressure gauge", "gauge pressure"],
        },
    },
    "multimeter": {
        "entity_types": ["multimeter"],
        "default_branches": ["мультиметры"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": ["мультиметр", "multimeter", "тестер", "tester"],
            "negative_patterns": [
                "кабельный тестер",
                "тестер кабеля",
                "cable tester",
                "network tester",
                "lan tester",
                "rj45",
                "ethernet",
                "сканер",
                "клещи",
                "clamp meter",
                "current clamp",
            ],
            "required_any_tokens": [
                ["мультиметр", "multimeter", "тестер", "tester"],
                ["цифров", "измер", "вольт", "напряж", "ампер", "ток", "ом", "сопротивл", "digital"],
            ],
        },
    },
    "clamp_meter": {
        "entity_types": ["clamp_meter"],
        "default_branches": ["клещи токоизмерительные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "клещи токоизмерительные",
                "токоизмерительные клещи",
                "токовые клещи",
                "clamp meter",
                "current clamp",
            ],
            "negative_patterns": [
                "обжимные клещи",
                "клещи обжимные",
                "клещи переставные",
                "клещи монтажные",
                "клещи для снятия изоляции",
                "press tool",
                "crimping",
            ],
            "required_any_tokens": [
                ["клещи", "clamp"],
                ["токоизмер", "токов", "ток", "current", "amp"],
            ],
        },
    },
    "voltage_indicator": {
        "entity_types": ["voltage_indicator"],
        "default_branches": ["индикаторы напряжения"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "индикатор напряжения",
                "индикаторы напряжения",
                "указатель напряжения",
                "пробник напряжения",
                "voltage indicator",
                "voltage tester",
            ],
            "negative_patterns": [
                "светосигнальн",
                "сигнальн ламп",
                "лампа сигнальн",
                "световой индикатор",
                "pilot light",
                "indicator lamp",
                "мультиметр",
                "multimeter",
            ],
            "required_any_tokens": [
                ["индикатор", "указатель", "пробник", "tester", "indicator"],
                ["напряж", "voltage", "220", "380"],
            ],
        },
    },
    "pressure_regulator": {
        "entity_types": ["pressure_regulator"],
        "default_branches": ["регулятор давления"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": ["регулятор давления", "pressure regulator"],
        },
    },
    "faucet": {
        "entity_types": ["faucet"],
        "default_branches": ["смесители для ванны и душа", "смесители для мойки"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "смеситель",
                "смесители для ванны и душа",
                "смесители для мойки",
                "faucet",
                "mixer tap",
            ],
            "negative_patterns": ["картридж", "ремкомплект", "душевая стойка", "лейка"],
            "required_any_tokens": [["смесител", "faucet", "mixer"], ["ванн", "душ", "мойк", "sink", "bath"]],
        },
    },
    "voltage_stabilizer": {
        "entity_types": ["voltage_stabilizer"],
        "default_branches": ["стабилизаторы напряжения"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "стабилизатор напряжения",
                "стабилизаторы напряжения",
                "voltage stabilizer",
                "avr",
            ],
            "negative_patterns": [
                "источник бесперебойного питания",
                "ибп",
                "ups",
                "реле контроля напряжения",
                "амортизатор",
            ],
            "required_any_tokens": [["стабилиз", "stabilizer", "avr"], ["напряж", "voltage", "220", "230", "380"]],
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
            "positive_patterns": ["шкаф"],
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
                "скоб",
                "однолапк",
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
                    "holder": ["держател", "хомут", "скоб", "однолапк", "holder"],
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
    "cable_conduit": {
        "entity_types": ["cable_conduit"],
        "default_branches": ["металлорукав с изоляцией", "гофрированные трубы для прокладки кабеля", "трубы жесткие двустенные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 57,
            "positive_patterns": [
                "металлорукав",
                "металлорукав с изоляцией",
                "гофрированная труба",
                "гофрированные трубы",
                "труба для прокладки кабеля",
                "трубы жесткие двустенные",
                "жесткая двустенная труба",
                "cable conduit",
                "corrugated conduit",
                "metal conduit",
            ],
            "negative_patterns": [
                "кабель-канал",
                "кабель канал",
                "перфорированный короб",
                "рукав пожарный",
                "шланг",
            ],
            "required_any_tokens": [
                ["металлорукав", "гофр", "двустен", "conduit"],
                ["изоляц", "труб", "прокладк", "corrugated", "жестк"],
            ],
        },
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
    "fuse": {
        "entity_types": ["fuse"],
        "default_branches": ["плавкие предохранители"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 56,
            "positive_patterns": ["предохранител", "плавк", "fuse"],
        },
    },
    "push_button": {
        "entity_types": ["push_button"],
        "default_branches": ["кнопки", "кнопочные посты"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 56,
            "positive_patterns": ["кнопк", "push button", "кнопочн пост"],
            "negative_patterns": ["клавиатур", "кнопочн телефон", "кнопк мыш"],
        },
    },
    "terminal_block": {
        "entity_types": ["terminal_block"],
        "default_branches": [
            "клеммные блоки зажимов на din-рейку",
            "клеммы на din-рейку",
            "проходные клеммы на din-рейку",
            "миниклеммы на din-рейку",
            "клеммные зажимы для печатных плат",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 56,
            "positive_patterns": [
                "клеммный блок",
                "клеммные блоки",
                "клеммник",
                "клемма наборная",
                "проходная клемма",
                "миниклем",
                "клеммы на din",
                "клеммный зажим для печатной платы",
                "клеммные зажимы для печатных плат",
                "pcb terminal",
                "terminal block pcb",
                "terminal block",
                "din rail",
            ],
            "negative_patterns": ["заглушк", "маркиров", "аккумулятор", "акб"],
        },
    },
    "wire_ferrule": {
        "entity_types": ["wire_ferrule"],
        "default_branches": ["штыревые втулочные наконечники (ншв и ншви)"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 56,
            "positive_patterns": [
                "штыревые втулочные наконечники",
                "втулочный наконечник",
                "втулочные наконечники",
                "ншв",
                "ншви",
                "ferrule",
                "bootlace ferrule",
            ],
            "negative_patterns": ["клеммный блок", "клеммник", "din рейк", "din-рейк", "terminal block", "клещ", "клещи", "пресс", "обжим", "кримпер"],
            "required_any_tokens": [
                ["ншв", "ншви", "наконеч"],
                ["втулоч", "штырев", "ferrule"],
            ],
        },
    },
    "power_terminal_lug": {
        "entity_types": ["power_terminal_lug"],
        "default_branches": ["силовые медные луженые наконечники (тмл)"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 56,
            "positive_patterns": [
                "силовые медные луженые наконечники",
                "наконечники тмл",
                "наконечник тмл",
                "луженый кабельный наконечник",
                "cable lug",
                "terminal lug",
            ],
            "negative_patterns": ["ншв", "ншви", "втулоч", "клеммный блок", "клеммник", "клещи", "обжим"],
            "required_any_tokens": [["наконеч", "lug"], ["тмл", "кабельн", "лужен", "terminal", "cable"]],
        },
    },
    "terminal_block_accessory": {
        "entity_types": ["terminal_block_accessory"],
        "default_branches": ["перемычки для клемм на din-рейку", "маркеры для клемм на din-рейку"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 56,
            "positive_patterns": [
                "перемычки для клемм на din-рейку",
                "маркеры для клемм на din-рейку",
                "перемычка для клемм",
                "маркер для клемм",
                "terminal block jumper",
                "terminal block marker",
            ],
            "negative_patterns": ["клеммный блок", "клеммник", "проходная клемма", "миниклемма", "аккумулятор", "акб"],
            "required_any_tokens": [["перемычк", "маркер", "jumper", "marker"], ["клемм", "terminal", "din"]],
        },
    },
    "signal_indicator": {
        "entity_types": ["signal_indicator"],
        "default_branches": ["светосигнальная арматура"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 55,
            "positive_patterns": [
                "светосигнальн",
                "сигнальн ламп",
                "лампа сигнальн",
                "световой индикатор",
                "индикатор световой",
                "pilot light",
                "indicator lamp",
            ],
            "negative_patterns": ["табло", "знак безопасности", "светильник"],
        },
    },
    "electrical_tape": {
        "entity_types": ["electrical_tape"],
        "default_branches": ["изолента"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": ["изолента", "изоляционная лента", "лента изоляционная", "electrical tape", "insulating tape"],
            "negative_patterns": ["теплоизоляц", "вспененн", "фум", "скотч", "малярная лента"],
        },
    },
    "power_accessory": {
        "entity_types": ["power_accessory"],
        "default_branches": ["удлинители, сетевые фильтры, переходники, штепсельные вилки"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 61,
            "positive_patterns": [
                "удлинител",
                "сетевой фильтр",
                "штепсельн",
                "вилка",
                "силовой переходник",
                "power strip",
                "extension cord",
                "travel adapter",
            ],
            "negative_patterns": [
                "переходники для кабельных лотков",
                "keystone",
                "rj45",
                "патч",
                "адаптер для din",
            ],
            "required_any_tokens": [["удлинител", "сетев", "штепсель", "вилка", "power strip", "extension", "переходник"], ["220", "230", "250", "евро", "schuko", "силов", "сетев"]],
        },
    },
    "ip_camera": {
        "entity_types": ["ip_camera"],
        "default_branches": ["ip-видеокамеры"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 56,
            "positive_patterns": ["ip-видеокамеры", "ip видеокамера", "ip camera", "network camera", "видеокамера ip"],
            "negative_patterns": ["муляж", "кронштейн", "объектив", "регистратор"],
            "required_any_tokens": [["ip", "network"], ["камер", "camera", "видеокамер"]],
        },
    },
    "jack": {
        "entity_types": ["jack"],
        "default_branches": ["домкраты"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": ["домкрат", "домкраты", "hydraulic jack", "bottle jack", "floor jack"],
            "negative_patterns": ["стойка", "тележка", "подкатная тележка", "опора"],
            "required_any_tokens": [["домкрат", "jack"], ["гидравл", "подкат", "бутылоч", "floor", "bottle"]],
        },
    },
    "utility_knife": {
        "entity_types": ["utility_knife"],
        "default_branches": ["ножи строительные", "лезвия для ножей"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "ножи строительные",
                "нож строительный",
                "лезвия для ножей",
                "utility knife",
                "snap off knife",
                "blade for utility knife",
            ],
            "negative_patterns": ["кухонный", "охотничий", "канцелярские ножницы", "скальпель"],
            "required_any_tokens": [["нож", "лезви", "knife", "blade"], ["строит", "utility", "snap", "segment"]],
        },
    },
    "trimmer_line": {
        "entity_types": ["trimmer_line"],
        "default_branches": ["леска для триммеров"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 52,
            "positive_patterns": [
                "леска для триммеров",
                "леска для триммера",
                "триммерная леска",
                "trimmer line",
                "nylon line",
            ],
            "negative_patterns": ["кабель", "провод", "wire", "fishing", "рыболов"],
            "required_any_tokens": [["леск", "line"], ["триммер", "trimmer", "nylon"]],
        },
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
    "frequency_drive": {
        "entity_types": ["frequency_drive"],
        "default_branches": [
            "преобразователи частоты, приводы",
            "аксессуары для преобразователей частоты",
            "сервисные позиции (запасные части) для преобразователей частоты",
        ],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 58,
            "positive_patterns": [
                "преобразователь частоты",
                "частотный преобразователь",
                "частотный привод",
                "frequency drive",
                "variable frequency drive",
                "vfd",
                "инверторный привод",
                "аксессуары для преобразователей частоты",
                "сервисные позиции для преобразователей частоты",
                "запасные части для преобразователей частоты",
            ],
            "negative_patterns": [
                "плавного пуска",
                "soft starter",
                "интерфейс",
                "преобразователь интерфейса",
                "rs-485",
                "реле",
                "модуль",
            ],
            "required_any_tokens": [["частот", "frequency", "vfd", "инвертор"], ["преобразоват", "привод", "drive"]],
        },
    },
    "electric_motor": {
        "entity_types": ["electric_motor"],
        "default_branches": ["электродвигатели общепромышленные"],
        "retrieval_mode": "branch_limited",
        "strictness": "semi_strict",
        "audited": True,
        "weak_match_policy": "reject_in_exact",
        "classifier": {
            "priority": 56,
            "positive_patterns": [
                "электродвигатель",
                "электродвигатели",
                "electric motor",
                "асинхронный двигатель",
                "трехфазный двигатель",
                "однофазный двигатель",
            ],
            "negative_patterns": [
                "преобразователь частоты",
                "частотный преобразователь",
                "частотный привод",
                "soft starter",
                "плавного пуска",
            ],
        },
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
            "families": ["tray_sheet"],
        },
        "lighting": {
            "patterns": ["светильник", "светодиод", "треков", "дсо", "дсп", "дпо", "дку"],
            "families": ["lighting_fixture", "light_signage"],
        },
        "safety_signage": {
            "patterns": ["табло", "выход", "exit", "эвакуац", "знак безопасности", "пиктограмм"],
            "families": ["light_signage", "safety_sign"],
        },
        "software": {
            "patterns": ["программ", "лиценз", "software", "monitoring"],
            "families": ["security_software"],
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
            "patterns": ["держател", "хомут", "скоб", "анкер", "болт", "шуруп", "шпильк", "дюбел", "гайк", "шайб"],
            "families": [],
        },
        "electrical_protection": {
            "patterns": ["выключател", "автоматическ", "автомат", "optidin", "bm63"],
            "families": ["breaker"],
        },
        "surge_protector": {
            "patterns": [
                "ограничитель импульсного перенапряжения",
                "ограничители импульсного перенапряжения",
                "перенапряжен",
                "узип",
                "spd",
                "surge protector",
                "surge arrester",
            ],
            "families": ["surge_protector"],
        },
        "fuse": {
            "patterns": ["предохранител", "плавк", "fuse"],
            "families": ["fuse"],
        },
        "push_button": {
            "patterns": ["кнопк", "push button", "кнопочн пост"],
            "families": ["push_button"],
        },
        "terminal_block": {
            "patterns": [
                "клеммный блок",
                "клеммные блоки",
                "клеммник",
                "клемма наборная",
                "проходная клемма",
                "миниклем",
                "клеммы на din",
                "клеммный зажим для печатной платы",
                "клеммные зажимы для печатных плат",
                "pcb terminal",
                "terminal block pcb",
                "terminal block",
                "din rail",
            ],
            "families": ["terminal_block"],
        },
        "pipe_clamp": {
            "patterns": ["хомуты для труб", "хомут для труб", "трубный хомут", "pipe clamp", "pipe hanger"],
            "families": ["pipe_clamp"],
        },
        "sewer_fitting": {
            "patterns": ["фитинги для наружной канализации", "фитинги для внутренней канализации", "фитинг шумопоглощающий для канализации", "фитинги шумопоглощающие для канализации", "канализационный фитинг", "sewer fitting", "drain fitting"],
            "families": ["sewer_fitting"],
        },
        "siphon": {
            "patterns": ["сифон", "сифоны", "siphon", "bottle trap", "trap for sink"],
            "families": ["siphon"],
        },
        "faucet": {
            "patterns": ["смеситель", "смесители для ванны и душа", "смесители для мойки", "faucet", "mixer tap"],
            "families": ["faucet"],
        },
        "wire_ferrule": {
            "patterns": [
                "штыревые втулочные наконечники",
                "втулочный наконечник",
                "втулочные наконечники",
                "ншв",
                "ншви",
                "ferrule",
                "bootlace ferrule",
            ],
            "families": ["wire_ferrule"],
        },
        "signal_indicator": {
            "patterns": ["светосигнальн", "сигнальн ламп", "лампа сигнальн", "световой индикатор", "индикатор световой", "pilot light", "indicator lamp"],
            "families": ["signal_indicator"],
        },
        "electrical_tape": {
            "patterns": ["изолента", "изоляционная лента", "лента изоляционная", "electrical tape", "insulating tape"],
            "families": ["electrical_tape"],
        },
        "reactive_power_compensator": {
            "patterns": ["укрм", "компенсация реактивной мощности", "реактивной мощности", "capacitor bank", "power factor correction"],
            "families": ["reactive_power_compensator"],
        },
        "heating_mat": {
            "patterns": ["нагревательный мат", "нагревательные маты", "тёплый пол мат", "теплый пол мат", "heating mat"],
            "families": ["heating_mat"],
        },
        "electric_convector": {
            "patterns": ["конвектор электрический", "конвекторы электрические", "electric convector", "electric heater convector"],
            "families": ["electric_convector"],
        },
        "floor_heating_manifold": {
            "patterns": ["коллекторная группа для теплого пола", "коллекторные группы для теплого пола", "floor heating manifold", "underfloor heating manifold"],
            "families": ["floor_heating_manifold"],
        },
        "pipe_insulation": {
            "patterns": ["изоляция из вспененного каучука трубная", "изоляция из вспененного полиэтилена трубная", "трубная изоляция", "pipe insulation", "rubber pipe insulation", "polyethylene pipe insulation"],
            "families": ["pipe_insulation"],
        },
        "grounding": {
            "patterns": ["заземл", "шина", "стержень"],
            "families": ["ground_bar"],
        },
        "neutral_busbar": {
            "patterns": ["нулевая шина", "нулевые шины", "шина нулевая", "neutral bus", "n busbar"],
            "families": ["neutral_busbar"],
        },
        "industrial_valve": {
            "patterns": [
                "затвор",
                "кран шаров",
                "краны шаров",
                "butterfly valve",
                "ball valve",
                "клапан электромагнитн",
                "соленоид",
                "клапан регулирующ",
                "клапаны регулирующ",
                "вентиль",
                "клапан запорн",
                "клапан обратн",
                "задвижк",
            ],
            "families": ["industrial_valve"],
        },
        "industrial_pump": {
            "patterns": ["насос", "pump", "центробежный насос", "вертикальный насос"],
            "families": ["industrial_pump"],
        },
        "thread_tap": {
            "patterns": ["метчик", "метчики", "tap", "thread tap", "машинно-ручной метчик"],
            "families": ["thread_tap"],
        },
        "thread_die": {
            "patterns": ["плашка", "плашки", "thread die", "round die"],
            "families": ["thread_die"],
        },
        "thread_gauge": {
            "patterns": ["резьбомер", "резьбомеры", "thread gauge", "screw pitch gauge", "шаблон резьбы"],
            "families": ["thread_gauge"],
        },
        "threading_tool_set": {
            "patterns": ["наборы резьбонарезного инструмента", "набор резьбонарезного инструмента", "threading tool set", "tap and die set"],
            "families": ["threading_tool_set"],
        },
        "bore_gauge": {
            "patterns": ["нутромер", "нутромеры", "bore gauge", "inside gauge"],
            "families": ["bore_gauge"],
        },
        "socket_head_set": {
            "patterns": ["торцевая головка", "торцевые головки", "торцевых головок", "набор торцевых головок", "набор головок", "socket set", "socket wrench"],
            "families": ["socket_head_set"],
        },
        "drive_belt": {
            "patterns": ["ремень клиновой", "ремни клиновые", "ремень узкоклиновой", "ремни узкоклиновые", "v-belt", "drive belt"],
            "families": ["drive_belt"],
        },
        "brass_threaded_fitting": {
            "patterns": ["фитинг резьбовой латунный", "фитинги резьбовые латунные", "латунный фитинг", "brass fitting", "threaded fitting"],
            "families": ["brass_threaded_fitting"],
        },
        "polypropylene_fitting": {
            "patterns": ["фитинги для полипропиленовых труб", "фитинг полипропиленовый", "полипропиленовый фитинг", "ppr fitting", "pp-r fitting"],
            "families": ["polypropylene_fitting"],
        },
        "axial_pex_fitting": {
            "patterns": ["фитинги аксиальные для pex", "фитинги аксиальные для pert", "фитинг аксиальный", "аксиальный фитинг", "pex fitting", "pert fitting"],
            "families": ["axial_pex_fitting"],
        },
        "pnd_compression_fitting": {
            "patterns": ["фитинги компрессионные для пнд труб пластиковые", "фитинг компрессионный пнд", "компрессионный фитинг пнд", "фитинг пнд компрессионный", "pnd compression fitting", "pe compression fitting"],
            "families": ["pnd_compression_fitting"],
        },
        "metal_turning_tool": {
            "patterns": ["резец по металлу", "резцы по металлу", "токарный резец", "lathe tool", "turning tool"],
            "families": ["metal_turning_tool"],
        },
        "workwear": {
            "patterns": ["костюм летний", "костюмы летние", "костюм утепленный", "костюмы утепленные", "костюмы сварщика", "костюм сварщика", "полукомбинезон рабочий", "брюки рабочие", "куртка утепленная", "куртки утепленные", "workwear suit", "workwear jacket", "workwear overall"],
            "families": ["workwear"],
        },
        "safety_footwear": {
            "patterns": ["ботинки рабочие", "полуботинки рабочие", "защитная обувь", "work boots", "safety shoes"],
            "families": ["safety_footwear"],
        },
        "protective_gloves": {
            "patterns": ["антипорезные перчатки", "защитные перчатки", "перчатки защитные", "перчатки защитные антипорезные", "рабочие перчатки", "protective gloves", "cut resistant gloves"],
            "families": ["protective_gloves"],
        },
        "safety_glasses": {
            "patterns": ["защитные очки", "очки защитные", "safety glasses", "protective eyewear"],
            "families": ["safety_glasses"],
        },
        "protective_helmet": {
            "patterns": ["каска", "каски", "защитная каска", "строительная каска", "safety helmet", "hard hat"],
            "families": ["protective_helmet"],
        },
        "combination_wrench": {
            "patterns": ["комбинированный ключ", "ключ комбинированный", "комбинированные ключи", "рожково накидной ключ", "ключ рожково накидной", "combination wrench", "combination spanner"],
            "families": ["combination_wrench"],
        },
        "open_end_wrench": {
            "patterns": ["рожковый ключ", "рожковые ключи", "ключ рожковый", "open end wrench", "open-end wrench", "open end spanner"],
            "families": ["open_end_wrench"],
        },
        "ring_wrench": {
            "patterns": ["накидной ключ", "накидные ключи", "ключ накидной", "ring wrench", "box wrench", "box-end wrench"],
            "families": ["ring_wrench"],
        },
        "adjustable_wrench": {
            "patterns": ["разводной ключ", "разводные ключи", "ключ разводной", "adjustable wrench", "crescent wrench"],
            "families": ["adjustable_wrench"],
        },
        "hex_bit": {
            "patterns": ["биты шестигранные", "биты шестигранные hex", "бита шестигранная", "hex bit", "allen bit"],
            "families": ["hex_bit"],
        },
        "hex_key": {
            "patterns": ["имбусовый ключ", "имбусовые ключи", "ключ имбусовый", "ключ шестигранный", "шестигранные ключи", "hex key", "allen key"],
            "families": ["hex_key"],
        },
        "caliper": {
            "patterns": ["штангенциркуль", "штангенциркули", "vernier caliper", "digital caliper"],
            "families": ["caliper"],
        },
        "screwdriver_set": {
            "patterns": ["набор отверток", "наборы отверток", "screwdriver set", "set of screwdrivers"],
            "families": ["screwdriver_set"],
        },
        "paint_roller": {
            "patterns": ["малярный валик", "валик малярный", "валики", "paint roller", "roller cover"],
            "families": ["paint_roller"],
        },
        "milling_cutter": {
            "patterns": ["фреза", "фрезы для станков", "концевая фреза", "кольцевая фреза", "milling cutter"],
            "families": ["milling_cutter"],
        },
        "router_bit": {
            "patterns": ["фрезы и наборы фрез для ручных фрезеров", "фреза для ручного фрезера", "набор фрез для ручного фрезера", "router bit", "router cutter"],
            "families": ["router_bit"],
        },
        "manual_puller": {
            "patterns": ["съемник", "съемники ручные", "puller tool", "gear puller", "bearing puller"],
            "families": ["manual_puller"],
        },
        "wood_saw_blade": {
            "patterns": ["пильный диск по дереву", "пильные диски по дереву", "диск по дереву", "saw blade wood", "wood saw blade"],
            "families": ["wood_saw_blade"],
        },
        "diamond_blade": {
            "patterns": ["алмазный диск", "алмазные диски", "diamond blade", "diamond cutting disc"],
            "families": ["diamond_blade"],
        },
        "hook_loop_sanding_disc": {
            "patterns": ["круг шлифовальный на липучке", "круги шлифовальные на липучке", "диск шлифовальный на липучке", "hook loop sanding disc", "sanding disc hook and loop"],
            "families": ["hook_loop_sanding_disc"],
        },
        "wire_brush_tool": {
            "patterns": ["корщетка", "корщетки", "крацовка", "щетка крацовка", "wire brush wheel", "cup brush"],
            "families": ["wire_brush_tool"],
        },
        "printer_cartridge": {
            "patterns": ["картридж для печатной техники", "картриджи для печатной техники", "картридж для принтера", "тонер картридж", "print cartridge", "printer cartridge", "toner cartridge"],
            "families": ["printer_cartridge"],
        },
        "phillips_screwdriver": {
            "patterns": ["крестовая отвертка", "отвертка крестовая", "крестовые отвертки", "отвертка phillips", "phillips screwdriver", "pozidriv screwdriver"],
            "families": ["phillips_screwdriver"],
        },
        "slotted_screwdriver": {
            "patterns": ["шлицевая отвертка", "отвертка шлицевая", "шлицевые отвертки", "slotted screwdriver", "flat screwdriver"],
            "families": ["slotted_screwdriver"],
        },
        "cutting_pliers": {
            "patterns": ["бокорез", "бокорезы", "кусачки", "диагональные кусачки", "side cutter", "diagonal cutter", "nipper"],
            "families": ["cutting_pliers"],
        },
        "torx_bit": {
            "patterns": ["бита torx", "биты torx", "torx bit", "бит torx"],
            "families": ["torx_bit"],
        },
        "phillips_bit": {
            "patterns": ["биты крест ph", "бита крест ph", "бита крест", "бита ph", "биты phillips", "phillips bit", "pozidriv bit", "бита pz"],
            "families": ["phillips_bit"],
        },
        "self_tapping_screw": {
            "patterns": ["саморез универсальный", "саморезы универсальные", "универсальный саморез", "универсальные саморезы", "саморез гипсокартон-дерево", "саморезы гипсокартон-дерево", "саморез гипсокартон-металл", "саморезы гипсокартон-металл", "саморез для гипсокартона", "drywall screw", "self-tapping screw", "self tapping screw"],
            "families": ["self_tapping_screw"],
        },
        "drill_bit_metal": {
            "patterns": ["сверло по металлу", "сверла по металлу", "drill bit", "metal drill", "hss drill"],
            "families": ["drill_bit_metal"],
        },
        "wood_drill_bit": {
            "patterns": ["сверло по дереву", "сверла по дереву", "wood drill", "brad point", "auger bit"],
            "families": ["wood_drill_bit"],
        },
        "masonry_drill_bit": {
            "patterns": [
                "бур sds-plus",
                "бур sds plus",
                "бур sds-max",
                "бур sds max",
                "сверло по бетону",
                "сверла по бетону",
                "masonry drill",
                "concrete drill",
            ],
            "families": ["masonry_drill_bit"],
        },
        "concrete_hole_saw": {
            "patterns": [
                "коронка по бетону",
                "коронки по бетону",
                "алмазная коронка по бетону",
                "diamond hole saw",
                "core bit",
            ],
            "families": ["concrete_hole_saw"],
        },
        "hole_saw": {
            "patterns": ["коронка", "коронки", "кольцевая коронка", "удлинитель для коронок", "hole saw", "bi-metal hole saw"],
            "families": ["hole_saw"],
        },
        "countersink_tool": {
            "patterns": ["зенкер", "зенковка", "зенкеры и зенковки", "countersink"],
            "families": ["countersink_tool"],
        },
        "sds_chisel": {
            "patterns": [
                "зубило sds-plus",
                "зубило sds plus",
                "зубило sds-max",
                "зубило sds max",
                "пика sds-plus",
                "пика sds plus",
                "пика sds-max",
                "пика sds max",
                "sds chisel",
                "sds point",
            ],
            "families": ["sds_chisel"],
        },
        "bearing": {
            "patterns": [
                "подшип",
                "bearing",
                "роликов",
                "шариков",
                "радиальн",
                "цилиндрическ",
                "упорн",
                "самоустанавлива",
            ],
            "families": ["bearing"],
        },
        "radiator": {
            "patterns": ["радиатор", "radiator", "панельн"],
            "families": ["radiator"],
        },
        "floor_convector": {
            "patterns": ["конвектор", "convector", "внутрипол", "напольн"],
            "families": ["floor_convector"],
        },
        "storage_water_heater": {
            "patterns": ["водонагреватель накопительный", "водонагреватели электрические накопительные", "электрический накопительный водонагреватель", "бойлер", "storage water heater"],
            "families": ["storage_water_heater"],
        },
        "heat_shrink": {
            "patterns": ["термоусаж", "термоусад", "heat shrink", "shrink tube"],
            "families": ["heat_shrink"],
        },
        "pipe_insulation": {
            "patterns": ["изоляция из вспененного каучука трубная", "трубная изоляция", "вспененного каучука", "pipe insulation", "rubber pipe insulation"],
            "families": ["pipe_insulation"],
        },
        "transformer": {
            "patterns": ["трансформатор", "transformer", "понижающ", "низковольтн", "трансформатор тока"],
            "families": ["transformer"],
        },
        "ups": {
            "patterns": ["источник бесперебойного питания", "ибп", "ups", "line interactive", "online ups", "uninterruptible"],
            "families": ["ups"],
        },
        "pressure_gauge": {
            "patterns": ["манометр", "pressure gauge", "gauge pressure"],
            "families": ["pressure_gauge"],
        },
        "multimeter": {
            "patterns": ["мультиметр", "multimeter", "тестер", "tester", "измеритель напряжения", "измеритель тока"],
            "families": ["multimeter"],
        },
        "clamp_meter": {
            "patterns": ["клещи токоизмерительные", "токоизмерительные клещи", "токовые клещи", "clamp meter", "current clamp"],
            "families": ["clamp_meter"],
        },
        "voltage_indicator": {
            "patterns": ["индикатор напряжения", "индикаторы напряжения", "указатель напряжения", "пробник напряжения", "voltage indicator", "voltage tester"],
            "families": ["voltage_indicator"],
        },
        "pressure_regulator": {
            "patterns": ["регулятор давления", "pressure regulator"],
            "families": ["pressure_regulator"],
        },
        "voltage_stabilizer": {
            "patterns": ["стабилизатор напряжения", "стабилизаторы напряжения", "voltage stabilizer", "avr"],
            "families": ["voltage_stabilizer"],
        },
        "frequency_drive": {
            "patterns": ["преобразователь частоты", "частотный преобразователь", "частотный привод", "аксессуары для преобразователей частоты", "сервисные позиции для преобразователей частоты", "запасные части для преобразователей частоты", "frequency drive", "variable frequency drive", "vfd"],
            "families": ["frequency_drive"],
        },
        "electric_motor": {
            "patterns": ["электродвигатель", "электродвигатели", "electric motor", "асинхронный двигатель", "трехфазный двигатель", "однофазный двигатель"],
            "families": ["electric_motor"],
        },
        "power_accessory": {
            "patterns": ["удлинител", "сетевой фильтр", "штепсельн", "вилка", "power strip", "extension cord", "силовой переходник"],
            "families": ["power_accessory"],
        },
        "distribution_enclosure": {
            "patterns": ["щит распредел", "силовой щит", "щит с монтажной панелью", "щит этажный", "щиток", "электрощит", "корпус распредел", "корпус учетно", "корпус для модульных устройств", "корпус мультимедиа", "корпуса щитов монтажных металлических", "бокс модульный", "встраиваемый щит", "навесной щит", "щрв", "щрн", "щурв", "щурн", "щмп"],
            "families": ["distribution_enclosure"],
        },
        "switchboard_accessory": {
            "patterns": [
                "вспомогательные щитовые аксессуары",
                "дополнительные двери",
                "козырек защитный",
                "панель монтажная",
                "окно герметичное",
                "петли для корпусов",
                "комплект для навески",
                "щитовые аксессуары",
            ],
            "families": ["switchboard_accessory"],
        },
        "cable_conduit": {
            "patterns": ["металлорукав", "гофрированная труба", "гофрированные трубы", "прокладки кабеля", "трубы жесткие двустенные", "жесткая двустенная труба", "cable conduit", "corrugated conduit"],
            "families": ["cable_conduit"],
        },
        "jack": {
            "patterns": ["домкрат", "домкраты", "hydraulic jack", "bottle jack", "floor jack"],
            "families": ["jack"],
        },
        "terminal_block_accessory": {
            "patterns": ["перемычки для клемм на din-рейку", "перемычка для клемм на din-рейку", "terminal block accessory", "terminal block jumper", "din rail terminal accessory"],
            "families": ["terminal_block_accessory"],
        },
        "power_terminal_lug": {
            "patterns": ["силовые медные луженые наконечники", "тмл", "наконечник тмл", "power terminal lug", "copper cable lug"],
            "families": ["power_terminal_lug"],
        },
        "ip_camera": {
            "patterns": ["ip-видеокамеры", "ip видеокамера", "ip camera", "network camera"],
            "families": ["ip_camera"],
        },
        "utility_knife": {
            "patterns": ["нож строительный", "ножи строительные", "utility knife", "snap-off knife"],
            "families": ["utility_knife"],
        },
        "trimmer_line": {
            "patterns": ["леска для триммеров", "леска для триммера", "триммерная леска", "trimmer line", "nylon line"],
            "families": ["trimmer_line"],
        },
        "rack_accessory": {
            "patterns": ["полк", "рельс", "направля", "щеточ", "заглуш"],
            "families": ["rack_accessory_strict", "rack_shelf", "rack_rail"],
        },
        "cable_channel": {
            "patterns": ["кабель-канал", "кабель канал", "перфокороб", "перфорированный короб"],
            "families": ["cable_channel"],
        },
        "cable": {
            "patterns": ["кабель", "провод", "ввг", "кгв", "кипэ", "сгпм"],
            "families": ["cable", "wire", "coax", "bulk_twisted_pair", "iec_power_cable"],
        },
        "fire_alarm": {
            "patterns": ["извещател", "оповещател", "опс", "орион про", "контрольно-пуск", "с2000", "пульт", "приемно-контрольн"],
            "families": [
                "fire_detector",
                "fire_annunciator",
                "fire_alarm_device",
                "security_interface_device",
                "security_control_panel",
                "security_module_device",
                "security_control_device",
                "security_software",
                "power_backup",
                "firestop_material",
            ],
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
    "rack_tray_holder_short_article_resolver": {
        "auto_accept_sources": [
            "article_series_local",
        ],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_holder_short_article_match",
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
        "auto_accept_sources": [
            "article_series_local",
        ],
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
    "telecom_optical_cross_populated_1u_24_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_optical_cross_populated_1u_24_match",
    },
    "telecom_optical_cross_populated_1u_36_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "local_tree+gemini",
            "candidate_tiebreaker_gemini",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_telecom_optical_cross_populated_1u_36_match",
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
    "rack_tray_short_article_tray_100_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_short_article_tray_100_match",
    },
    "rack_tray_short_article_tray_200_resolver": {
        "auto_accept_sources": [],
        "review_sources": [
            "compatible_local_fallback",
            "assembly_possible_local_fallback",
        ],
        "compatible_default_decision": "review",
        "default_review_reason": "review_rack_tray_short_article_tray_200_match",
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
        "box",
        "box_accessory",
        "distribution_enclosure",
        "switchboard_accessory",
        "reactive_power_compensator",
        "cable_conduit",
        "cable_channel",
        "cable",
        "coax",
        "floor_box",
        "fastener",
        "surge_protector",
        "fuse",
        "push_button",
        "terminal_block",
        "wire_ferrule",
        "signal_indicator",
        "electrical_tape",
        "power_accessory",
        "ground_bar",
        "light_signage",
        "safety_sign",
        "industrial_valve",
        "industrial_pump",
        "neutral_busbar",
        "thread_tap",
        "thread_die",
        "thread_gauge",
        "threading_tool_set",
        "socket_head_set",
        "drive_belt",
        "brass_threaded_fitting",
        "polypropylene_fitting",
        "axial_pex_fitting",
        "pnd_compression_fitting",
        "metal_turning_tool",
        "milling_cutter",
        "router_bit",
        "workwear",
        "safety_footwear",
        "protective_gloves",
        "safety_glasses",
        "protective_helmet",
        "crimping_tool",
        "paint_brush",
        "micrometer",
        "bore_gauge",
        "long_nose_pliers",
        "clamp_tool",
        "manual_puller",
        "holiday_lighting",
        "enclosure_panel",
        "pipe_connector",
        "pipe_clamp",
        "sewer_fitting",
        "siphon",
        "faucet",
        "floor_heating_manifold",
        "lighting_support_foundation",
        "door_window_hardware",
        "auto_repair_tool",
        "spirit_level",
        "tape_measure",
        "file_tool",
        "abrasive_cutting_disc",
        "hook_loop_sanding_disc",
        "combination_wrench",
        "open_end_wrench",
        "ring_wrench",
        "adjustable_wrench",
        "screwdriver_set",
        "hex_bit",
        "hex_key",
        "caliper",
        "paint_roller",
        "wood_saw_blade",
        "diamond_blade",
        "wire_brush_tool",
        "printer_cartridge",
        "phillips_screwdriver",
        "slotted_screwdriver",
        "cutting_pliers",
        "torx_bit",
        "phillips_bit",
        "self_tapping_screw",
        "drill_bit_metal",
        "wood_drill_bit",
        "masonry_drill_bit",
        "concrete_hole_saw",
        "hole_saw",
        "countersink_tool",
        "sds_chisel",
        "bearing",
        "radiator",
        "floor_convector",
        "electric_convector",
        "heating_mat",
        "storage_water_heater",
        "heat_shrink",
        "pipe_insulation",
        "transformer",
        "ups",
        "pressure_gauge",
        "multimeter",
        "clamp_meter",
        "voltage_indicator",
        "pressure_regulator",
        "voltage_stabilizer",
        "frequency_drive",
        "electric_motor",
        "terminal_block_accessory",
        "power_terminal_lug",
        "ip_camera",
        "jack",
        "utility_knife",
        "trimmer_line",
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
        "switch_wiring",
        "wire",
    ],
    "family_groups": {
        "box": "box",
        "box_accessory": "box_accessory",
        "distribution_enclosure": "distribution_enclosure",
        "switchboard_accessory": "switchboard_accessory",
        "reactive_power_compensator": "reactive_power_compensator",
        "cable_conduit": "cable_conduit",
        "cable_channel": "cable_channel",
        "bearing": "bearing",
        "radiator": "radiator",
        "floor_convector": "floor_convector",
        "electric_convector": "electric_convector",
        "heat_shrink": "heat_shrink",
        "transformer": "transformer",
        "ups": "ups",
        "pressure_gauge": "pressure_gauge",
        "multimeter": "multimeter",
        "clamp_meter": "clamp_meter",
        "voltage_indicator": "voltage_indicator",
        "pressure_regulator": "pressure_regulator",
        "voltage_stabilizer": "voltage_stabilizer",
        "frequency_drive": "frequency_drive",
        "electric_motor": "electric_motor",
        "light_signage": "signage",
        "safety_sign": "signage",
        "industrial_pump": "industrial_pump",
        "neutral_busbar": "neutral_busbar",
        "thread_tap": "thread_tap",
        "thread_die": "thread_die",
        "thread_gauge": "thread_gauge",
        "threading_tool_set": "threading_tool_set",
        "socket_head_set": "socket_head_set",
        "drive_belt": "drive_belt",
        "brass_threaded_fitting": "brass_threaded_fitting",
        "polypropylene_fitting": "polypropylene_fitting",
        "axial_pex_fitting": "axial_pex_fitting",
        "pnd_compression_fitting": "pnd_compression_fitting",
        "metal_turning_tool": "metal_turning_tool",
        "milling_cutter": "milling_cutter",
        "router_bit": "router_bit",
        "workwear": "workwear",
        "safety_footwear": "safety_footwear",
        "protective_gloves": "protective_gloves",
        "safety_glasses": "safety_glasses",
        "protective_helmet": "protective_helmet",
        "crimping_tool": "crimping_tool",
        "paint_brush": "paint_brush",
        "micrometer": "micrometer",
        "bore_gauge": "bore_gauge",
        "long_nose_pliers": "long_nose_pliers",
        "clamp_tool": "clamp_tool",
        "manual_puller": "manual_puller",
        "holiday_lighting": "holiday_lighting",
        "enclosure_panel": "enclosure_panel",
        "pipe_connector": "pipe_connector",
        "pipe_clamp": "pipe_clamp",
        "sewer_fitting": "sewer_fitting",
        "siphon": "siphon",
        "faucet": "faucet",
        "floor_heating_manifold": "floor_heating_manifold",
        "lighting_support_foundation": "lighting_support_foundation",
        "door_window_hardware": "door_window_hardware",
        "auto_repair_tool": "auto_repair_tool",
        "spirit_level": "spirit_level",
        "tape_measure": "tape_measure",
        "file_tool": "file_tool",
        "abrasive_cutting_disc": "abrasive_cutting_disc",
        "hook_loop_sanding_disc": "hook_loop_sanding_disc",
        "combination_wrench": "combination_wrench",
        "open_end_wrench": "open_end_wrench",
        "ring_wrench": "ring_wrench",
        "adjustable_wrench": "adjustable_wrench",
        "screwdriver_set": "screwdriver_set",
        "hex_bit": "hex_bit",
        "hex_key": "hex_key",
        "caliper": "caliper",
        "paint_roller": "paint_roller",
        "wood_saw_blade": "wood_saw_blade",
        "diamond_blade": "diamond_blade",
        "wire_brush_tool": "wire_brush_tool",
        "printer_cartridge": "printer_cartridge",
        "phillips_screwdriver": "phillips_screwdriver",
        "slotted_screwdriver": "slotted_screwdriver",
        "cutting_pliers": "cutting_pliers",
        "torx_bit": "torx_bit",
        "phillips_bit": "phillips_bit",
        "self_tapping_screw": "self_tapping_screw",
        "drill_bit_metal": "drill_bit_metal",
        "wood_drill_bit": "wood_drill_bit",
        "masonry_drill_bit": "masonry_drill_bit",
        "concrete_hole_saw": "concrete_hole_saw",
        "hole_saw": "hole_saw",
        "countersink_tool": "countersink_tool",
        "sds_chisel": "sds_chisel",
        "heating_mat": "heating_mat",
        "storage_water_heater": "storage_water_heater",
        "pipe_insulation": "pipe_insulation",
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
        "fastener": "fastener",
        "surge_protector": "surge_protector",
        "ground_bar": "grounding",
        "industrial_valve": "industrial_valve",
        "floor_box": "floor_box",
        "fuse": "fuse",
        "push_button": "push_button",
        "terminal_block": "terminal_block",
        "wire_ferrule": "wire_ferrule",
        "signal_indicator": "signal_indicator",
        "electrical_tape": "electrical_tape",
        "power_accessory": "power_accessory",
        "terminal_block_accessory": "terminal_block_accessory",
        "power_terminal_lug": "power_terminal_lug",
        "ip_camera": "ip_camera",
        "jack": "jack",
        "utility_knife": "utility_knife",
        "trimmer_line": "trimmer_line",
        "rack": "rack",
        "sensor": "sensor",
        "switch_wiring": "switch_wiring",
    },
    "family_group_labels": {
        "box": "box",
        "box_accessory": "box_accessory",
        "distribution_enclosure": "distribution enclosure",
        "switchboard_accessory": "switchboard accessory",
        "reactive_power_compensator": "reactive power compensator",
        "cable_conduit": "cable conduit",
        "cable_channel": "cable_channel",
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
        "bearing": "bearing",
        "radiator": "radiator",
        "floor_convector": "floor convector",
        "electric_convector": "electric convector",
        "heat_shrink": "heat shrink",
        "transformer": "transformer",
        "ups": "ups",
        "pressure_gauge": "pressure gauge",
        "multimeter": "multimeter",
        "clamp_meter": "clamp meter",
        "voltage_indicator": "voltage indicator",
        "pressure_regulator": "pressure regulator",
        "voltage_stabilizer": "voltage stabilizer",
        "frequency_drive": "frequency drive",
        "electric_motor": "electric motor",
        "signage": "signage",
        "industrial_pump": "industrial pump",
        "neutral_busbar": "neutral busbar",
        "thread_tap": "thread tap",
        "thread_die": "thread die",
        "thread_gauge": "thread gauge",
        "threading_tool_set": "threading tool set",
        "socket_head_set": "socket head set",
        "drive_belt": "drive belt",
        "brass_threaded_fitting": "brass threaded fitting",
        "polypropylene_fitting": "polypropylene fitting",
        "axial_pex_fitting": "axial PEX fitting",
        "pnd_compression_fitting": "PND compression fitting",
        "metal_turning_tool": "metal turning tool",
        "milling_cutter": "milling cutter",
        "router_bit": "router bit",
        "workwear": "workwear",
        "safety_footwear": "safety footwear",
        "protective_gloves": "protective gloves",
        "safety_glasses": "safety glasses",
        "protective_helmet": "protective helmet",
        "crimping_tool": "crimping tool",
        "paint_brush": "paint brush",
        "micrometer": "micrometer",
        "bore_gauge": "bore gauge",
        "long_nose_pliers": "long nose pliers",
        "clamp_tool": "clamp tool",
        "manual_puller": "manual puller",
        "holiday_lighting": "holiday lighting",
        "enclosure_panel": "enclosure panel",
        "pipe_connector": "pipe connector",
        "pipe_clamp": "pipe clamp",
        "sewer_fitting": "sewer fitting",
        "siphon": "siphon",
        "faucet": "faucet",
        "floor_heating_manifold": "floor heating manifold",
        "lighting_support_foundation": "lighting support foundation",
        "door_window_hardware": "door/window hardware",
        "auto_repair_tool": "auto repair tool",
        "spirit_level": "spirit level",
        "tape_measure": "tape measure",
        "file_tool": "file tool",
        "abrasive_cutting_disc": "abrasive cutting disc",
        "hook_loop_sanding_disc": "hook loop sanding disc",
        "combination_wrench": "combination wrench",
        "open_end_wrench": "open end wrench",
        "ring_wrench": "ring wrench",
        "adjustable_wrench": "adjustable wrench",
        "screwdriver_set": "screwdriver set",
        "hex_bit": "hex bit",
        "hex_key": "hex key",
        "caliper": "caliper",
        "paint_roller": "paint roller",
        "wood_saw_blade": "wood saw blade",
        "diamond_blade": "diamond blade",
        "wire_brush_tool": "wire brush tool",
        "printer_cartridge": "printer cartridge",
        "phillips_screwdriver": "phillips screwdriver",
        "slotted_screwdriver": "slotted screwdriver",
        "cutting_pliers": "cutting pliers",
        "torx_bit": "torx bit",
        "phillips_bit": "phillips bit",
        "self_tapping_screw": "self tapping screw",
        "drill_bit_metal": "drill bit metal",
        "wood_drill_bit": "wood drill bit",
        "masonry_drill_bit": "masonry drill bit",
        "concrete_hole_saw": "concrete hole saw",
        "hole_saw": "hole saw",
        "countersink_tool": "countersink tool",
        "sds_chisel": "sds chisel",
        "heating_mat": "heating mat",
        "storage_water_heater": "storage water heater",
        "pipe_insulation": "pipe insulation",
        "fastener": "fastener",
        "surge_protector": "surge protector",
        "grounding": "grounding",
        "industrial_valve": "industrial valve",
        "floor_box": "floor_box",
        "fuse": "fuse",
        "push_button": "push_button",
        "terminal_block": "terminal_block",
        "wire_ferrule": "wire ferrule",
        "signal_indicator": "signal indicator",
        "electrical_tape": "electrical tape",
        "power_accessory": "power accessory",
        "terminal_block_accessory": "terminal block accessory",
        "power_terminal_lug": "power terminal lug",
        "ip_camera": "ip camera",
        "jack": "jack",
        "utility_knife": "utility knife",
        "trimmer_line": "trimmer line",
        "rack": "rack",
        "sensor": "sensor",
        "switch_wiring": "switch_wiring",
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


def build_taxonomy_tree_snapshot(rules: Mapping[str, Any] | None) -> Dict[str, Any]:
    prepared_rules = dict(rules or {})
    groups = audit_family_groups(prepared_rules)
    labels = audit_family_group_labels(prepared_rules)
    audited = audited_families(prepared_rules)

    families_payload: Dict[str, Dict[str, Any]] = {}
    branch_to_families: Dict[str, list[str]] = {}

    for family_name in sorted(family_registry(prepared_rules).keys()):
        default_branches = family_default_branches(family_name, prepared_rules)
        entity_types = sorted(family_entity_types(family_name, prepared_rules))
        spec = family_spec_for(family_name, prepared_rules)
        group_name = groups.get(family_name, "")
        families_payload[family_name] = {
            "entity_types": entity_types,
            "default_branches": default_branches,
            "retrieval_mode": family_retrieval_mode(family_name, prepared_rules),
            "strictness": family_strictness(family_name, prepared_rules),
            "weak_match_policy": family_weak_match_policy(family_name, prepared_rules),
            "same_family_gate": family_requires_same_family_gate(family_name, prepared_rules),
            "audited": family_name in audited,
            "audit_group": group_name,
            "audit_group_label": labels.get(group_name, group_name),
        }
        for branch_path in default_branches:
            normalized_branch = clean_registry_text(branch_path).lower()
            if not normalized_branch or normalized_branch == "прочее":
                continue
            branch_to_families.setdefault(normalized_branch, []).append(family_name)

    branches_payload = {
        branch_path: {"families": sorted(set(families))}
        for branch_path, families in sorted(branch_to_families.items())
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "family_count": len(families_payload),
        "branch_count": len(branches_payload),
        "families": families_payload,
        "branches": branches_payload,
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
