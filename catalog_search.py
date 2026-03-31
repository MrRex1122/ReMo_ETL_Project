from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import pandas as pd

try:
    import duckdb

    DUCKDB_AVAILABLE = True
except ImportError:
    duckdb = None
    DUCKDB_AVAILABLE = False

from catalog_merge import get_catalog_readiness, get_merged_catalog_path
from catalog_schema import (
    CANONICAL_NAME_COLUMN,
    CANONICAL_PRICE_COLUMN,
    CANONICAL_ARTICLE_COLUMN,
    canonicalize_catalog_columns,
)
from taxonomy_registry import (
    classify_entity_type_from_registry,
    entity_family_for_type,
    family_default_branches as registry_family_default_branches,
    load_registry_taxonomy_rules,
)

logger = logging.getLogger(__name__)

SEARCH_CATALOG_CSV_FILENAME = "price_clean_search.csv"
SEARCH_CATALOG_DUCKDB_FILENAME = "price_clean_search.duckdb"
SEARCH_CATALOG_FILENAME = SEARCH_CATALOG_CSV_FILENAME
SEARCH_CATALOG_TABLE = "search_catalog"
SEARCH_BUILD_DEFAULT_CHUNKSIZE = 50000
BRANCH_PATH_SEPARATOR = " > "
DEFAULT_TAXONOMY_RULES_PATH = Path(__file__).with_name("taxonomy_rules.json")
GROUP_TOKEN_STOPWORDS = {
    "и",
    "в",
    "во",
    "на",
    "для",
    "с",
    "со",
    "по",
    "из",
    "шт",
    "мм",
    "см",
    "м",
    "к",
    "за",
    "u",
    "the",
    "zero",
}
TERM_NORMALIZATION_ALIASES = {
    "patch cord": "патч корд",
    "patch-cord": "патч корд",
    "patchcord": "патч корд",
    "патч-корд": "патч корд",
    "патчкорд": "патч корд",
    "шнур коммутационный": "патч корд",
    "коммутационный шнур": "патч корд",
    "zero-u": "zero u",
    '19"': "19 inch",
    "19''": "19 inch",
}
DEFAULT_KEYWORD_ROUTES = [
    {"patterns": ["pdu", "блок розеток"], "path": ["телеком", "питание", "pdu"], "weight": 4.0},
    {"patterns": ["zero u"], "path": ["телеком", "питание", "pdu", "zero u"], "weight": 5.0},
    {"patterns": ["патч панель", "патч-панель"], "path": ["телеком", "коммутация", "патч панели"], "weight": 4.5},
    {"patterns": ["патч корд", "patch cord"], "path": ["телеком", "кабели", "патч корды"], "weight": 4.5},
    {"patterns": ["органайзер"], "path": ["телеком", "аксессуары", "кабельные органайзеры"], "weight": 4.0},
    {"patterns": ["шкаф", "стойк"], "path": ["телеком", "шкафы"], "weight": 3.2},
    {"patterns": ["датчик"], "path": ["автоматика", "датчики"], "weight": 3.2},
    {"patterns": ["кабель", "utp", "ftp"], "path": ["электрика", "кабели"], "weight": 2.8},
    {"patterns": ["провод"], "path": ["электрика", "провода"], "weight": 2.8},
    {"patterns": ["автомат"], "path": ["электрика", "автоматы"], "weight": 3.5},
    {"patterns": ["розетка"], "path": ["электрика", "розетки"], "weight": 3.0},
    {"patterns": ["светильник"], "path": ["свет", "светильники"], "weight": 3.0},
]
SEARCH_BASE_COLUMNS = [
    CANONICAL_NAME_COLUMN,
    CANONICAL_ARTICLE_COLUMN,
    CANONICAL_PRICE_COLUMN,
    "Название класса",
    "Код класса",
    "Тип изделия",
    "Тип исполнения кабельного изделия",
    "Производитель",
]
SEARCH_DERIVED_COLUMNS = [
    "search_branch_path",
    "search_branch_leaf",
    "search_normalized_name",
    "search_tokens_json",
    "search_entity_type",
    "search_item_markers_json",
]


@dataclass
class SearchCatalogReadiness:
    merged_path: Path
    search_path: Path
    search_format: str
    search_csv_path: Path
    search_duckdb_path: Path
    state: str
    reason: str | None
    merged_mtime: float | None
    search_mtime: float | None


def get_search_catalog_csv_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_CATALOG_CSV_FILENAME


def get_search_catalog_duckdb_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_CATALOG_DUCKDB_FILENAME


def get_search_catalog_path(clean_dir: Path) -> Path:
    preferred = os.getenv("REMO_SEARCH_STORAGE_FORMAT", "").strip().lower()
    if preferred == "csv":
        return get_search_catalog_csv_path(clean_dir)
    if preferred == "duckdb" and DUCKDB_AVAILABLE:
        return get_search_catalog_duckdb_path(clean_dir)
    if DUCKDB_AVAILABLE:
        return get_search_catalog_duckdb_path(clean_dir)
    return get_search_catalog_csv_path(clean_dir)


def is_search_catalog_path(path: str | Path) -> bool:
    candidate = Path(str(path))
    return candidate.name in {SEARCH_CATALOG_CSV_FILENAME, SEARCH_CATALOG_DUCKDB_FILENAME}


def load_search_taxonomy_rules() -> Dict[str, Any]:
    path_raw = os.getenv("REMO_TAXONOMY_RULES_PATH")
    path = Path(path_raw) if path_raw else DEFAULT_TAXONOMY_RULES_PATH
    try:
        return load_registry_taxonomy_rules(path=path)
    except Exception as exc:
        logger.warning("⚠️ Failed to load search taxonomy rules from %s: %s", path, exc)
        return load_registry_taxonomy_rules()


def clean_text_value(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def normalize_branch_path(segments: Iterable[str]) -> str:
    cleaned: list[str] = []
    for segment in segments:
        text = clean_text_value(segment)
        if not text:
            continue
        text = text.replace("|", " ").replace("/", " ").replace("\\", " ")
        text = re.sub(r"\s+", " ", text).strip().lower()
        if text:
            cleaned.append(text)
    return BRANCH_PATH_SEPARATOR.join(cleaned)


def normalize_query_terms(text: str, synonyms: Mapping[str, str] | None = None) -> str:
    normalized = str(text or "").lower()
    replacements = dict(TERM_NORMALIZATION_ALIASES)
    if synonyms:
        replacements.update({str(key): str(value) for key, value in synonyms.items()})
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized.replace("ё", "е")


def normalize_text(text: str, synonyms: Mapping[str, str] | None = None) -> str:
    normalized = normalize_query_terms(text, synonyms=synonyms)
    normalized = re.sub(r"[^\w\dа-я]+", " ", normalized, flags=re.IGNORECASE)
    return " ".join(normalized.split())


def tokenize(
    text: str,
    synonyms: Mapping[str, str] | None = None,
    stopwords: set[str] | None = None,
) -> List[str]:
    normalized = normalize_text(text, synonyms=synonyms)
    tokens = re.findall(r"[a-zа-я0-9]+", normalized, flags=re.IGNORECASE)
    blocked = stopwords or GROUP_TOKEN_STOPWORDS
    return [token for token in tokens if len(token) >= 2 and token not in blocked]


def _detect_connector_pair(normalized: str) -> str:
    connector_patterns = (
        ("c13-c14", (r"\bc13\b", r"\bc14\b")),
        ("c19-c20", (r"\bc19\b", r"\bc20\b")),
        ("lc-lc", (r"\blc\b", r"\blc\b")),
        ("sc-sc", (r"\bsc\b", r"\bsc\b")),
        ("lc-sc", (r"\blc\b", r"\bsc\b")),
        ("rj45-rj45", (r"\brj[\s-]?45\b", r"\brj[\s-]?45\b")),
    )
    for value, patterns in connector_patterns:
        if all(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns):
            return value
    return ""


def _has_airflow_blanking_signal(normalized: str) -> bool:
    return (
        ("поток" in normalized and "воздух" in normalized)
        or "airflow" in normalized
        or "blanking panel" in normalized
        or "свободных юнит" in normalized
    )


def _looks_like_ats_sts_device_precise(normalized: str) -> bool:
    static_switch_markers = ("\u0441\u0442\u0430\u0442\u0438\u0447\u0435\u0441\u043a", "\u043f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0430\u0442\u0435\u043b")
    if all(marker in normalized for marker in static_switch_markers):
        return True
    if "switch" in normalized and any(marker in normalized for marker in ("ats", "sts", "transfer")):
        return True
    if not re.search(r"\b(?:ats|sts)\b", normalized, flags=re.IGNORECASE):
        return False
    connector_noise_markers = (
        "\u043a\u043e\u043d\u043d\u0435\u043a\u0442\u043e\u0440",
        "pin",
        "rgb",
        "mono",
        "germ",
        "hip-",
        "arl-",
    )
    if any(marker in normalized for marker in connector_noise_markers):
        return False
    power_context_markers = (
        "\u043f\u0435\u0440\u0435\u043a\u043b\u044e\u0447",
        "\u0432\u0432\u043e\u0434 \u0440\u0435\u0437\u0435\u0440\u0432\u0430",
        "bypass",
        "\u0431\u0430\u0439\u043f\u0430\u0441",
        "transfer",
        "power",
        "pdu",
        "\u043d\u043e\u043c\u0438\u043d\u0430\u043b",
        "16a",
        "30a",
        "32a",
    )
    return any(marker in normalized for marker in power_context_markers)


def _has_iec_power_cable_context(normalized: str) -> bool:
    connector_pattern = r"(?<![A-Za-z0-9])(?:iec320|c13|c14|c19|c20)(?![A-Za-z0-9])"
    if not re.search(connector_pattern, normalized, flags=re.IGNORECASE):
        return False
    cable_context_markers = (
        "\u043a\u0430\u0431\u0435\u043b\u044c",
        "\u0448\u043d\u0443\u0440",
        "\u0441\u043e\u0435\u0434\u0438\u043d\u0438\u0442\u0435\u043b\u044c\u043d",
        "cord",
        "power cord",
    )
    return any(marker in normalized for marker in cable_context_markers)


def _looks_like_primary_cable_product(normalized: str) -> bool:
    primary_prefixes = (
        "\u043a\u0430\u0431\u0435\u043b\u044c",
        "\u0448\u043d\u0443\u0440",
        "\u0441\u043e\u0435\u0434\u0438\u043d\u0438\u0442\u0435\u043b\u044c\u043d",
        "power cord",
        "cord",
    )
    return normalized.startswith(primary_prefixes)


def _looks_like_pdu_device(normalized: str) -> bool:
    has_pdu_token = "pdu" in normalized
    has_socket_strip = "\u0431\u043b\u043e\u043a \u0440\u043e\u0437\u0435\u0442\u043e\u043a" in normalized
    if not has_pdu_token and not has_socket_strip:
        return False
    if "without pdu" in normalized or "\u0431\u0435\u0437 pdu" in normalized:
        return False
    fastener_noise_markers = (
        "\u0434\u044e\u0431\u0435\u043b",
        "\u0448\u0443\u0440\u0443\u043f",
        "\u043d\u0435\u0439\u043b\u043e\u043d",
        "zn ",
        "sormat",
        "fischer",
    )
    if any(marker in normalized for marker in fastener_noise_markers):
        return False
    non_pdu_power_markers = (
        "\u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a \u0431\u0435\u0441\u043f\u0435\u0440\u0435\u0431\u043e\u0439\u043d",
        "\u0431\u0435\u0441\u043f\u0435\u0440\u0435\u0431\u043e\u0439\u043d",
        "\u0431\u0430\u0442\u0430\u0440\u0435\u0439\u043d",
        "\u0437\u0430\u0440\u044f\u0434\u043d",
        "ups",
        "online",
        "line interactive",
        "keor",
        "info pdu",
    )
    if any(marker in normalized for marker in non_pdu_power_markers):
        return False
    if "bypass" in normalized or "\u0431\u0430\u0439\u043f\u0430\u0441" in normalized:
        return False
    if _looks_like_primary_cable_product(normalized) and any(
        marker in normalized for marker in ("iec320", "c13", "c14", "c19", "c20")
    ):
        return False
    if has_pdu_token:
        return True
    rack_pdu_markers = (
        "zero u",
        "schuko",
        "c13",
        "c19",
        "c20",
        "\u0431\u0430\u0439\u043f\u0430\u0441",
        "bypass",
        "\u0438\u0431\u043f",
        "ups",
        "\u0448\u043a\u0430\u0444",
        "\u0441\u0442\u043e\u0439\u043a",
        "\u0432\u0435\u0440\u0442\u0438\u043a\u0430\u043b\u044c\u043d",
        "\u0433\u043e\u0440\u0438\u0437\u043e\u043d\u0442\u0430\u043b\u044c\u043d",
        "19",
    )
    return any(marker in normalized for marker in rack_pdu_markers)


def _looks_like_patch_panel(normalized: str, phrase_normalized: str) -> bool:
    if "патч панел" in phrase_normalized or "patch panel" in phrase_normalized:
        return True
    if "панел" not in normalized or "коммутац" not in normalized:
        return False
    telecom_markers = (
        "порт",
        "rj45",
        "rj 45",
        "cat",
        "категор",
        "ethernet",
        "keystone",
        "кейстоун",
        "krone",
    )
    return any(marker in normalized for marker in telecom_markers)


def _looks_like_patch_cord(normalized: str, phrase_normalized: str) -> bool:
    if "патч корд" not in phrase_normalized and "patch cord" not in phrase_normalized:
        return False
    telecom_markers = (
        "rj45",
        "rj 45",
        "8p8c",
        "ethernet",
        "lan",
        "utp",
        "ftp",
        "sftp",
        "cat",
        "категор",
        "коммутацион",
        "витая пара",
    )
    if any(marker in normalized for marker in telecom_markers):
        return True
    connector_pair = _detect_connector_pair(normalized)
    return connector_pair == "rj45-rj45"


def _detect_port_count(normalized: str) -> str:
    direct_match = re.search(
        r"\b(\d{1,3})\s*(?:Ð¿Ð¾Ñ€Ñ‚|Ð¿Ð¾Ñ€Ñ‚Ð°|Ð¿Ð¾Ñ€Ñ‚Ð¾Ð²|Ð¿Ð¾ÑÑ‚|Ð¿Ð¾ÑÑ‚Ð°|Ð¿Ð¾ÑÑ‚Ð¾Ð²|Ð¼ÐµÑÑ‚|Ð¼ÐµÑÑ‚Ð°|Ð¼ÐµÑÑ‚Ð½Ð°Ñ)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if direct_match:
        return direct_match.group(1)

    word_patterns = (
        (r"\bÐ¾Ð´Ð½(?:Ð¾Ð³Ð¾|Ð°|Ð¾|Ð¾Ð¼ÐµÑÑ‚Ð½\w*)\s*(?:Ð¿Ð¾Ñ€Ñ‚|Ð¿Ð¾Ñ€Ñ‚Ð°|Ð¿Ð¾Ñ€Ñ‚Ð¾Ð²)?", "1"),
        (r"\bÐ´Ð²(?:Ð°|ÑƒÑ…|ÑƒÑ…Ð¿Ð¾Ñ€Ñ‚\w*|ÑƒÑ…Ð¼ÐµÑÑ‚\w*)\s*(?:Ð¿Ð¾Ñ€Ñ‚|Ð¿Ð¾Ñ€Ñ‚Ð°|Ð¿Ð¾Ñ€Ñ‚Ð¾Ð²)?", "2"),
        (r"\bÑ‚Ñ€(?:Ð¸|ÐµÑ…)\s*(?:Ð¿Ð¾Ñ€Ñ‚|Ð¿Ð¾Ñ€Ñ‚Ð°|Ð¿Ð¾Ñ€Ñ‚Ð¾Ð²)?", "3"),
        (r"\bÑ‡ÐµÑ‚Ñ‹Ñ€(?:Ðµ|ÐµÑ…)\s*(?:Ð¿Ð¾Ñ€Ñ‚|Ð¿Ð¾Ñ€Ñ‚Ð°|Ð¿Ð¾Ñ€Ñ‚Ð¾Ð²)?", "4"),
    )
    for pattern, value in word_patterns:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return value
    return ""


def _detect_port_count_precise(normalized: str) -> str:
    direct_match = re.search(
        r"\b(\d{1,3})\s*(?:\u043f\u043e\u0440\u0442|\u043f\u043e\u0440\u0442\u0430|\u043f\u043e\u0440\u0442\u043e\u0432|\u043f\u043e\u0441\u0442|\u043f\u043e\u0441\u0442\u0430|\u043f\u043e\u0441\u0442\u043e\u0432|\u043c\u0435\u0441\u0442|\u043c\u0435\u0441\u0442\u0430|\u043c\u0435\u0441\u0442\u043d\u0430\u044f)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if direct_match:
        return direct_match.group(1)

    word_patterns = (
        (r"\b\u043e\u0434\u043d(?:\u043e\u0433\u043e|\u0430|\u043e|\u043e\u043c\u0435\u0441\u0442\u043d\w*)\s*(?:\u043f\u043e\u0440\u0442|\u043f\u043e\u0440\u0442\u0430|\u043f\u043e\u0440\u0442\u043e\u0432)?", "1"),
        (r"\b\u0434\u0432(?:\u0430|\u0443\u0445|\u0443\u0445\u043f\u043e\u0440\u0442\w*|\u0443\u0445\u043c\u0435\u0441\u0442\w*)\s*(?:\u043f\u043e\u0440\u0442|\u043f\u043e\u0440\u0442\u0430|\u043f\u043e\u0440\u0442\u043e\u0432)?", "2"),
        (r"\b\u0442\u0440(?:\u0438|\u0435\u0445)\s*(?:\u043f\u043e\u0440\u0442|\u043f\u043e\u0440\u0442\u0430|\u043f\u043e\u0440\u0442\u043e\u0432)?", "3"),
        (r"\b\u0447\u0435\u0442\u044b\u0440(?:\u0435|\u0435\u0445)\s*(?:\u043f\u043e\u0440\u0442|\u043f\u043e\u0440\u0442\u0430|\u043f\u043e\u0440\u0442\u043e\u0432)?", "4"),
    )
    for pattern, value in word_patterns:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return value
    return ""


_GENERIC_CABLE_DESIGNATION_TOKENS = {
    "a",
    "а",
    "cat",
    "category",
    "cord",
    "cable",
    "indoor",
    "indooroutdoor",
    "lan",
    "outdoor",
    "patch",
    "wire",
    "\u0430\u0440\u0442",
    "\u0430\u0440\u0442\u0438\u043a\u0443\u043b",
    "\u0432\u0438\u0442\u0430\u044f",
    "\u043a\u0430\u0431\u0435\u043b\u044c",
    "\u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044f",
    "\u043a\u043e\u043d\u0442\u0440\u043e\u043b\u044c\u043d\u044b\u0439",
    "\u043a\u043e\u0440\u0434",
    "\u043c\u0435\u0434\u043d\u044b\u0439",
    "\u043f\u0430\u0440\u0430",
    "\u043f\u0430\u0442\u0447",
    "\u043f\u0440\u043e\u0432\u043e\u0434",
    "\u0441\u0438\u0433\u043d\u0430\u043b\u044c\u043d\u044b\u0439",
    "\u0441\u0438\u043b\u043e\u0432\u043e\u0439",
    "\u044d\u043a\u0440\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0439",
    "\u043d\u0435\u044d\u043a\u0440\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0439",
}


def _extract_cable_designation_family(normalized: str) -> str:
    if not normalized:
        return ""

    dimension_match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*[x\u0445\u00d7*/]\s*(\d+(?:[.,]\d+)?)(?:\s*[x\u0445\u00d7*/]\s*(\d+(?:[.,]\d+)?))?",
        normalized,
        flags=re.IGNORECASE,
    )
    if not dimension_match:
        return ""

    base_part = normalized[: dimension_match.start()]
    base_part = re.sub(
        r"\b(?:sku|part\s*number|partnumber|vendor\s*code|\u0430\u0440\u0442\u0438\u043a\u0443\u043b|\u0430\u0440\u0442\.?)\b",
        " ",
        base_part,
        flags=re.IGNORECASE,
    )
    base_part = re.sub(r"[\(\)\[\],;:]+", " ", base_part)
    tokens = [
        token
        for token in re.findall(r"[a-z0-9\u0430-\u044f]+", base_part.lower(), flags=re.IGNORECASE)
        if token and token not in _GENERIC_CABLE_DESIGNATION_TOKENS
    ]
    if not tokens or len(tokens) > 4:
        return ""
    if not any(len(token) >= 3 for token in tokens):
        return ""
    return " ".join(tokens)


def _detect_accessory_kind(normalized: str) -> str:
    if not normalized:
        return ""
    if "\u043e\u0442\u0432\u0435\u0442\u0432\u0438\u0442\u0435\u043b" in normalized:
        return "tee"
    if "\u0443\u0433\u043e\u043b" in normalized:
        return "corner"
    if "\u043a\u043e\u043d\u0441\u043e\u043b" in normalized:
        return "console"
    if "\u0434\u0435\u0440\u0436\u0430\u0442\u0435\u043b" in normalized or (
        "\u0445\u043e\u043c\u0443\u0442" in normalized and "\u0441\u0442\u0430\u043b" in normalized
    ) or "\u0441\u043a\u043e\u0431" in normalized or "\u043e\u0434\u043d\u043e\u043b\u0430\u043f\u043a" in normalized or "\u0434\u0432\u0443\u043b\u0430\u043f\u043a" in normalized:
        return "holder"
    if "\u043f\u0440\u043e\u0444\u0438\u043b" in normalized:
        return "profile"
    if "\u0437\u0430\u0437\u0435\u043c\u043b" in normalized and "\u043f\u043b\u0430\u0441\u0442\u0438\u043d" in normalized:
        return "grounding_plate"
    if "\u0441\u043e\u0435\u0434\u0438\u043d\u0438\u0442\u0435\u043b" in normalized and "\u043f\u043b\u0430\u0441\u0442\u0438\u043d" in normalized:
        return "connector_plate"
    if "\u043f\u043b\u0430\u0441\u0442\u0438\u043d" in normalized:
        return "plate"
    if "\u043a\u0440\u044b\u0448\u043a" in normalized:
        return "cover"
    if any(
        token in normalized
        for token in (
            "\u0430\u043d\u043a\u0435\u0440",
            "\u043a\u0440\u0435\u043f\u0435\u0436",
            "\u0431\u043e\u043b\u0442",
            "\u0448\u0443\u0440\u0443\u043f",
            "\u0448\u043f\u0438\u043b\u044c\u043a",
            "\u0434\u044e\u0431\u0435\u043b",
            "\u0433\u0430\u0439\u043a",
            "\u0448\u0430\u0439\u0431",
        )
    ):
        return "fastener"
    return ""


def looks_like_telecom_rack_query(normalized: str) -> bool:
    if not normalized:
        return False
    if "\u0448\u043a\u0430\u0444" in normalized:
        if any(
            marker in normalized
            for marker in (
                "\u043a\u043e\u043d\u0442\u0440\u043e\u043b\u044c\u043d",
                "\u043f\u0443\u0441\u043a",
                "\u0443\u043f\u0440\u0430\u0432\u043b",
                "\u0430\u0432\u0442\u043e\u043c\u0430\u0442",
            )
        ):
            return False
        return True
    return bool(
        re.search(
            r"\b(?:\u0441\u0442\u043e\u0439\u043a\u0430|\u0441\u0442\u043e\u0439\u043a\u0438|\u0441\u0442\u043e\u0439\u043a\u0443|\u0441\u0442\u043e\u0439\u043a\u0435|\u0441\u0442\u043e\u0439\u043a\u043e\u0439|\u0441\u0442\u043e\u0435\u043a)\b",
            normalized,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_ats_sts_device(normalized: str) -> bool:
    if "ÑÑ‚Ð°Ñ‚Ð¸Ñ‡ÐµÑÐº" in normalized and "Ð¿ÐµÑ€ÐµÐºÐ»ÑŽÑ‡Ð°Ñ‚ÐµÐ»" in normalized:
        return True
    if "switch" in normalized and any(marker in normalized for marker in ("ats", "sts", "transfer")):
        return True
    if not re.search(r"\b(?:ats|sts)\b", normalized, flags=re.IGNORECASE):
        return False
    if any(marker in normalized for marker in ("ÐºÐ¾Ð½Ð½ÐµÐºÑ‚Ð¾Ñ€", "pin", "rgb", "mono", "germ", "hip-", "arl-")):
        return False
    return any(
        marker in normalized
        for marker in ("Ð¿ÐµÑ€ÐµÐºÐ»ÑŽÑ‡", "Ð²Ð²Ð¾Ð´ Ñ€ÐµÐ·ÐµÑ€Ð²Ð°", "bypass", "Ð±Ð°Ð¹Ð¿Ð°Ñ", "transfer", "power", "pdu", "Ð½Ð¾Ð¼Ð¸Ð½Ð°Ð»", "16a", "32a")
    )


def _looks_like_optical_patch_cord(normalized: str, phrase_normalized: str) -> bool:
    if not any(marker in normalized for marker in ("\u043e\u043f\u0442\u0438\u0447\u0435\u0441\u043a", "\u0432\u043e\u043b\u043e\u043a\u043e\u043d")):
        return False
    if "\u0434\u043b\u044f \u043f\u0430\u0442\u0447 \u043a\u043e\u0440\u0434" in phrase_normalized:
        return False
    explicit_patch_cord = "\u043f\u0430\u0442\u0447 \u043a\u043e\u0440\u0434" in phrase_normalized or "patch cord" in phrase_normalized
    connector_markers = ("lc", "sc", "fc", "st", "mtp", "mpo", "duplex", "simplex", "os2", "om3", "om4")
    return explicit_patch_cord and any(marker in normalized for marker in connector_markers)


def _looks_like_keystone_adapter(normalized: str) -> bool:
    if "keystone" not in normalized and "\u043a\u0435\u0439\u0441\u0442\u043e\u0443\u043d" not in normalized:
        return False
    adapter_markers = (
        "\u0430\u0434\u0430\u043f\u0442\u0435\u0440",
        "\u043b\u0438\u0446\u0435\u0432\u0430\u044f \u043f\u0430\u043d\u0435\u043b",
        "\u043d\u0430\u043a\u043b\u0430\u0434\u043a",
        "\u0440\u0430\u043c\u043a",
        "faceplate",
        "cover",
        "adapter",
    )
    return any(marker in normalized for marker in adapter_markers)


def _looks_like_keystone_module(normalized: str) -> bool:
    if "keystone" not in normalized and "\u043a\u0435\u0439\u0441\u0442\u043e\u0443\u043d" not in normalized:
        return False
    if _looks_like_keystone_adapter(normalized):
        return False
    if "\u043f\u0430\u043d\u0435\u043b" in normalized or "patch panel" in normalized or "\u043f\u0430\u0442\u0447 \u043f\u0430\u043d\u0435\u043b" in normalized:
        return False
    module_markers = (
        "\u043c\u043e\u0434\u0443\u043b",
        "jack",
        "toolless",
        "\u0433\u043d\u0435\u0437\u0434\u043e",
        "\u0440\u043e\u0437\u0435\u0442\u043a",
        "\u044d\u043a\u0440\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d",
        "cat5",
        "cat6",
        "cat6a",
        "rj45",
    )
    return any(marker in normalized for marker in module_markers)


def _looks_like_rj45_connector(normalized: str) -> bool:
    if "коннектор" not in normalized or not re.search(r"\brj[\s-]?45\b", normalized, flags=re.IGNORECASE):
        return False
    assembly_noise = (
        "\u043e\u0441\u043d\u043e\u0432",
        "\u0440\u043e\u0437\u0435\u0442\u043a",
        "\u043d\u0430\u043a\u043b\u0430\u0434\u043a",
        "\u0430\u0434\u0430\u043f\u0442\u0435\u0440",
        "\u043b\u0438\u0446\u0435\u0432\u0430\u044f \u043f\u0430\u043d\u0435\u043b",
        "\u0432\u043b\u0430\u0433\u043e\u0441\u0442\u043e\u0439\u043a",
        "\u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0442\u0438\u0432",
        "\u0432 \u0441\u0431\u043e\u0440\u0435",
        "faceplate",
        "cover",
    )
    return not any(marker in normalized for marker in assembly_noise)


def _looks_like_rj45_outlet(normalized: str) -> bool:
    if not re.search(r"\brj[\s-]?45\b", normalized, flags=re.IGNORECASE):
        return False
    power_device_noise = (
        "\u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a \u0431\u0435\u0441\u043f\u0435\u0440\u0435\u0431\u043e\u0439\u043d",
        "line interactive",
        "online ups",
        "usb",
        "schuko",
        "\u0438\u0431\u043f",
        "ups",
    )
    if any(marker in normalized for marker in power_device_noise):
        return False
    adapter_noise = (
        "\u043b\u0438\u0446\u0435\u0432\u0430\u044f \u043f\u0430\u043d\u0435\u043b",
        "\u043d\u0430\u043a\u043b\u0430\u0434\u043a",
        "\u0430\u0434\u0430\u043f\u0442\u0435\u0440",
        "faceplate",
        "cover",
    )
    if any(marker in normalized for marker in adapter_noise):
        return False
    outlet_markers = (
        "\u0440\u043e\u0437\u0435\u0442\u043a",
        "\u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0442\u0438\u0432",
        "\u043b\u044e\u0447\u043e\u043a",
        "\u043a\u0430\u0431\u0435\u043b\u044c-\u043a\u0430\u043d\u0430\u043b",
        "\u0432 \u0441\u0431\u043e\u0440\u0435",
        "\u0435\u0432\u0440\u043e\u0441\u043b\u043e\u0442",
        "\u043d\u0430\u0440\u0443\u0436\u043d",
        "\u0432\u043d\u0443\u0442\u0440\u0435\u043d",
    )
    return any(marker in normalized for marker in outlet_markers)


def classify_item_type(
    text: str,
    synonyms: Mapping[str, str] | None = None,
    taxonomy_rules: Mapping[str, Any] | None = None,
) -> str:
    rules = taxonomy_rules if taxonomy_rules is not None else load_registry_taxonomy_rules()
    normalized = normalize_query_terms(text, synonyms=synonyms)
    phrase_normalized = normalized.replace("-", " ")
    extracted_markers = extract_item_markers(
        text,
        attribute_patterns=rules.get("attribute_patterns", {}),
        synonyms=synonyms,
    )
    registry_match = classify_entity_type_from_registry(text, rules=rules, markers=extracted_markers)
    registry_entity_type = clean_text_value((registry_match or {}).get("entity_type"))
    if registry_entity_type == "rack" and not looks_like_telecom_rack_query(normalized):
        registry_entity_type = ""
    has_iec_connector_markers = _has_iec_power_cable_context(normalized)
    ats_sts_device = _looks_like_ats_sts_device_precise(normalized)
    if ("ats" in normalized or "sts" in normalized) and not ats_sts_device:
        normalized = normalized.replace("ats", " __signal_noise__ ").replace("sts", " __signal_noise__ ")
        phrase_normalized = normalized.replace("-", " ")
        has_iec_connector_markers = _has_iec_power_cable_context(normalized)
    if "soft starter" in normalized or ("плавн" in normalized and "пуск" in normalized):
        return "soft_starter"
    if (
        ("заглуш" in normalized or "панел" in normalized)
        and _has_airflow_blanking_signal(normalized)
    ):
        return "airflow_blanking_panel"
    if (
        "ats" in normalized
        or "sts" in normalized
        or ("статическ" in normalized and "переключател" in normalized)
    ):
        return "ats_sts"
    if ("температур" in normalized or "влажност" in normalized) and "датчик" in normalized:
        if "влажност" in normalized:
            return "temperature_humidity_sensor"
        return "temperature_sensor"
    if "геркон" in normalized or "магнитоконтакт" in normalized:
        return "reed_sensor"
    if has_iec_connector_markers and not _looks_like_pdu_device(normalized) and any(
        token in normalized for token in ("кабель", "cord", "шнур", "соединительн")
    ):
        return "iec_power_cable"
    if _looks_like_pdu_device(normalized):
        if "meter" in normalized or "измерител" in normalized:
            return "pdu_metered"
        return "pdu_basic"
    if _looks_like_optical_patch_cord(normalized, phrase_normalized):
        return "optical_patch_cord"
    if ("оптическ" in normalized and "кросс" in normalized) or ("кросс" in normalized and "волокон" in normalized):
        return "optical_cross"
    if _looks_like_keystone_adapter(normalized):
        return "keystone_adapter"
    if _looks_like_keystone_module(normalized):
        return "keystone_module"
    if _looks_like_rj45_connector(normalized):
        return "rj45_connector"
    if _looks_like_rj45_outlet(normalized):
        return "rj45_outlet"
    if "лючок" in normalized or ("напольн" in normalized and "короб" in normalized):
        return "floor_box"
    if "щеточ" in normalized:
        return "rack_brush_panel"
    if "заглуш" in normalized:
        return "rack_blank_panel"
    if "полк" in normalized:
        return "rack_shelf"
    if "рельс" in normalized or "rail" in normalized or "направляющ" in normalized:
        return "rack_rail"
    if any(token in normalized for token in ("анкер", "болт", "шуруп", "шпильк", "дюбел", "гайк", "шайб")):
        return "fastener"
    if "заземл" in normalized and "шин" in normalized:
        return "ground_bar"
    if has_iec_connector_markers and not _looks_like_pdu_device(normalized):
        return "iec_power_cable"
    if _looks_like_patch_panel(normalized, phrase_normalized):
        return "patch_panel"
    if _looks_like_patch_cord(normalized, phrase_normalized):
        return "patch_cord"
    bulk_markers = ("витая пара", "utp", "ftp", "f utp", "u utp", "бухта", "305м", "500м")
    if any(marker in normalized for marker in bulk_markers):
        return "bulk_twisted_pair"
    if "коаксиал" in normalized or "rg " in normalized or "75 ом" in normalized or "50 ом" in normalized:
        return "coax"
    if looks_like_telecom_rack_query(normalized):
        return "rack"
    if "кабель" in normalized:
        return "cable"
    if "провод" in normalized:
        return "wire"
    if "автомат" in normalized:
        return "breaker"
    if "розетк" in normalized:
        return "socket"
    if "датчик" in normalized:
        return "sensor"
    return registry_entity_type or "other"


def derive_branch_from_text(
    *texts: str,
    keyword_routes: list[dict[str, Any]] | None = None,
    synonyms: Mapping[str, str] | None = None,
    taxonomy_rules: Mapping[str, Any] | None = None,
) -> str:
    rules = taxonomy_rules if taxonomy_rules is not None else load_registry_taxonomy_rules()
    merged = normalize_text(" ".join(filter(None, texts)), synonyms=synonyms)
    if not merged:
        return "прочее"

    ranked_rules = sorted(
        keyword_routes or DEFAULT_KEYWORD_ROUTES,
        key=lambda item: float(item.get("weight", 1.0)),
        reverse=True,
    )
    for rule in ranked_rules:
        patterns = [normalize_text(item, synonyms=synonyms) for item in rule.get("patterns", [])]
        branch_path = normalize_branch_path(rule.get("path", []))
        if any(pattern and pattern in merged for pattern in patterns):
            if branch_path == "телеком > шкафы" and not looks_like_telecom_rack_query(merged):
                continue
            return branch_path

    entity_type = classify_item_type(merged, synonyms=synonyms, taxonomy_rules=rules)
    registry_defaults = registry_family_default_branches(entity_type, rules, branch_hint="")
    if registry_defaults and registry_defaults[0] != "прочее":
        registry_family = entity_family_for_type(entity_type, rules)
        if registry_family in {
            "airflow_blanking_panel",
            "ats_sts",
            "patch_panel",
            "optical_cross",
            "optical_patch_cord",
            "patch_cord",
            "keystone",
            "floor_box",
            "ground_bar",
            "breaker",
            "socket",
            "lighting_fixture",
            "tray_sheet",
            "contactor_starter",
            "control_relay",
            "light_signage",
            "fire_alarm_device",
            "security_control_device",
            "security_software",
            "power_backup",
            "firestop_material",
        }:
            return registry_defaults[0]
    if entity_type in {"pdu", "pdu_basic", "pdu_metered"}:
        if "zero u" in merged:
            return "телеком > питание > pdu > zero u"
        return "телеком > питание > pdu"
    if entity_type == "ats_sts":
        return "телеком > питание > ats"
    if entity_type == "airflow_blanking_panel":
        return "телеком > аксессуары > шкафные аксессуары > заглушки"
    if entity_type == "patch_panel":
        return "телеком > коммутация > патч панели"
    if entity_type == "optical_cross":
        return "телеком > оптика > кроссы"
    if entity_type == "optical_patch_cord":
        return "телеком > кабели > оптические патч корды"
    if entity_type == "patch_cord":
        return "телеком > кабели > патч корды"
    if entity_type in {"keystone_module", "keystone_adapter", "rj45_connector", "rj45_outlet"}:
        return "телеком > коммутация > модули"
    if entity_type == "rack":
        return "телеком > шкафы"
    if entity_type in {"temperature_sensor", "temperature_humidity_sensor", "reed_sensor", "sensor"}:
        return "автоматика > датчики"
    if entity_type in {"rack_blank_panel", "rack_brush_panel", "rack_shelf", "rack_rail"}:
        return "телеком > аксессуары > шкафные аксессуары"
    if entity_type == "floor_box":
        return "телеком > аксессуары > лючки"
    if entity_type == "ground_bar":
        return "телеком > аксессуары > заземление"
    if entity_type == "breaker":
        return "электрика > автоматы"
    if entity_type == "socket":
        return "электрика > розетки"
    if entity_type in {"cable", "bulk_twisted_pair", "coax", "iec_power_cable"}:
        if "cat6" in merged:
            return "телеком > кабели > витая пара > cat6"
        if "cat5e" in merged:
            return "телеком > кабели > витая пара > cat5e"
        if "силов" in merged:
            return "электрика > кабели > силовые"
        return "электрика > кабели"
    if entity_type == "wire":
        return "электрика > провода"
    if "светильник" in merged:
        return "свет > светильники"
    return "прочее"


def normalize_catalog_branch_from_row(
    row: Mapping[str, Any],
    taxonomy_rules: Mapping[str, Any] | None = None,
) -> str:
    rules = dict(taxonomy_rules or {})
    synonyms = rules.get("synonyms", {})
    class_code = clean_text_value(row.get("Код класса"))
    class_name = clean_text_value(row.get("Название класса"))
    item_type = clean_text_value(row.get("Тип изделия"))
    cable_exec = clean_text_value(row.get("Тип исполнения кабельного изделия"))
    name = clean_text_value(row.get(CANONICAL_NAME_COLUMN))

    class_code_map = {
        str(key).strip().lower(): normalize_branch_path(value)
        for key, value in dict(rules.get("class_code_map", {})).items()
    }
    class_name_map = {
        normalize_text(str(key), synonyms=synonyms): normalize_branch_path(value)
        for key, value in dict(rules.get("class_name_map", {})).items()
    }

    if class_code and class_code.lower() in class_code_map:
        return class_code_map[class_code.lower()]

    normalized_class_name = normalize_text(class_name, synonyms=synonyms)
    if normalized_class_name and normalized_class_name in class_name_map:
        return class_name_map[normalized_class_name]

    derived = derive_branch_from_text(
        class_name,
        item_type,
        cable_exec,
        name,
        keyword_routes=list(rules.get("keyword_routes", DEFAULT_KEYWORD_ROUTES)),
        synonyms=synonyms,
        taxonomy_rules=rules,
    )
    if derived != "прочее":
        return derived

    extra_segments: list[str] = []
    if class_name:
        extra_segments.append(class_name)
    elif item_type:
        extra_segments.append(item_type)
    elif name:
        extra_segments.append(name)
    return normalize_branch_path(extra_segments) or "прочее"


def extract_item_markers(
    text: str,
    attribute_patterns: Mapping[str, Any] | None = None,
    synonyms: Mapping[str, str] | None = None,
) -> Dict[str, str]:
    original = clean_text_value(text)
    normalized = normalize_text(original, synonyms=synonyms)
    markers: Dict[str, str] = {}

    rules = dict(attribute_patterns or {})
    for feature_name, matchers in rules.items():
        for matcher in matchers:
            regex = matcher.get("regex")
            if not regex:
                continue
            match = re.search(regex, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(int(matcher["group"])) if "group" in matcher else matcher.get("value")
            if value:
                markers[feature_name] = str(value).lower()
                break

    category_match = re.search(
        r"\b(?:cat|кат|категор(?:ия|ии)?)\s*(5e|5е|6a|6а|6)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if category_match:
        category_value = (
            category_match.group(1)
            .replace("а", "a")
            .replace("е", "e")
            .lower()
        )
        markers["category"] = f"cat{category_value}"

    if "неэкранир" in normalized:
        markers["shielding"] = "utp"
    elif any(token in normalized for token in ("s/ftp", "sftp", "sf/utp", "f/ftp")):
        markers["shielding"] = "sftp"
    elif any(token in normalized for token in ("f/utp", "f utp", "ftp")):
        markers["shielding"] = "ftp"
    elif "экранир" in normalized:
        markers["shielding"] = "shielded"
    elif any(token in normalized for token in ("u/utp", "u utp", "utp", "неэкранир")):
        markers["shielding"] = "utp"

    if any(token in normalized for token in ("внешн", "наружн", "outdoor", "уличн")):
        markers["cable_environment"] = "outdoor"
    elif any(token in normalized for token in ("внутр", "indoor")):
        markers["cable_environment"] = "indoor"

    rack_unit_match = re.search(r"\b(\d{1,2})\s*u\b", normalized, flags=re.IGNORECASE)
    if rack_unit_match:
        markers["rack_unit"] = rack_unit_match.group(1)

    connector_pair = _detect_connector_pair(normalized)
    if connector_pair:
        markers["connector_pair"] = connector_pair

    fiber_mode_match = re.search(r"\b(os2|om1|om2|om3|om4)\b", normalized, flags=re.IGNORECASE)
    if fiber_mode_match:
        markers["fiber_mode"] = fiber_mode_match.group(1).lower()

    if "duplex" in normalized:
        markers["duplex"] = "yes"

    if ("температур" in normalized or "влажност" in normalized) and "датчик" in normalized:
        markers["sensor_kind"] = "temperature_humidity" if "влажност" in normalized else "temperature"
    elif "геркон" in normalized or "магнитоконтакт" in normalized:
        markers["sensor_kind"] = "reed"

    if "полк" in normalized:
        markers["mount_kind"] = "shelf"
    elif "рельс" in normalized or "rail" in normalized or "направляющ" in normalized:
        markers["mount_kind"] = "rail"
    elif "щеточ" in normalized:
        markers["mount_kind"] = "brush_panel"
    elif "заглуш" in normalized:
        markers["mount_kind"] = "blank_panel"

    accessory_kind = _detect_accessory_kind(normalized)
    if accessory_kind:
        markers["accessory_kind"] = accessory_kind

    if "вертик" in normalized:
        markers["orientation_kind"] = "vertical"
    elif "горизонт" in normalized:
        markers["orientation_kind"] = "horizontal"

    if "внеш" in normalized:
        markers["position_kind"] = "outer"
    elif "внутр" in normalized:
        markers["position_kind"] = "inner"

    if _has_airflow_blanking_signal(normalized):
        markers["airflow"] = "yes"

    if "лючок" in normalized or ("напольн" in normalized and "короб" in normalized):
        markers["installation_kind"] = "floor_box"
    elif re.search(r"\brj[\s-]?45\b", normalized, flags=re.IGNORECASE) and "розетк" in normalized:
        markers["installation_kind"] = "outlet_module"

    if "адаптер" in normalized:
        markers["component_kind"] = "adapter"
    elif "лицевая панель" in normalized or ("панел" in normalized and "keystone" in normalized):
        markers["component_kind"] = "faceplate"
    elif "коннектор" in normalized and re.search(r"\brj[\s-]?45\b", normalized, flags=re.IGNORECASE):
        markers["component_kind"] = "connector"
    elif "розетк" in normalized and re.search(r"\brj[\s-]?45\b", normalized, flags=re.IGNORECASE):
        markers["component_kind"] = "outlet"
    elif "keystone" in normalized or "кейстоун" in normalized:
        markers["component_kind"] = "module"

    port_count_match = re.search(r"\b(\d{1,3})\s*порт", normalized, flags=re.IGNORECASE)
    if port_count_match:
        markers["port_count"] = port_count_match.group(1)

    length_match = re.search(r"(\d+(?:[.,]\d+)?)\s*м\b", normalized)
    if length_match:
        markers["length_m"] = length_match.group(1).replace(",", ".")

    current_matches = re.finditer(r"(\d+(?:[.,]\d+)?)\s*а\b", normalized)
    for current_match in current_matches:
        prefix = normalized[max(0, current_match.start() - 16) : current_match.start()]
        if re.search(r"(?:cat|кат|категор(?:ия|ии)?)\s*$", prefix, flags=re.IGNORECASE):
            continue
        markers["current_a"] = current_match.group(1).replace(",", ".")
        break

    if "zero u" in normalized:
        markers["zero_u"] = "yes"
        markers["rack_unit"] = "zero u"
    if markers.get("rack_unit") == "1":
        markers["rack_1u"] = "yes"
    if "19 inch" in normalized:
        markers["rack_size"] = "19 inch"
        markers["rack_mount_19"] = "yes"

    if "ÐºÐ°Ð±ÐµÐ»ÑŒ ÐºÐ°Ð½Ð°Ð»" in normalized or "ÐºÐ°Ð±ÐµÐ»ÑŒ-ÐºÐ°Ð½Ð°Ð»" in original.lower():
        markers["installation_kind"] = "cable_channel"

    if "ÐºÐ¾Ð½ÑÑ‚Ñ€ÑƒÐºÑ‚Ð¸Ð²" in normalized or "Ð² ÑÐ±Ð¾Ñ€Ðµ" in normalized:
        markers["component_kind"] = "assembly"
    elif "Ð½Ð°ÐºÐ»Ð°Ð´Ðº" in normalized:
        markers["component_kind"] = "adapter"

    detected_port_count = _detect_port_count(normalized)
    if detected_port_count:
        markers["port_count"] = detected_port_count

    if "\u043a\u0430\u0431\u0435\u043b\u044c \u043a\u0430\u043d\u0430\u043b" in normalized or "\u043a\u0430\u0431\u0435\u043b\u044c-\u043a\u0430\u043d\u0430\u043b" in original.lower():
        markers["installation_kind"] = "cable_channel"

    if "\u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0442\u0438\u0432" in normalized or "\u0432 \u0441\u0431\u043e\u0440\u0435" in normalized:
        markers["component_kind"] = "assembly"
    elif "\u043d\u0430\u043a\u043b\u0430\u0434\u043a" in normalized:
        markers["component_kind"] = "adapter"

    detected_port_count_precise = _detect_port_count_precise(normalized)
    if detected_port_count_precise:
        markers["port_count"] = detected_port_count_precise

    designation_family = _extract_cable_designation_family(normalized)
    if designation_family:
        markers["designation_family"] = designation_family

    return markers


def build_search_projection_row(
    row: Mapping[str, Any],
    taxonomy_rules: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    rules = dict(taxonomy_rules or {})
    synonyms = dict(rules.get("synonyms", {}))
    name = clean_text_value(row.get(CANONICAL_NAME_COLUMN))
    item_type = clean_text_value(row.get("Тип изделия"))
    class_name = clean_text_value(row.get("Название класса"))
    combined_text = " ".join(filter(None, [name, item_type, class_name]))
    branch_path = normalize_catalog_branch_from_row(row, taxonomy_rules=rules)
    tokens = sorted(set(tokenize(" ".join(filter(None, [name, item_type, class_name])), synonyms=synonyms)))
    entity_type = classify_item_type(combined_text, synonyms=synonyms, taxonomy_rules=rules)
    item_markers = extract_item_markers(combined_text, attribute_patterns=rules.get("attribute_patterns"), synonyms=synonyms)

    projected = {column: row.get(column, "") for column in SEARCH_BASE_COLUMNS}
    projected.update(
        {
            "search_branch_path": branch_path,
            "search_branch_leaf": branch_path.split(BRANCH_PATH_SEPARATOR)[-1] if branch_path else "",
            "search_normalized_name": normalize_text(name, synonyms=synonyms),
            "search_tokens_json": json.dumps(tokens, ensure_ascii=False),
            "search_entity_type": entity_type,
            "search_item_markers_json": json.dumps(item_markers, ensure_ascii=False),
        }
    )
    return projected


def get_search_catalog_readiness(source_path: str | Path) -> SearchCatalogReadiness:
    merged_readiness = get_catalog_readiness(source_path)
    if merged_readiness.clean_dir is None:
        clean_dir = merged_readiness.merged_path.parent
    else:
        clean_dir = merged_readiness.clean_dir
    search_path = get_search_catalog_path(clean_dir)

    if merged_readiness.state != "ready":
        readiness = SearchCatalogReadiness(
            merged_path=merged_readiness.merged_path,
            search_path=search_path,
            state="invalid",
            reason=merged_readiness.reason or "Полная merged БД не готова",
            merged_mtime=merged_readiness.merged_mtime,
            search_mtime=search_path.stat().st_mtime if search_path.exists() else None,
        )
        logger.info(
            "ℹ️ Search catalog readiness: state=%s merged=%s search=%s",
            readiness.state,
            readiness.merged_path,
            readiness.search_path,
        )
        return readiness

    if not search_path.exists():
        readiness = SearchCatalogReadiness(
            merged_path=merged_readiness.merged_path,
            search_path=search_path,
            state="missing",
            reason=f"Поисковая БД не собрана: отсутствует {search_path.name}",
            merged_mtime=merged_readiness.merged_mtime,
            search_mtime=None,
        )
        logger.info(
            "ℹ️ Search catalog readiness: state=%s merged=%s search=%s",
            readiness.state,
            readiness.merged_path,
            readiness.search_path,
        )
        return readiness

    search_mtime = search_path.stat().st_mtime
    merged_mtime = merged_readiness.merged_mtime
    if merged_mtime is not None and search_mtime < merged_mtime:
        readiness = SearchCatalogReadiness(
            merged_path=merged_readiness.merged_path,
            search_path=search_path,
            state="stale",
            reason="Поисковая БД устарела: сначала обновите `🪶 Обновить поисковую БД`.",
            merged_mtime=merged_mtime,
            search_mtime=search_mtime,
        )
        logger.info(
            "ℹ️ Search catalog readiness: state=%s merged=%s search=%s",
            readiness.state,
            readiness.merged_path,
            readiness.search_path,
        )
        return readiness

    readiness = SearchCatalogReadiness(
        merged_path=merged_readiness.merged_path,
        search_path=search_path,
        state="ready",
        reason=None,
        merged_mtime=merged_mtime,
        search_mtime=search_mtime,
    )
    logger.info(
        "ℹ️ Search catalog readiness: state=%s merged=%s search=%s",
        readiness.state,
        readiness.merged_path,
        readiness.search_path,
    )
    return readiness


def _read_search_build_chunksize() -> int:
    raw_value = os.getenv("REMO_SEARCH_BUILD_CHUNKSIZE", str(SEARCH_BUILD_DEFAULT_CHUNKSIZE))
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return SEARCH_BUILD_DEFAULT_CHUNKSIZE


def build_search_catalog_from_merged(merged_csv: Path, output_path: Path | None = None) -> Path:
    merged_path = Path(merged_csv)
    if not merged_path.exists():
        raise FileNotFoundError(f"Не найден merged CSV для поисковой БД: {merged_path}")

    target_path = Path(output_path) if output_path is not None else get_search_catalog_path(merged_path.parent)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = target_path.with_suffix(f"{target_path.suffix}.part")
    if part_path.exists():
        part_path.unlink()

    chunksize = _read_search_build_chunksize()
    logger.info("🪶 Search catalog rebuild start: source=%s target=%s", merged_path, target_path)
    logger.info("🪶 Search catalog source: %s", merged_path)
    logger.info("🪶 Search build config: chunksize=%s", chunksize)

    rows_total = 0
    wrote_header = False
    taxonomy_rules = load_search_taxonomy_rules()
    for chunk in pd.read_csv(
        merged_path,
        sep=";",
        encoding="utf-8",
        chunksize=chunksize,
        low_memory=False,
    ):
        chunk = canonicalize_catalog_columns(chunk, create_missing=True)
        for column in SEARCH_BASE_COLUMNS:
            if column not in chunk.columns:
                chunk[column] = ""
        source_chunk = chunk[SEARCH_BASE_COLUMNS].copy()

        output_rows = [
            build_search_projection_row(row, taxonomy_rules=taxonomy_rules)
            for row in source_chunk.to_dict(orient="records")
        ]
        projected_frame = pd.DataFrame(output_rows, columns=SEARCH_BASE_COLUMNS + SEARCH_DERIVED_COLUMNS)
        projected_frame.to_csv(
            part_path,
            sep=";",
            encoding="utf-8",
            index=False,
            mode="w" if not wrote_header else "a",
            header=not wrote_header,
        )
        wrote_header = True
        rows_total += len(projected_frame)
        logger.info("🪶 Search build progress: rows=%s", rows_total)

    if not wrote_header:
        pd.DataFrame(columns=SEARCH_BASE_COLUMNS + SEARCH_DERIVED_COLUMNS).to_csv(
            part_path,
            sep=";",
            encoding="utf-8",
            index=False,
        )

    part_path.replace(target_path)
    size_bytes = target_path.stat().st_size if target_path.exists() else 0
    logger.info(
        "✅ Search catalog rebuild complete: path=%s rows=%s size_bytes=%s",
        target_path,
        rows_total,
        size_bytes,
    )
    return target_path


def refresh_search_catalog(clean_dir: Path) -> Path:
    clean_dir = Path(clean_dir)
    merged_readiness = get_catalog_readiness(clean_dir)
    if merged_readiness.state != "ready":
        if merged_readiness.state == "missing":
            raise FileNotFoundError(merged_readiness.reason or "Итоговая БД не собрана")
        raise RuntimeError(merged_readiness.reason or f"Итоговая БД не готова: {merged_readiness.state}")
    return build_search_catalog_from_merged(merged_readiness.merged_path, get_search_catalog_path(clean_dir))


def _search_preferred_formats(clean_dir: Path) -> list[str]:
    preferred_path = get_search_catalog_path(clean_dir)
    if preferred_path.name == SEARCH_CATALOG_DUCKDB_FILENAME:
        return ["duckdb", "csv"]
    return ["csv", "duckdb"]


def _search_artifact_path(clean_dir: Path, storage_format: str) -> Path:
    if storage_format == "duckdb":
        return get_search_catalog_duckdb_path(clean_dir)
    return get_search_catalog_csv_path(clean_dir)


def _build_search_catalog_csv_from_merged(merged_path: Path, target_path: Path) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = target_path.with_suffix(f"{target_path.suffix}.part")
    if part_path.exists():
        part_path.unlink()

    chunksize = _read_search_build_chunksize()
    rows_total = 0
    wrote_header = False
    taxonomy_rules = load_search_taxonomy_rules()
    logger.info("Search catalog rebuild start: source=%s target=%s format=csv", merged_path, target_path)

    for chunk in pd.read_csv(
        merged_path,
        sep=";",
        encoding="utf-8",
        chunksize=chunksize,
        low_memory=False,
    ):
        chunk = canonicalize_catalog_columns(chunk, create_missing=True)
        for column in SEARCH_BASE_COLUMNS:
            if column not in chunk.columns:
                chunk[column] = ""
        source_chunk = chunk[SEARCH_BASE_COLUMNS].copy()
        output_rows = [
            build_search_projection_row(row, taxonomy_rules=taxonomy_rules)
            for row in source_chunk.to_dict(orient="records")
        ]
        projected_frame = pd.DataFrame(output_rows, columns=SEARCH_BASE_COLUMNS + SEARCH_DERIVED_COLUMNS)
        projected_frame.to_csv(
            part_path,
            sep=";",
            encoding="utf-8",
            index=False,
            mode="w" if not wrote_header else "a",
            header=not wrote_header,
        )
        wrote_header = True
        rows_total += len(projected_frame)
        logger.info("Search build progress: rows=%s format=csv", rows_total)

    if not wrote_header:
        pd.DataFrame(columns=SEARCH_BASE_COLUMNS + SEARCH_DERIVED_COLUMNS).to_csv(
            part_path,
            sep=";",
            encoding="utf-8",
            index=False,
        )

    part_path.replace(target_path)
    return target_path


def _build_search_catalog_duckdb_from_merged(merged_path: Path, target_path: Path) -> Path:
    if not DUCKDB_AVAILABLE:
        raise RuntimeError("duckdb package is not installed")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = target_path.with_suffix(f"{target_path.suffix}.part")
    if part_path.exists():
        part_path.unlink()

    chunksize = _read_search_build_chunksize()
    rows_total = 0
    created_table = False
    taxonomy_rules = load_search_taxonomy_rules()
    logger.info("Search catalog rebuild start: source=%s target=%s format=duckdb", merged_path, target_path)

    connection = duckdb.connect(str(part_path))
    try:
        for chunk in pd.read_csv(
            merged_path,
            sep=";",
            encoding="utf-8",
            chunksize=chunksize,
            low_memory=False,
        ):
            chunk = canonicalize_catalog_columns(chunk, create_missing=True)
            for column in SEARCH_BASE_COLUMNS:
                if column not in chunk.columns:
                    chunk[column] = ""
            source_chunk = chunk[SEARCH_BASE_COLUMNS].copy()
            output_rows = [
                build_search_projection_row(row, taxonomy_rules=taxonomy_rules)
                for row in source_chunk.to_dict(orient="records")
            ]
            projected_frame = pd.DataFrame(output_rows, columns=SEARCH_BASE_COLUMNS + SEARCH_DERIVED_COLUMNS)
            connection.register("projected_frame", projected_frame)
            if not created_table:
                connection.execute(
                    f"CREATE TABLE {SEARCH_CATALOG_TABLE} AS SELECT * FROM projected_frame"
                )
                created_table = True
            else:
                connection.execute(
                    f"INSERT INTO {SEARCH_CATALOG_TABLE} SELECT * FROM projected_frame"
                )
            connection.unregister("projected_frame")
            rows_total += len(projected_frame)
            logger.info("Search build progress: rows=%s format=duckdb", rows_total)

        if not created_table:
            empty_frame = pd.DataFrame(columns=SEARCH_BASE_COLUMNS + SEARCH_DERIVED_COLUMNS)
            connection.register("projected_frame", empty_frame)
            connection.execute(
                f"CREATE TABLE {SEARCH_CATALOG_TABLE} AS SELECT * FROM projected_frame"
            )
            connection.unregister("projected_frame")
    finally:
        connection.close()

    part_path.replace(target_path)
    size_bytes = target_path.stat().st_size if target_path.exists() else 0
    logger.info(
        "✅ Search catalog rebuild complete: path=%s rows=%s size_bytes=%s format=duckdb",
        target_path,
        rows_total,
        size_bytes,
    )
    return target_path


def iter_search_catalog_chunks(search_path: Path | str, *, chunksize: int = SEARCH_BUILD_DEFAULT_CHUNKSIZE) -> Iterable[pd.DataFrame]:
    catalog_path = Path(search_path)
    if catalog_path.suffix.lower() == ".duckdb":
        if not DUCKDB_AVAILABLE:
            raise RuntimeError("duckdb package is not installed")
        connection = duckdb.connect(str(catalog_path), read_only=True)
        try:
            offset = 0
            while True:
                frame = connection.execute(
                    f"SELECT * FROM {SEARCH_CATALOG_TABLE} LIMIT {int(chunksize)} OFFSET {int(offset)}"
                ).df()
                if frame.empty:
                    break
                yield frame
                offset += len(frame)
        finally:
            connection.close()
        return

    yield from pd.read_csv(
        catalog_path,
        sep=";",
        encoding="utf-8",
        chunksize=chunksize,
        low_memory=False,
    )


def get_search_catalog_readiness(source_path: str | Path) -> SearchCatalogReadiness:
    merged_readiness = get_catalog_readiness(source_path)
    clean_dir = merged_readiness.merged_path.parent if merged_readiness.clean_dir is None else merged_readiness.clean_dir
    search_csv_path = get_search_catalog_csv_path(clean_dir)
    search_duckdb_path = get_search_catalog_duckdb_path(clean_dir)
    preferred_formats = _search_preferred_formats(clean_dir)

    def artifact_state(storage_format: str) -> tuple[str, Path, float | None]:
        path = _search_artifact_path(clean_dir, storage_format)
        if not path.exists():
            return "missing", path, None
        path_mtime = path.stat().st_mtime
        if merged_readiness.merged_mtime is not None and path_mtime < merged_readiness.merged_mtime:
            return "stale", path, path_mtime
        return "ready", path, path_mtime

    if merged_readiness.state != "ready":
        preferred_format = preferred_formats[0]
        search_path = _search_artifact_path(clean_dir, preferred_format)
        return SearchCatalogReadiness(
            merged_path=merged_readiness.merged_path,
            search_path=search_path,
            search_format=preferred_format,
            search_csv_path=search_csv_path,
            search_duckdb_path=search_duckdb_path,
            state="invalid",
            reason=merged_readiness.reason or "Search source catalog is not ready",
            merged_mtime=merged_readiness.merged_mtime,
            search_mtime=search_path.stat().st_mtime if search_path.exists() else None,
        )

    ready_candidate: tuple[str, Path, float | None] | None = None
    stale_candidate: tuple[str, Path, float | None] | None = None
    for storage_format in preferred_formats:
        state, path, path_mtime = artifact_state(storage_format)
        if state == "ready" and ready_candidate is None:
            ready_candidate = (storage_format, path, path_mtime)
        elif state == "stale" and stale_candidate is None:
            stale_candidate = (storage_format, path, path_mtime)

    if ready_candidate is not None:
        storage_format, search_path, search_mtime = ready_candidate
        return SearchCatalogReadiness(
            merged_path=merged_readiness.merged_path,
            search_path=search_path,
            search_format=storage_format,
            search_csv_path=search_csv_path,
            search_duckdb_path=search_duckdb_path,
            state="ready",
            reason=None,
            merged_mtime=merged_readiness.merged_mtime,
            search_mtime=search_mtime,
        )

    if stale_candidate is not None:
        storage_format, search_path, search_mtime = stale_candidate
        return SearchCatalogReadiness(
            merged_path=merged_readiness.merged_path,
            search_path=search_path,
            search_format=storage_format,
            search_csv_path=search_csv_path,
            search_duckdb_path=search_duckdb_path,
            state="stale",
            reason="Search catalog is stale; rebuild it from the merged catalog.",
            merged_mtime=merged_readiness.merged_mtime,
            search_mtime=search_mtime,
        )

    preferred_format = preferred_formats[0]
    search_path = _search_artifact_path(clean_dir, preferred_format)
    return SearchCatalogReadiness(
        merged_path=merged_readiness.merged_path,
        search_path=search_path,
        search_format=preferred_format,
        search_csv_path=search_csv_path,
        search_duckdb_path=search_duckdb_path,
        state="missing",
        reason=f"Search catalog is missing: {search_path.name}",
        merged_mtime=merged_readiness.merged_mtime,
        search_mtime=None,
    )


def build_search_catalog_from_merged(merged_csv: Path, output_path: Path | None = None) -> Path:
    merged_path = Path(merged_csv)
    if not merged_path.exists():
        raise FileNotFoundError(f"Search source merged catalog not found: {merged_path}")

    target_path = Path(output_path) if output_path is not None else get_search_catalog_path(merged_path.parent)
    if target_path.suffix.lower() == ".duckdb":
        return _build_search_catalog_duckdb_from_merged(merged_path, target_path)
    return _build_search_catalog_csv_from_merged(merged_path, target_path)


def refresh_search_catalog(clean_dir: Path) -> Path:
    clean_dir = Path(clean_dir)
    merged_readiness = get_catalog_readiness(clean_dir)
    if merged_readiness.state != "ready":
        if merged_readiness.state == "missing":
            raise FileNotFoundError(merged_readiness.reason or "Merged catalog is missing")
        raise RuntimeError(merged_readiness.reason or f"Merged catalog is not ready: {merged_readiness.state}")
    return build_search_catalog_from_merged(merged_readiness.merged_path, get_search_catalog_path(clean_dir))
