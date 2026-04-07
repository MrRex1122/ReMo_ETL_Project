from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping

import pandas as pd

try:
    import duckdb

    DUCKDB_AVAILABLE = True
except ImportError:
    duckdb = None
    DUCKDB_AVAILABLE = False

try:
    from google import genai as genai_sdk
    from google.genai import types as genai_types

    SEARCH_GENAI_SDK_AVAILABLE = True
except ImportError:
    genai_sdk = None
    genai_types = None
    SEARCH_GENAI_SDK_AVAILABLE = False

try:
    import google.generativeai as legacy_genai_sdk

    SEARCH_LEGACY_GENAI_AVAILABLE = True
except ImportError:
    legacy_genai_sdk = None
    SEARCH_LEGACY_GENAI_AVAILABLE = False

from catalog_merge import get_catalog_readiness, get_merged_catalog_path
from catalog_schema import (
    CANONICAL_NAME_COLUMN,
    CANONICAL_PRICE_COLUMN,
    CANONICAL_ARTICLE_COLUMN,
    canonicalize_catalog_columns,
)
from taxonomy_registry import (
    build_taxonomy_tree_snapshot,
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
SEARCH_TAXONOMY_TREE_FILENAME = "taxonomy_tree.json"
SEARCH_TAXONOMY_BRANCH_SUMMARY_FILENAME = "taxonomy_branch_family_summary.csv"
SEARCH_TAXONOMY_PREVIEW_TREE_FILENAME = "taxonomy_preview_tree.json"
SEARCH_TAXONOMY_PREVIEW_BRANCH_SUMMARY_FILENAME = "taxonomy_preview_branch_family_summary.csv"
SEARCH_TAXONOMY_PREVIEW_AUDIT_FILENAME = "taxonomy_preview_branch_cleanup_audit.csv"
SEARCH_TAXONOMY_PROBE_TREE_FILENAME = "taxonomy_probe_tree.json"
SEARCH_TAXONOMY_PROBE_BRANCH_SUMMARY_FILENAME = "taxonomy_probe_branch_family_summary.csv"
SEARCH_TAXONOMY_PROBE_AUDIT_FILENAME = "taxonomy_probe_branch_cleanup_audit.csv"
SEARCH_TAXONOMY_PROBE_REPORT_FILENAME = "taxonomy_probe_report.json"
SEARCH_TAXONOMY_BOOTSTRAP_DRAFT_JSON_FILENAME = "taxonomy_bootstrap_draft.json"
SEARCH_TAXONOMY_BOOTSTRAP_DRAFT_CSV_FILENAME = "taxonomy_bootstrap_draft.csv"
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
    "search_effective_family",
    "search_effective_entity_type",
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


def get_search_taxonomy_tree_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_TAXONOMY_TREE_FILENAME


def get_search_taxonomy_branch_summary_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_TAXONOMY_BRANCH_SUMMARY_FILENAME


def get_search_taxonomy_preview_tree_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_TAXONOMY_PREVIEW_TREE_FILENAME


def get_search_taxonomy_preview_branch_summary_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_TAXONOMY_PREVIEW_BRANCH_SUMMARY_FILENAME


def get_search_taxonomy_preview_audit_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_TAXONOMY_PREVIEW_AUDIT_FILENAME


def get_search_taxonomy_probe_tree_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_TAXONOMY_PROBE_TREE_FILENAME


def get_search_taxonomy_probe_branch_summary_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_TAXONOMY_PROBE_BRANCH_SUMMARY_FILENAME


def get_search_taxonomy_probe_audit_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_TAXONOMY_PROBE_AUDIT_FILENAME


def get_search_taxonomy_probe_report_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_TAXONOMY_PROBE_REPORT_FILENAME


def get_search_taxonomy_bootstrap_draft_json_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_TAXONOMY_BOOTSTRAP_DRAFT_JSON_FILENAME


def get_search_taxonomy_bootstrap_draft_csv_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_TAXONOMY_BOOTSTRAP_DRAFT_CSV_FILENAME


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


def _branch_probe_token_keys(text: str) -> set[str]:
    normalized = normalize_text(text)
    if not normalized:
        return set()
    token_keys: set[str] = set()
    for token in re.findall(r"[a-zа-я0-9]+", normalized, flags=re.IGNORECASE):
        if len(token) < 4:
            continue
        stemmed = re.sub(
            r"(иями|ями|ами|ого|ему|ому|ыми|ими|иях|иях|ией|ией|ий|ый|ой|ая|ое|ые|ие|ов|ев|ам|ям|ах|ях|ы|и|а|я|о|е|у|ю)$",
            "",
            token,
        )
        normalized_token = stemmed if len(stemmed) >= 4 else token
        token_keys.add(normalized_token[:5])
    return token_keys


def _prepare_branch_probe_selection(branch_paths: Iterable[str]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for branch_path in branch_paths:
        normalized_path = normalize_branch_path([branch_path])
        if not normalized_path:
            continue
        segments = normalized_path.split(BRANCH_PATH_SEPARATOR)
        prepared.append(
            {
                "path": normalized_path,
                "prefix": f"{normalized_path}{BRANCH_PATH_SEPARATOR}",
                "has_hierarchy": BRANCH_PATH_SEPARATOR in normalized_path,
                "first_segment": segments[0] if segments else "",
                "last_segment_keys": _branch_probe_token_keys(segments[-1] if segments else normalized_path),
            }
        )
    return prepared


def _branch_matches_probe_selection(candidate_branch: str, selections: Sequence[Mapping[str, Any]]) -> bool:
    normalized_candidate = normalize_branch_path([candidate_branch])
    if not normalized_candidate:
        return False
    candidate_has_hierarchy = BRANCH_PATH_SEPARATOR in normalized_candidate
    candidate_first_segment = normalized_candidate.split(BRANCH_PATH_SEPARATOR)[0]
    candidate_token_keys = _branch_probe_token_keys(normalized_candidate)
    for selection in selections:
        selection_path = clean_text_value(selection.get("path"))
        if not selection_path:
            continue
        if (
            normalized_candidate == selection_path
            or normalized_candidate.startswith(clean_text_value(selection.get("prefix")))
            or selection_path.startswith(f"{normalized_candidate}{BRANCH_PATH_SEPARATOR}")
        ):
            return True
        if not bool(selection.get("has_hierarchy")):
            continue
        selected_last_segment_keys = set(selection.get("last_segment_keys") or set())
        if not selected_last_segment_keys or not candidate_token_keys:
            continue
        if not candidate_has_hierarchy:
            if candidate_token_keys & selected_last_segment_keys:
                return True
            continue
        if clean_text_value(selection.get("first_segment")) == candidate_first_segment and (
            candidate_token_keys & selected_last_segment_keys
        ):
            return True
    return False


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
    if _looks_like_cable_channel_box(normalized):
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


def _looks_like_cable_channel_box(
    normalized: str,
    *,
    extracted_markers: Mapping[str, Any] | None = None,
) -> bool:
    if not normalized:
        return False
    if "коробка" in normalized or "лючок" in normalized:
        return False
    has_channel_phrase = (
        "кабель канал" in normalized
        or "кабель-канал" in normalized
        or re.search(r"\bкороб\b", normalized, flags=re.IGNORECASE) is not None
    )
    if not has_channel_phrase:
        return False
    has_dimensions = bool(
        re.search(
            r"\b\d+(?:[.,]\d+)?\s*[xх×]\s*\d+(?:[.,]\d+)?(?:\s*[xх×]\s*\d+(?:[.,]\d+)?)?\b",
            normalized,
            flags=re.IGNORECASE,
        )
    )
    markers = extracted_markers or {}
    has_length = bool(
        clean_text_value(markers.get("length_m"))
        or re.search(r"\b\d+(?:[.,]\d+)?\s*м\b", normalized, flags=re.IGNORECASE)
    )
    if not has_dimensions:
        return False
    if "кабель канал" in normalized or "кабель-канал" in normalized:
        return True
    return ("крышк" in normalized and has_length) or ("канал" in normalized and has_length)


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
        any(
            token in normalized
            for token in (
                "преобразователь частоты",
                "частотный преобразователь",
                "частотный привод",
                "frequency drive",
                "variable frequency drive",
                "vfd",
                "инверторный привод",
            )
        )
        and not any(
            token in normalized
            for token in (
                "плавного пуска",
                "soft starter",
                "преобразователь интерфейса",
                "интерфейс",
                "rs-485",
            )
        )
    ):
        return "frequency_drive"
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
    if _looks_like_cable_channel_box(normalized, extracted_markers=extracted_markers):
        return "cable_channel"
    if _has_cable_conduit_signal(normalized):
        return "cable_conduit"
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
    if (
        "затвор" in normalized
        or ("кран" in normalized and "шар" in normalized)
        or "butterfly valve" in normalized
        or "ball valve" in normalized
    ):
        return "industrial_valve"
    if "подшип" in normalized or "bearing" in normalized:
        return "bearing"
    if "радиатор" in normalized or "radiator" in normalized:
        return "radiator"
    if ("конвектор" in normalized or "convector" in normalized) and "внутрипол" in normalized:
        return "floor_convector"
    if "термоусаж" in normalized or "термоусад" in normalized or "heat shrink" in normalized or "shrink tube" in normalized:
        return "heat_shrink"
    if "трансформатор" in normalized or "transformer" in normalized:
        return "transformer"
    if any(
        token in normalized
        for token in ("источник бесперебойного питания", "ибп", "ups", "line interactive", "online ups", "uninterruptible")
    ):
        return "ups"
    if "манометр" in normalized or "pressure gauge" in normalized or "gauge pressure" in normalized:
        return "pressure_gauge"
    if (
        any(
            token in normalized
            for token in ("клещи токоизмерительные", "токоизмерительные клещи", "токовые клещи", "clamp meter", "current clamp")
        )
        or (
            any(token in normalized for token in ("клещи", "clamp"))
            and any(token in normalized for token in ("токоизмер", "токов", "ток", "amp", "current"))
            and not any(token in normalized for token in ("обжим", "переставн", "монтажн", "изоляц", "press tool", "crimp"))
        )
    ):
        return "clamp_meter"
    if (
        ("мультиметр" in normalized or "multimeter" in normalized)
        or (
            any(token in normalized for token in ("тестер", "tester"))
            and any(token in normalized for token in ("цифров", "измер", "вольт", "напряж", "ампер", "ток", "ом", "сопротивл", "digital"))
            and not any(token in normalized for token in ("кабельный", "кабеля", "cable", "network", "lan", "rj45", "ethernet", "сканер", "клещи", "clamp"))
        )
    ):
        return "multimeter"
    if (
        any(
            token in normalized
            for token in ("индикатор напряжения", "индикаторы напряжения", "указатель напряжения", "пробник напряжения", "voltage indicator", "voltage tester")
        )
        and not any(
            token in normalized
            for token in ("светосигнальн", "сигнальн ламп", "лампа сигнальн", "световой индикатор", "pilot light", "indicator lamp", "мультиметр", "multimeter")
        )
    ):
        return "voltage_indicator"
    if "регулятор давления" in normalized or "pressure regulator" in normalized:
        return "pressure_regulator"
    if (
        any(token in normalized for token in ("стабилизатор напряжения", "стабилизаторы напряжения", "voltage stabilizer", "avr"))
        and not any(token in normalized for token in ("источник бесперебойного питания", "ибп", "ups", "реле контроля напряжения", "амортизатор"))
    ):
        return "voltage_stabilizer"
    if (
        any(token in normalized for token in ("удлинител", "сетевой фильтр", "штепсель", "вилка", "power strip", "extension cord"))
        or (
            "переходник" in normalized
            and any(token in normalized for token in ("220", "230", "250", "евро", "schuko", "силов", "сетев"))
        )
    ) and not any(token in normalized for token in ("кабельн лот", "keystone", "rj45", "патч", "din рейк", "din-рейк")):
        return "power_accessory"
    if (
        any(token in normalized for token in ("щит распредел", "щиток", "электрощит", "корпус распредел", "корпус учетно"))
        and any(token in normalized for token in ("встраив", "модул", "распредел", "учет"))
        and not any(token in normalized for token in ("заглуш", "двер", "панел", "рамк", "аксессуар", "комплектующ"))
    ):
        return "distribution_enclosure"
    if any(token in normalized for token in ("предохранител", "плавк", "fuse")):
        return "fuse"
    if any(token in normalized for token in ("кнопк", "push button", "кнопочн пост")):
        return "push_button"
    if any(
        token in normalized
        for token in (
            "ограничитель импульсного перенапряжения",
            "ограничители импульсного перенапряжения",
            "перенапряжен",
            "узип",
            "spd",
            "surge protector",
            "surge arrester",
        )
    ) and not any(token in normalized for token in ("предохранител", "автомат", "рубильник")):
        return "surge_protector"
    if any(
        token in normalized
        for token in (
            "штыревые втулочные наконечники",
            "втулочный наконечник",
            "втулочные наконечники",
            "ншв",
            "ншви",
            "ferrule",
            "bootlace ferrule",
        )
    ) and not any(token in normalized for token in ("клеммный блок", "клеммник", "din рейк", "din-рейк", "terminal block")):
        return "wire_ferrule"
    if any(
        token in normalized
        for token in (
            "клеммный блок",
            "клеммные блоки",
            "клеммник",
            "клемма наборная",
            "проходная клемма",
            "миниклем",
            "клеммы на din",
            "terminal block",
            "din rail",
        )
    ) and not any(token in normalized for token in ("заглушк", "маркиров", "аккумулятор", "акб")):
        return "terminal_block"
    if any(
        token in normalized
        for token in ("светосигнальн", "сигнальн ламп", "лампа сигнальн", "световой индикатор", "индикатор световой", "pilot light", "indicator lamp")
    ) and "табло" not in normalized:
        return "signal_indicator"
    if "табло" in normalized and any(
        token in normalized
        for token in ("светов", "свето", "звуков", "эвакуац", "аварийн", "выход", "exit")
    ):
        return "light_signage"
    if "знак" in normalized and any(
        token in normalized
        for token in ("безопас", "эвакуац", "пиктограмм", "warning", "caution")
    ):
        return "safety_sign"
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
    if any(token in normalized for token in ("автомат", "рубильник", "выключатель нагрузки", "выключатель разъединитель")):
        return "breaker"
    if "розетк" in normalized:
        return "socket"
    if "датчик" in normalized:
        return "sensor"
    return registry_entity_type or "other"


def _has_strong_security_domain_signal(normalized_text: str) -> bool:
    normalized = normalize_text(normalized_text)
    if not normalized:
        return False
    if re.search(r"\b(?:опс|пс|bolid|s2000)\b", normalized, flags=re.IGNORECASE):
        return True
    return any(
        token in normalized
        for token in (
            "пожар",
            "охран",
            "сигнализац",
            "извещат",
            "оповещат",
            "пожаротуш",
            "адресн",
            "орион",
            "с2000",
            "болид",
        )
    )


def _has_strong_breaker_domain_signal(normalized_text: str) -> bool:
    normalized = normalize_text(normalized_text)
    if not normalized:
        return False
    breaker_markers = (
        "автоматическ",
        "автомат ",
        " автомат",
        "выключатель нагрузки",
        "дифавтомат",
        "дифф",
        "узо",
        "рубильник",
        "mccb",
        "rcbo",
        "rcd",
        "mcb",
    )
    return any(marker in normalized for marker in breaker_markers)


def _has_wall_wiring_signal(normalized_text: str) -> bool:
    normalized = normalize_text(normalized_text)
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "скрыт",
            "открыт",
            "клавиш",
            "рамк",
            "механизм",
            "установоч",
            "розетк",
            "переключател",
            "диммер",
        )
    )


def _has_strong_lighting_domain_signal(normalized_text: str) -> bool:
    normalized = normalize_text(normalized_text)
    if not normalized:
        return False
    token_patterns = (
        r"\bсветильник\b",
        r"\bпрожектор\b",
        r"аварийн",
        r"освещен",
        r"светодиод",
        r"\bдво(?:[\s\-]|\d|\b)",
        r"\bдсо(?:[\s\-]|\d|\b)",
        r"\bдсп(?:[\s\-]|\d|\b)",
        r"\bдпо(?:[\s\-]|\d|\b)",
        r"\bдку(?:[\s\-]|\d|\b)",
    )
    return any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in token_patterns)


def _looks_like_cable_infrastructure_class_name(normalized_class_name: str) -> bool:
    if not normalized_class_name:
        return False
    return any(
        token in normalized_class_name
        for token in (
            "кабель канал",
            "кабель-канал",
            "кабельных лотков",
            "лотки",
            "лоток",
            "лестничн",
            "перегород",
            "разделител",
            "ответвител",
            "заглушки для кабель",
            "углы для кабель",
            "крышки для кабель",
            "суппорты и адаптеры",
        )
    )


def _normalize_effective_entity_type_by_catalog_branch(
    *,
    branch_path: str,
    effective_entity_type: str,
    raw_entity_type: str,
    rules: Mapping[str, Any],
) -> str:
    normalized_branch = normalize_branch_path([branch_path])
    if not normalized_branch:
        return effective_entity_type

    tray_sheet_branch_markers = (
        "кабельные лотки",
        "листовые лотки",
        "лестничные лотки",
        "разделители и перегородки для кабельных лотков",
    )
    cable_channel_body_branch_markers = (
        "перфорированные кабель-каналы",
        "кабель-каналы",
    )
    tray_accessory_branch_markers = (
        "углы и повороты кабельных лотков",
        "углы для кабель-каналов",
        "тройники для кабель-каналов",
        "крышки для кабельных лотков",
        "ответвители для кабельных лотков",
        "кронштейны и консоли для кабельных лотков",
        "профили strut системы для кабельных лотков",
        "соединители для кабельных лотков",
        "переходники для кабельных лотков",
        "заглушки для кабельных лотков",
        "заглушки для кабель-каналов",
        "фиксаторы для кабельных лотков",
        "подвесы и крепления для кабельных лотков",
    )

    if any(marker in normalized_branch for marker in tray_accessory_branch_markers):
        return "rack_accessory_strict"
    if any(marker in normalized_branch for marker in tray_sheet_branch_markers):
        return "tray_sheet"
    if any(marker in normalized_branch for marker in cable_channel_body_branch_markers):
        return "cable_channel"
    if any(marker in normalized_branch for marker in ("металлорукав с изоляцией", "гофрированные трубы для прокладки кабеля", "трубы жесткие двустенные")):
        return "cable_conduit"
    if any(marker in normalized_branch for marker in ("затворы поворотные дисковые", "краны шаровые стальные", "краны шаровые латунные для воды", "краны шаровые пнд", "клапаны электромагнитные соленоидные")):
        return "industrial_valve"
    if any(marker in normalized_branch for marker in ("подшипники роликовые цилиндрические", "подшипники роликовые сферические", "подшипники роликовые конические", "подшипники шариковые радиальные", "подшипники шариковые радиально-упорные", "упорные подшипники", "самоустанавливающиеся шарикоподшипники", "игольчатые подшипники")):
        return "bearing"
    if "радиаторы стальные панельные" in normalized_branch:
        return "radiator"
    if "конвекторы внутрипольные" in normalized_branch:
        return "floor_convector"
    if "термоусаживаемые изделия" in normalized_branch:
        return "heat_shrink"
    if any(
        marker in normalized_branch
        for marker in ("трансформаторы напряжения понижающие низковольтные", "трансформаторы тока низковольтные")
    ):
        return "transformer"
    if "манометры" in normalized_branch:
        return "pressure_gauge"
    if "клещи токоизмерительные" in normalized_branch:
        return "clamp_meter"
    if "мультиметры" in normalized_branch:
        return "multimeter"
    if "индикаторы напряжения" in normalized_branch:
        return "voltage_indicator"
    if "регулятор давления" in normalized_branch:
        return "pressure_regulator"
    if "стабилизаторы напряжения" in normalized_branch:
        return "voltage_stabilizer"
    if "преобразователи частоты приводы" in normalized_branch:
        return "frequency_drive"
    if "удлинители сетевые фильтры переходники штепсельные вилки" in normalized_branch:
        return "power_accessory"
    if any(
        marker in normalized_branch
        for marker in (
            "корпуса учетно распределительные встраиваемые металлические",
            "корпуса распределительные встраиваемые пластиковые",
        )
    ):
        return "distribution_enclosure"
    if "ограничители импульсного перенапряжения силовые модульные" in normalized_branch:
        return "surge_protector"
    if any(marker in normalized_branch for marker in ("рубильники", "выключатели нагрузки", "выключатели разъединители")):
        return "breaker"
    if "источники бесперебойного питания" in normalized_branch or "ибп" in normalized_branch:
        return "ups"
    if "плавкие предохранители" in normalized_branch:
        return "fuse"
    if any(marker in normalized_branch for marker in ("кнопки", "кнопочные посты")):
        return "push_button"
    if any(
        marker in normalized_branch
        for marker in (
            "клеммные блоки зажимов на din рейку",
            "клеммы на din рейку",
            "проходные клеммы на din рейку",
            "миниклеммы на din рейку",
        )
    ):
        return "terminal_block"
    if "штыревые втулочные наконечники" in normalized_branch:
        return "wire_ferrule"
    if "светосигнальная арматура" in normalized_branch:
        return "signal_indicator"
    if any(marker in normalized_branch for marker in ("световое табло", "свето звуковое табло")):
        return "light_signage"
    if "знаки безопасности" in normalized_branch:
        return "safety_sign"

    return effective_entity_type or raw_entity_type


def _normalize_catalog_effective_entity_type(
    *,
    raw_entity_type: str,
    candidate_entity_type: str,
    normalized_text: str,
    rules: Mapping[str, Any],
) -> str:
    candidate_family = entity_family_for_type(candidate_entity_type, rules)
    raw_family = entity_family_for_type(raw_entity_type, rules)
    if _has_power_accessory_signal(normalized_text):
        if raw_family == "power_accessory":
            return raw_entity_type
        if candidate_family in {"keystone", "rj45_connector", "switch_wiring"}:
            return "power_accessory"
    if _has_cable_conduit_signal(normalized_text):
        if raw_family == "cable_conduit":
            return raw_entity_type or "cable_conduit"
        if candidate_family in {"cable", "wire", "cable_channel", "box"}:
            return "cable_conduit"
    if any(token in normalized_text for token in ("стабилизатор напряжения", "стабилизаторы напряжения", "voltage stabilizer", "avr")) and not any(
        token in normalized_text for token in ("источник бесперебойного питания", "ибп", "ups", "реле контроля напряжения", "амортизатор")
    ):
        if raw_family == "voltage_stabilizer":
            return raw_entity_type or "voltage_stabilizer"
        if candidate_family in {"ups", "transformer", "control_relay"}:
            return "voltage_stabilizer"
    if any(
        token in normalized_text
        for token in (
            "преобразователь частоты",
            "частотн",
            "frequency drive",
            "variable frequency drive",
            "vfd",
            "инверторн",
        )
    ) and not any(
        token in normalized_text
        for token in (
            "плавного пуска",
            "soft starter",
            "преобразователь интерфейса",
            "интерфейс",
            "rs-485",
        )
    ):
        if raw_family == "frequency_drive":
            return raw_entity_type or "frequency_drive"
        if candidate_family in {
            "soft_starter",
            "security_interface_device",
            "security_control_panel",
            "security_module_device",
            "security_control_device",
        }:
            return "frequency_drive"
    if candidate_family == "lighting_fixture":
        if _has_strong_lighting_domain_signal(normalized_text):
            return candidate_entity_type
        if raw_entity_type:
            return raw_entity_type
        return "other"
    if candidate_family == "optical_cross":
        if "кросс" in normalized_text:
            return candidate_entity_type
        if raw_family in {"cable", "bulk_twisted_pair", "coax", "iec_power_cable"} or "кабель" in normalized_text:
            return raw_entity_type
        return "other"
    if candidate_family in {
        "rack_accessory_strict",
        "rj45_connector",
        "keystone",
        "switch_wiring",
    } and _has_strong_lighting_domain_signal(normalized_text):
        return "lighting_fixture"
    if candidate_family == "switch_wiring":
        if _has_strong_breaker_domain_signal(normalized_text) and not _has_wall_wiring_signal(normalized_text):
            return "breaker"
        return candidate_entity_type
    if candidate_family not in {
        "security_interface_device",
        "security_control_panel",
        "security_module_device",
        "security_control_device",
    }:
        return candidate_entity_type
    if _has_strong_security_domain_signal(normalized_text):
        return candidate_entity_type

    if candidate_family == "security_interface_device" and any(
        token in normalized_text for token in ("кабел", "провод", "шнур", "витая пара")
    ):
        if raw_family == "wire":
            return "wire"
        if raw_family == "bulk_twisted_pair":
            return "bulk_twisted_pair"
        return "cable"

    if candidate_family in {"security_control_panel", "security_module_device", "security_control_device"}:
        if "плавн" in normalized_text and "пуск" in normalized_text:
            return "soft_starter"
        if any(
            token in normalized_text
            for token in (
                "авр",
                "автоматический ввод резерва",
                "выключатель нагрузки",
                "выключатель разъединитель",
                "рубильник",
                "узо",
            )
        ):
            return "breaker"
        if any(token in normalized_text for token in ("кабел", "провод", "шнур")):
            if raw_family == "wire":
                return "wire"
            return "cable"
        if any(
            token in normalized_text
            for token in ("knx", "освещен", "светодиодн", "драйвер", "диммер", "котел", "кранов")
        ):
            return "other"
        if raw_family and raw_family not in {
            "security_interface_device",
            "security_control_panel",
            "security_module_device",
            "security_control_device",
            "other",
        }:
            return raw_entity_type
        return "other"

    return candidate_entity_type


def derive_branch_from_text(
    *texts: str,
    keyword_routes: list[dict[str, Any]] | None = None,
    synonyms: Mapping[str, str] | None = None,
    taxonomy_rules: Mapping[str, Any] | None = None,
    catalog_row_mode: bool = False,
) -> str:
    rules = taxonomy_rules if taxonomy_rules is not None else load_registry_taxonomy_rules()
    merged = normalize_text(" ".join(filter(None, texts)), synonyms=synonyms)
    if not merged:
        return "прочее"

    entity_type = classify_item_type(merged, synonyms=synonyms, taxonomy_rules=rules)
    effective_entity_type = entity_type
    effective_family = entity_family_for_type(effective_entity_type, rules)
    if catalog_row_mode:
        extracted_markers = extract_item_markers(
            merged,
            attribute_patterns=rules.get("attribute_patterns", {}),
            synonyms=synonyms,
        )
        registry_match = classify_entity_type_from_registry(merged, rules=rules, markers=extracted_markers)
        effective_entity_type = clean_text_value((registry_match or {}).get("entity_type")) or entity_type
        effective_entity_type = _normalize_catalog_effective_entity_type(
            raw_entity_type=entity_type,
            candidate_entity_type=effective_entity_type,
            normalized_text=merged,
            rules=rules,
        )
        effective_family = entity_family_for_type(effective_entity_type, rules)

    if catalog_row_mode:
        registry_defaults = registry_family_default_branches(effective_entity_type, rules, branch_hint="")
        if registry_defaults and registry_defaults[0] != "прочее":
            if effective_family == "lighting_fixture":
                return registry_defaults[0]
            if effective_family == "cable_channel":
                if "перфор" in merged and any(token in merged for token in ("кабель", "канал", "короб")):
                    return "перфорированные кабель-каналы"
                return "электрика > кабели > кабель-каналы"
            if effective_family == "cable_conduit":
                if "металлорукав" in merged:
                    return "металлорукав с изоляцией"
                if "двустен" in merged and "труб" in merged:
                    return "трубы жесткие двустенные"
                return "гофрированные трубы для прокладки кабеля"
            if effective_family == "industrial_valve":
                if "соленоид" in merged or ("электромагнит" in merged and "клапан" in merged):
                    return "клапаны электромагнитные (соленоидные)"
                if "пнд" in merged:
                    return "краны шаровые пнд"
                if "латун" in merged and "кран" in merged and "шар" in merged:
                    return "краны шаровые латунные для воды"
                if "кран" in merged and "шар" in merged:
                    return "краны шаровые стальные"
                if "чугун" in merged:
                    return "затворы поворотные дисковые чугунные"
                return "затворы поворотные дисковые стальные"
            if effective_family == "bearing":
                if "игольчат" in merged:
                    return "игольчатые подшипники"
                if "самоустанавлива" in merged:
                    return "самоустанавливающиеся шарикоподшипники"
                if "упорн" in merged and "радиальн" not in merged:
                    return "упорные подшипники"
                if "коническ" in merged:
                    return "подшипники роликовые конические"
                if "сферич" in merged:
                    return "подшипники роликовые сферические"
                if "упор" in merged:
                    return "подшипники шариковые радиально-упорные"
                if "шарик" in merged or "радиальн" in merged:
                    return "подшипники шариковые радиальные"
                return "подшипники роликовые цилиндрические"
            if effective_family == "radiator":
                return "радиаторы стальные панельные"
            if effective_family == "floor_convector":
                return "конвекторы внутрипольные"
            if effective_family == "heat_shrink":
                return "термоусаживаемые изделия"
            if effective_family == "transformer":
                if "ток" in merged:
                    return "трансформаторы тока низковольтные"
                return "трансформаторы напряжения понижающие низковольтные"
            if effective_family == "ups":
                return "источники бесперебойного питания (ибп)"
            if effective_family == "pressure_gauge":
                return "манометры"
            if effective_family == "clamp_meter":
                return "клещи токоизмерительные"
            if effective_family == "multimeter":
                return "мультиметры"
            if effective_family == "voltage_indicator":
                return "индикаторы напряжения"
            if effective_family == "pressure_regulator":
                return "регулятор давления"
            if effective_family == "voltage_stabilizer":
                return "стабилизаторы напряжения"
            if effective_family == "frequency_drive":
                return "преобразователи частоты, приводы"
            if effective_family == "power_accessory":
                return "удлинители, сетевые фильтры, переходники, штепсельные вилки"
            if effective_family == "distribution_enclosure":
                if "пластик" in merged:
                    return "корпуса распределительные встраиваемые пластиковые"
                return "корпуса учетно-распределительные встраиваемые металлические"
            if effective_family == "fuse":
                return "плавкие предохранители"
            if effective_family == "push_button":
                if "пост" in merged:
                    return "кнопочные посты"
                return "кнопки"
            if effective_family == "light_signage":
                if "табло" in merged and any(token in merged for token in ("звуков", "сирен", "свето звуков", "светозвуков")):
                    return "свето-звуковое табло"
                return "световое табло"
            if effective_family == "safety_sign":
                return "знаки безопасности"
            if extracted_markers.get("installation_kind") == "cable_conduit":
                if "металлорукав" in merged:
                    return "металлорукав с изоляцией"
                if "двустен" in merged and "труб" in merged:
                    return "трубы жесткие двустенные"
                return "гофрированные трубы для прокладки кабеля"
            if extracted_markers.get("installation_kind") == "cable_channel":
                return "электрика > кабели > кабель-каналы"
            if effective_family in {"fire_detector", "fire_annunciator"}:
                return registry_defaults[0]
            if effective_family in {
                "security_interface_device",
                "security_control_panel",
                "security_module_device",
                "security_control_device",
            } and _has_strong_security_domain_signal(merged):
                return registry_defaults[0]

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

    registry_defaults = registry_family_default_branches(effective_entity_type, rules, branch_hint="")
    if registry_defaults and registry_defaults[0] != "прочее":
        registry_family = effective_family
        if registry_family == "box":
            if "установоч" in merged:
                return "коробки установочные"
            if "внутрен" in merged:
                return "коробки распределительные внутренние"
            return "коробки распределительные наружные"
        if registry_family == "box_accessory":
            if "установоч" in merged:
                return "аксессуары для установочных коробок"
            return "аксессуары и комплектующие для коробок"
        if registry_family == "power_accessory":
            return "удлинители, сетевые фильтры, переходники, штепсельные вилки"
        if registry_family == "distribution_enclosure":
            if "пластик" in merged:
                return "корпуса распределительные встраиваемые пластиковые"
            return "корпуса учетно-распределительные встраиваемые металлические"
        if registry_family == "cable_channel":
            if "перфор" in merged and any(token in merged for token in ("кабель", "канал", "короб")):
                return "перфорированные кабель-каналы"
            return "электрика > кабели > кабель-каналы"
        if registry_family == "cable_conduit":
            if "металлорукав" in merged:
                return "металлорукав с изоляцией"
            if "двустен" in merged and "труб" in merged:
                return "трубы жесткие двустенные"
            return "гофрированные трубы для прокладки кабеля"
        if registry_family == "industrial_valve":
            if "соленоид" in merged or ("электромагнит" in merged and "клапан" in merged):
                return "клапаны электромагнитные (соленоидные)"
            if "пнд" in merged:
                return "краны шаровые пнд"
            if "латун" in merged and "кран" in merged and "шар" in merged:
                return "краны шаровые латунные для воды"
            if "кран" in merged and "шар" in merged:
                return "краны шаровые стальные"
            if "чугун" in merged:
                return "затворы поворотные дисковые чугунные"
            return "затворы поворотные дисковые стальные"
        if registry_family == "bearing":
            if "игольчат" in merged:
                return "игольчатые подшипники"
            if "самоустанавлива" in merged:
                return "самоустанавливающиеся шарикоподшипники"
            if "упорн" in merged and "радиальн" not in merged:
                return "упорные подшипники"
            if "коническ" in merged:
                return "подшипники роликовые конические"
            if "сферич" in merged:
                return "подшипники роликовые сферические"
            if "упор" in merged:
                return "подшипники шариковые радиально-упорные"
            if "шарик" in merged or "радиальн" in merged:
                return "подшипники шариковые радиальные"
            return "подшипники роликовые цилиндрические"
        if registry_family == "radiator":
            return "радиаторы стальные панельные"
        if registry_family == "floor_convector":
            return "конвекторы внутрипольные"
        if registry_family == "heat_shrink":
            return "термоусаживаемые изделия"
        if registry_family == "transformer":
            if "ток" in merged:
                return "трансформаторы тока низковольтные"
            return "трансформаторы напряжения понижающие низковольтные"
        if registry_family == "ups":
            return "источники бесперебойного питания (ибп)"
        if registry_family == "pressure_gauge":
            return "манометры"
        if registry_family == "clamp_meter":
            return "клещи токоизмерительные"
        if registry_family == "multimeter":
            return "мультиметры"
        if registry_family == "voltage_indicator":
            return "индикаторы напряжения"
        if registry_family == "pressure_regulator":
            return "регулятор давления"
        if registry_family == "voltage_stabilizer":
            return "стабилизаторы напряжения"
        if registry_family == "frequency_drive":
            return "преобразователи частоты, приводы"
        if registry_family == "fuse":
            return "плавкие предохранители"
        if registry_family == "push_button":
            if "пост" in merged:
                return "кнопочные посты"
            return "кнопки"
        if registry_family == "breaker":
            if any(token in merged for token in ("рубильник", "выключатель нагрузки", "выключатель разъединитель")):
                return "рубильники"
            return "электрика > автоматы"
        if registry_family == "surge_protector":
            return "ограничители импульсного перенапряжения силовые модульные"
        if registry_family == "terminal_block":
            if "мини" in merged and "клем" in merged:
                return "миниклеммы на din-рейку"
            if "проходн" in merged and "клем" in merged:
                return "проходные клеммы на din-рейку"
            if ("клем" in merged or "terminal block" in merged) and "блок" not in merged and "блоки" not in merged:
                return "клеммы на din-рейку"
            return "клеммные блоки зажимов на din-рейку"
        if registry_family == "wire_ferrule":
            return "штыревые втулочные наконечники (ншв и ншви)"
        if registry_family == "signal_indicator":
            return "светосигнальная арматура"
        if registry_family == "light_signage":
            if "табло" in merged and any(token in merged for token in ("звуков", "сирен", "свето звуков", "светозвуков")):
                return "свето-звуковое табло"
            return "световое табло"
        if registry_family == "safety_sign":
            return "знаки безопасности"
        if registry_family == "switch_wiring":
            if "рамк" in merged:
                return "рамки"
            if "розетк" in merged and "скрыт" in merged:
                return "розетки скрытого монтажа"
            if "розетк" in merged and "открыт" in merged:
                return "розетки открытого монтажа"
            if "розетк" in merged:
                return "розетки скрытого монтажа"
            if "переключател" in merged and "открыт" in merged:
                return "переключатели открытого монтажа"
            if "выключател" in merged and "скрыт" in merged:
                return "выключатели скрытого монтажа"
        if registry_family == "fire_detector":
            if "охран" in merged:
                return "извещатели охранные"
            return "извещатели пожарные"
        if registry_family == "fire_annunciator":
            if any(token in merged for token in ("звуков", "речев", "сирен")):
                return "звуковой оповещатель"
            return "световой оповещатель"
        if registry_family == "security_control_panel":
            return "приборы приёмно-контрольные для опс"
        if registry_family in {"security_interface_device", "security_module_device"}:
            return "дополнительное оборудование для пс"
        if registry_family in {
            "airflow_blanking_panel",
            "ats_sts",
            "box",
            "box_accessory",
            "power_accessory",
            "distribution_enclosure",
            "cable_conduit",
            "cable_channel",
            "industrial_valve",
            "bearing",
            "radiator",
            "floor_convector",
            "heat_shrink",
            "transformer",
            "voltage_stabilizer",
            "frequency_drive",
            "clamp_meter",
            "voltage_indicator",
            "patch_panel",
            "optical_cross",
            "optical_patch_cord",
            "patch_cord",
            "keystone",
            "floor_box",
            "ground_bar",
            "breaker",
            "surge_protector",
            "ups",
            "fuse",
            "push_button",
            "terminal_block",
            "wire_ferrule",
            "signal_indicator",
            "socket",
            "lighting_fixture",
            "tray_sheet",
            "contactor_starter",
            "control_relay",
            "light_signage",
            "safety_sign",
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
            "switch_wiring",
        }:
            return registry_defaults[0]
    if effective_entity_type in {"pdu", "pdu_basic", "pdu_metered"}:
        if "zero u" in merged:
            return "телеком > питание > pdu > zero u"
        return "телеком > питание > pdu"
    if effective_entity_type == "ats_sts":
        return "телеком > питание > ats"
    if effective_entity_type == "airflow_blanking_panel":
        return "телеком > аксессуары > шкафные аксессуары > заглушки"
    if effective_entity_type == "patch_panel":
        return "телеком > коммутация > патч панели"
    if effective_entity_type == "optical_cross":
        return "телеком > оптика > кроссы"
    if effective_entity_type == "optical_patch_cord":
        return "телеком > кабели > оптические патч корды"
    if effective_entity_type == "patch_cord":
        return "телеком > кабели > патч корды"
    if effective_entity_type in {"keystone_module", "keystone_adapter", "rj45_connector", "rj45_outlet"}:
        return "телеком > коммутация > модули"
    if effective_entity_type == "rack":
        return "телеком > шкафы"
    if effective_entity_type in {"temperature_sensor", "temperature_humidity_sensor", "reed_sensor", "sensor"}:
        return "автоматика > датчики"
    if effective_entity_type in {"rack_blank_panel", "rack_brush_panel", "rack_shelf", "rack_rail"}:
        return "телеком > аксессуары > шкафные аксессуары"
    if effective_entity_type == "floor_box":
        return "телеком > аксессуары > лючки"
    if effective_entity_type == "ground_bar":
        return "телеком > аксессуары > заземление"
    if effective_entity_type == "breaker":
        if any(token in merged for token in ("рубильник", "выключатель нагрузки", "выключатель разъединитель")):
            return "рубильники"
        return "электрика > автоматы"
    if effective_entity_type == "surge_protector":
        return "ограничители импульсного перенапряжения силовые модульные"
    if effective_entity_type == "ups":
        return "источники бесперебойного питания (ибп)"
    if effective_entity_type == "clamp_meter":
        return "клещи токоизмерительные"
    if effective_entity_type == "multimeter":
        return "мультиметры"
    if effective_entity_type == "voltage_indicator":
        return "индикаторы напряжения"
    if effective_entity_type == "voltage_stabilizer":
        return "стабилизаторы напряжения"
    if effective_entity_type == "frequency_drive":
        return "преобразователи частоты, приводы"
    if effective_entity_type == "fuse":
        return "плавкие предохранители"
    if effective_entity_type == "power_accessory":
        return "удлинители, сетевые фильтры, переходники, штепсельные вилки"
    if effective_entity_type == "distribution_enclosure":
        if "пластик" in merged:
            return "корпуса распределительные встраиваемые пластиковые"
        return "корпуса учетно-распределительные встраиваемые металлические"
    if effective_entity_type == "push_button":
        if "пост" in merged:
            return "кнопочные посты"
        return "кнопки"
    if effective_entity_type == "terminal_block":
        if "мини" in merged and "клем" in merged:
            return "миниклеммы на din-рейку"
        if "проходн" in merged and "клем" in merged:
            return "проходные клеммы на din-рейку"
        if ("клем" in merged or "terminal block" in merged) and "блок" not in merged and "блоки" not in merged:
            return "клеммы на din-рейку"
        return "клеммные блоки зажимов на din-рейку"
    if effective_entity_type == "wire_ferrule":
        return "штыревые втулочные наконечники (ншв и ншви)"
    if effective_entity_type == "signal_indicator":
        return "светосигнальная арматура"
    if effective_entity_type == "socket":
        return "электрика > розетки"
    if effective_entity_type == "light_signage":
        if "табло" in merged and any(token in merged for token in ("звуков", "сирен", "свето звуков", "светозвуков")):
            return "свето-звуковое табло"
        return "световое табло"
    if effective_entity_type == "safety_sign":
        return "знаки безопасности"
    if effective_entity_type == "cable_conduit":
        if "металлорукав" in merged:
            return "металлорукав с изоляцией"
        if "двустен" in merged and "труб" in merged:
            return "трубы жесткие двустенные"
        return "гофрированные трубы для прокладки кабеля"
    if effective_entity_type == "cable_channel":
        if "перфор" in merged and any(token in merged for token in ("кабель", "канал", "короб")):
            return "перфорированные кабель-каналы"
        return "электрика > кабели > кабель-каналы"
    if effective_entity_type in {"cable", "bulk_twisted_pair", "coax", "iec_power_cable"}:
        if _looks_like_cable_channel_box(merged):
            return "электрика > кабели > кабель-каналы"
        if "cat6" in merged:
            return "телеком > кабели > витая пара > cat6"
        if "cat5e" in merged:
            return "телеком > кабели > витая пара > cat5e"
        if "силов" in merged:
            return "электрика > кабели > силовые"
        return "электрика > кабели"
    if effective_entity_type == "wire":
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
    if _looks_like_cable_infrastructure_class_name(normalized_class_name):
        return normalize_branch_path([class_name]) or "прочее"

    derived = derive_branch_from_text(
        class_name,
        item_type,
        cable_exec,
        name,
        keyword_routes=list(rules.get("keyword_routes", DEFAULT_KEYWORD_ROUTES)),
        synonyms=synonyms,
        taxonomy_rules=rules,
        catalog_row_mode=True,
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
    elif _looks_like_cable_channel_box(normalized, extracted_markers=markers):
        markers["installation_kind"] = "cable_channel"
    elif _has_cable_conduit_signal(normalized):
        markers["installation_kind"] = "cable_conduit"

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


def _has_power_accessory_signal(normalized: str) -> bool:
    if not normalized:
        return False
    if any(token in normalized for token in ("удлинител", "сетевой фильтр", "штепсель", "вилка", "power strip", "extension cord")):
        return True
    if "переходник" in normalized and any(token in normalized for token in ("220", "230", "250", "евро", "schuko", "силов", "сетев")):
        return True
    return False


def _has_cable_conduit_signal(normalized: str) -> bool:
    if not normalized:
        return False
    if "металлорукав" in normalized:
        return True
    if "conduit" in normalized and "cable channel" not in normalized:
        return True
    if "двустен" in normalized and "труб" in normalized:
        return True
    if "гофр" in normalized and any(
        token in normalized
        for token in ("труб", "рукав", "прокладк", "кабел", "канализац", "conduit", "corrugated")
    ):
        return True
    return False


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
    registry_match = classify_entity_type_from_registry(
        combined_text,
        rules=rules,
        markers=item_markers,
    )
    effective_entity_type = clean_text_value((registry_match or {}).get("entity_type")) or entity_type
    effective_entity_type = _normalize_catalog_effective_entity_type(
        raw_entity_type=entity_type,
        candidate_entity_type=effective_entity_type,
        normalized_text=normalize_text(combined_text, synonyms=synonyms),
        rules=rules,
    )
    effective_entity_type = _normalize_effective_entity_type_by_catalog_branch(
        branch_path=branch_path,
        effective_entity_type=effective_entity_type,
        raw_entity_type=entity_type,
        rules=rules,
    )
    effective_family = entity_family_for_type(effective_entity_type or entity_type, rules)

    projected = {column: row.get(column, "") for column in SEARCH_BASE_COLUMNS}
    projected.update(
        {
            "search_branch_path": branch_path,
            "search_branch_leaf": branch_path.split(BRANCH_PATH_SEPARATOR)[-1] if branch_path else "",
            "search_normalized_name": normalize_text(name, synonyms=synonyms),
            "search_tokens_json": json.dumps(tokens, ensure_ascii=False),
            "search_entity_type": entity_type,
            "search_effective_family": effective_family,
            "search_effective_entity_type": effective_entity_type,
            "search_item_markers_json": json.dumps(item_markers, ensure_ascii=False),
        }
    )
    return projected


def _update_taxonomy_usage_counters(
    output_rows: list[Mapping[str, Any]],
    *,
    family_counts: Counter[str],
    branch_counts: Counter[str],
    branch_family_counts: Counter[tuple[str, str]],
) -> None:
    for row in output_rows:
        branch_path = clean_text_value(row.get("search_branch_path")).lower()
        effective_family = clean_text_value(row.get("search_effective_family")).lower()
        if branch_path:
            branch_counts[branch_path] += 1
        if effective_family:
            family_counts[effective_family] += 1
        if branch_path and effective_family:
            branch_family_counts[(branch_path, effective_family)] += 1


def _write_search_taxonomy_snapshot(
    clean_dir: Path,
    *,
    taxonomy_rules: Mapping[str, Any],
    rows_total: int,
    family_counts: Counter[str],
    branch_counts: Counter[str],
    branch_family_counts: Counter[tuple[str, str]],
) -> None:
    clean_dir = Path(clean_dir)
    clean_dir.mkdir(parents=True, exist_ok=True)

    tree_snapshot = build_taxonomy_tree_snapshot(taxonomy_rules)
    tree_snapshot["catalog_stats"] = {
        "rows_total": int(rows_total),
        "family_counts": [
            {"family": family_name, "rows_count": int(count)}
            for family_name, count in family_counts.most_common()
        ],
        "top_branches": [],
    }

    branch_rows: list[dict[str, Any]] = []
    for branch_path, branch_total_rows in branch_counts.most_common():
        family_items = [
            (family_name, count)
            for (candidate_branch, family_name), count in branch_family_counts.items()
            if candidate_branch == branch_path
        ]
        family_items.sort(key=lambda item: (-item[1], item[0]))
        top_families = [
            {"family": family_name, "rows_count": int(count)}
            for family_name, count in family_items[:5]
        ]
        tree_snapshot["catalog_stats"]["top_branches"].append(
            {
                "search_branch_path": branch_path,
                "rows_total": int(branch_total_rows),
                "top_families": top_families,
            }
        )
        for family_name, count in family_items:
            share = (float(count) / float(branch_total_rows)) if branch_total_rows else 0.0
            branch_rows.append(
                {
                    "search_branch_path": branch_path,
                    "branch_total_rows": int(branch_total_rows),
                    "effective_family": family_name,
                    "rows_count": int(count),
                    "family_share_within_branch": round(share, 6),
                }
            )

    tree_snapshot["catalog_stats"]["top_branches"] = tree_snapshot["catalog_stats"]["top_branches"][:50]

    tree_path = get_search_taxonomy_tree_path(clean_dir)
    tree_path.write_text(json.dumps(tree_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_path = get_search_taxonomy_branch_summary_path(clean_dir)
    pd.DataFrame(
        branch_rows,
        columns=[
            "search_branch_path",
            "branch_total_rows",
            "effective_family",
            "rows_count",
            "family_share_within_branch",
        ],
    ).to_csv(summary_path, sep=";", encoding="utf-8", index=False)

    logger.info(
        "🧭 Search taxonomy snapshot updated: tree=%s branch_summary=%s rows=%s",
        tree_path,
        summary_path,
        rows_total,
    )


def _build_branch_cleanup_audit_frame(branch_df: pd.DataFrame) -> pd.DataFrame:
    audit_columns = [
        "search_branch_path",
        "branch_total_rows",
        "family_count",
        "top_family",
        "top_family_rows",
        "top_family_share",
        "second_family",
        "second_family_rows",
        "second_family_share",
        "other_rows",
        "other_share",
        "suspicious_score",
        "top_families",
    ]
    if branch_df.empty:
        return pd.DataFrame(columns=audit_columns)

    prepared = branch_df.copy()
    prepared["branch_total_rows"] = pd.to_numeric(prepared["branch_total_rows"], errors="coerce").fillna(0).astype(int)
    prepared["rows_count"] = pd.to_numeric(prepared["rows_count"], errors="coerce").fillna(0).astype(int)
    prepared["family_share_within_branch"] = pd.to_numeric(
        prepared["family_share_within_branch"], errors="coerce"
    ).fillna(0.0)

    audit_rows: list[dict[str, Any]] = []
    for branch_path, group in prepared.groupby("search_branch_path", dropna=False):
        group = group.sort_values(["rows_count", "effective_family"], ascending=[False, True], kind="stable")
        if group.empty:
            continue

        branch_total_rows = int(group["branch_total_rows"].iloc[0])
        if branch_total_rows <= 0:
            continue

        family_items = [
            {
                "family": str(row["effective_family"]),
                "rows_count": int(row["rows_count"]),
                "share": float(row["family_share_within_branch"]),
            }
            for _, row in group.iterrows()
        ]
        family_count = len(family_items)
        top = family_items[0]
        second = family_items[1] if family_count > 1 else {"family": "", "rows_count": 0, "share": 0.0}
        other_item = next((item for item in family_items if item["family"] == "other"), {"rows_count": 0, "share": 0.0})

        suspicious = (
            branch_total_rows >= 100
            and (
                top["family"] == "other"
                or top["share"] < 0.85
                or second["share"] >= 0.10
                or family_count >= 5
                or other_item["share"] >= 0.10
            )
        )
        if not suspicious:
            continue

        suspicious_score = round(
            (1.0 - top["share"]) * branch_total_rows
            + second["share"] * branch_total_rows
            + max(0, family_count - 2) * 25
            + other_item["share"] * branch_total_rows,
            3,
        )
        audit_rows.append(
            {
                "search_branch_path": branch_path,
                "branch_total_rows": branch_total_rows,
                "family_count": family_count,
                "top_family": top["family"],
                "top_family_rows": top["rows_count"],
                "top_family_share": round(top["share"], 6),
                "second_family": second["family"],
                "second_family_rows": second["rows_count"],
                "second_family_share": round(float(second["share"]), 6),
                "other_rows": int(other_item["rows_count"]),
                "other_share": round(float(other_item["share"]), 6),
                "suspicious_score": suspicious_score,
                "top_families": " | ".join(
                    f"{item['family']} ({item['rows_count']})" for item in family_items[:5]
                ),
            }
        )

    audit_df = pd.DataFrame(audit_rows, columns=audit_columns)
    if audit_df.empty:
        return pd.DataFrame(columns=audit_columns)
    return audit_df.sort_values(
        ["suspicious_score", "branch_total_rows", "search_branch_path"],
        ascending=[False, False, True],
        kind="stable",
    ).reset_index(drop=True)


def _create_branch_context_bucket() -> Dict[str, Any]:
    return {
        "sample_names": [],
        "sample_rows": [],
        "top_class_names": Counter(),
        "top_item_types": Counter(),
        "top_articles": [],
    }


def _update_branch_context_from_output_rows(
    output_rows: Iterable[Mapping[str, Any]],
    *,
    branch_context: Dict[str, Dict[str, Any]],
    sample_limit: int = 8,
) -> None:
    for row in output_rows:
        branch_path = clean_text_value(row.get("search_branch_path"))
        if not branch_path:
            continue
        context = branch_context.setdefault(branch_path, _create_branch_context_bucket())

        name = clean_text_value(row.get(CANONICAL_NAME_COLUMN)) or clean_text_value(row.get("search_normalized_name"))
        class_name = clean_text_value(row.get("Название класса"))
        item_type = clean_text_value(row.get("Тип изделия"))
        article = clean_text_value(row.get(CANONICAL_ARTICLE_COLUMN))

        if name and name not in context["sample_names"] and len(context["sample_names"]) < sample_limit:
            context["sample_names"].append(name)
        if class_name:
            context["top_class_names"][class_name] += 1
        if item_type:
            context["top_item_types"][item_type] += 1
        if article and article not in context["top_articles"] and len(context["top_articles"]) < sample_limit:
            context["top_articles"].append(article)

        sample_row = " | ".join(
            part
            for part in (
                name,
                f"class={class_name}" if class_name else "",
                f"type={item_type}" if item_type else "",
                f"article={article}" if article else "",
            )
            if part
        )
        if sample_row and sample_row not in context["sample_rows"] and len(context["sample_rows"]) < sample_limit:
            context["sample_rows"].append(sample_row)


def _serialize_branch_context_field(value: Any, *, limit: int = 5) -> str:
    if isinstance(value, Counter):
        payload = [name for name, _ in value.most_common(limit)]
    elif isinstance(value, list):
        payload = [clean_text_value(item) for item in value if clean_text_value(item)][:limit]
    else:
        payload = []
    return json.dumps(payload, ensure_ascii=False)


def _parse_json_list_field(value: Any) -> List[str]:
    text = clean_text_value(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return [text]
    if isinstance(parsed, list):
        return [clean_text_value(item) for item in parsed if clean_text_value(item)]
    return []


def _build_branch_probe_report_payload(
    *,
    tree_snapshot: Mapping[str, Any],
    branch_df: pd.DataFrame,
    audit_df: pd.DataFrame,
) -> Dict[str, Any]:
    report_stats = dict((tree_snapshot.get("catalog_stats", {}) or {}))
    report_stats["branch_count"] = int(branch_df["search_branch_path"].nunique()) if not branch_df.empty else 0
    report_stats["family_count"] = int(branch_df["effective_family"].nunique()) if not branch_df.empty else 0
    report_stats["suspicious_branch_count"] = int(len(audit_df))

    audit_lookup: Dict[str, Dict[str, Any]] = {}
    if not audit_df.empty:
        for row in audit_df.to_dict(orient="records"):
            branch_path = clean_text_value(row.get("search_branch_path"))
            if not branch_path:
                continue
            audit_lookup[branch_path] = {
                key: (
                    int(value)
                    if key in {"branch_total_rows", "family_count", "top_family_rows", "second_family_rows", "other_rows"}
                    and pd.notna(value)
                    else float(value)
                    if key in {"top_family_share", "second_family_share", "other_share", "suspicious_score"}
                    and pd.notna(value)
                    else clean_text_value(value)
                )
                for key, value in row.items()
            }

    branches_payload: list[dict[str, Any]] = []
    if not branch_df.empty:
        prepared = branch_df.copy()
        prepared["branch_total_rows"] = pd.to_numeric(prepared["branch_total_rows"], errors="coerce").fillna(0).astype(int)
        prepared["rows_count"] = pd.to_numeric(prepared["rows_count"], errors="coerce").fillna(0).astype(int)
        prepared["family_share_within_branch"] = pd.to_numeric(
            prepared["family_share_within_branch"], errors="coerce"
        ).fillna(0.0)
        for branch_path, group in prepared.groupby("search_branch_path", dropna=False):
            cleaned_branch = clean_text_value(branch_path)
            if not cleaned_branch:
                continue
            group = group.sort_values(["rows_count", "effective_family"], ascending=[False, True], kind="stable")
            first_row = group.iloc[0]
            families = [
                {
                    "effective_family": clean_text_value(row.get("effective_family")),
                    "rows_count": int(row.get("rows_count", 0) or 0),
                    "family_share_within_branch": round(float(row.get("family_share_within_branch", 0.0) or 0.0), 6),
                }
                for _, row in group.iterrows()
            ]
            branches_payload.append(
                {
                    "search_branch_path": cleaned_branch,
                    "branch_total_rows": int(first_row.get("branch_total_rows", 0) or 0),
                    "family_count": len(families),
                    "top_family": families[0]["effective_family"] if families else "",
                    "top_family_rows": families[0]["rows_count"] if families else 0,
                    "top_family_share": families[0]["family_share_within_branch"] if families else 0.0,
                    "sample_names": _parse_json_list_field(first_row.get("sample_names_json")),
                    "sample_rows": _parse_json_list_field(first_row.get("sample_rows_json")),
                    "top_class_names": _parse_json_list_field(first_row.get("top_class_names_json")),
                    "top_item_types": _parse_json_list_field(first_row.get("top_item_types_json")),
                    "top_articles": _parse_json_list_field(first_row.get("top_articles_json")),
                    "families": families,
                    "cleanup_audit": audit_lookup.get(cleaned_branch, {}),
                }
            )
    branches_payload.sort(key=lambda item: (-int(item.get("branch_total_rows", 0)), item.get("search_branch_path", "")))

    suspicious_payload = [
        {
            key: (
                int(value)
                if key in {"branch_total_rows", "family_count", "top_family_rows", "second_family_rows", "other_rows"}
                and pd.notna(value)
                else float(value)
                if key in {"top_family_share", "second_family_share", "other_share", "suspicious_score"}
                and pd.notna(value)
                else clean_text_value(value)
            )
            for key, value in row.items()
        }
        for row in audit_df.to_dict(orient="records")
    ] if not audit_df.empty else []

    summary_lines = [
        f"Selected branches: {len(report_stats.get('selected_branches', []) or [])}",
        f"Rows in probe: {int(report_stats.get('rows_total', 0) or 0)}",
        f"Branches in probe: {int(report_stats.get('branch_count', 0) or 0)}",
        f"Families in probe: {int(report_stats.get('family_count', 0) or 0)}",
        f"Suspicious branches: {int(report_stats.get('suspicious_branch_count', 0) or 0)}",
    ]

    return {
        "mode": "branch_probe_report",
        "catalog_stats": report_stats,
        "summary_lines": summary_lines,
        "taxonomy_tree": tree_snapshot,
        "branches": branches_payload,
        "suspicious_branches": suspicious_payload,
    }


def _resolve_search_catalog_snapshot_source(clean_dir: Path) -> Path | None:
    clean_dir = Path(clean_dir)
    readiness = get_search_catalog_readiness(clean_dir)
    if readiness.search_path.exists():
        return readiness.search_path

    existing_candidates: list[Path] = []
    for storage_format in _search_preferred_formats(clean_dir):
        candidate = _search_artifact_path(clean_dir, storage_format)
        if candidate.exists():
            existing_candidates.append(candidate)
    if not existing_candidates:
        return None
    existing_candidates.sort(key=lambda path: (path.stat().st_mtime, path.suffix.lower() == ".duckdb"), reverse=True)
    return existing_candidates[0]


def ensure_search_taxonomy_snapshot(
    clean_dir: Path,
    *,
    force: bool = False,
    chunksize: int = SEARCH_BUILD_DEFAULT_CHUNKSIZE,
) -> tuple[Path, Path]:
    clean_dir = Path(clean_dir)
    tree_path = get_search_taxonomy_tree_path(clean_dir)
    summary_path = get_search_taxonomy_branch_summary_path(clean_dir)
    search_path = _resolve_search_catalog_snapshot_source(clean_dir)
    if search_path is None:
        raise FileNotFoundError("Search catalog is not available yet.")

    search_mtime = search_path.stat().st_mtime
    snapshots_are_fresh = (
        tree_path.exists()
        and summary_path.exists()
        and tree_path.stat().st_mtime >= search_mtime
        and summary_path.stat().st_mtime >= search_mtime
    )
    if snapshots_are_fresh and not force:
        return tree_path, summary_path

    taxonomy_rules = load_search_taxonomy_rules()
    family_counts: Counter[str] = Counter()
    branch_counts: Counter[str] = Counter()
    branch_family_counts: Counter[tuple[str, str]] = Counter()
    rows_total = 0
    for chunk in iter_search_catalog_chunks(search_path, chunksize=chunksize):
        output_rows = chunk.to_dict("records")
        rows_total += len(output_rows)
        _update_taxonomy_usage_counters(
            output_rows,
            family_counts=family_counts,
            branch_counts=branch_counts,
            branch_family_counts=branch_family_counts,
        )

    _write_search_taxonomy_snapshot(
        clean_dir,
        taxonomy_rules=taxonomy_rules,
        rows_total=rows_total,
        family_counts=family_counts,
        branch_counts=branch_counts,
        branch_family_counts=branch_family_counts,
    )
    logger.info(
        "🧭 Search taxonomy snapshot synchronized from catalog: source=%s tree=%s branch_summary=%s rows=%s",
        search_path,
        tree_path,
        summary_path,
        rows_total,
    )
    return tree_path, summary_path


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
    family_counts: Counter[str] = Counter()
    branch_counts: Counter[str] = Counter()
    branch_family_counts: Counter[tuple[str, str]] = Counter()
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
        _update_taxonomy_usage_counters(
            output_rows,
            family_counts=family_counts,
            branch_counts=branch_counts,
            branch_family_counts=branch_family_counts,
        )
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
    _write_search_taxonomy_snapshot(
        target_path.parent,
        taxonomy_rules=taxonomy_rules,
        rows_total=rows_total,
        family_counts=family_counts,
        branch_counts=branch_counts,
        branch_family_counts=branch_family_counts,
    )
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
    family_counts: Counter[str] = Counter()
    branch_counts: Counter[str] = Counter()
    branch_family_counts: Counter[tuple[str, str]] = Counter()
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
            _update_taxonomy_usage_counters(
                output_rows,
                family_counts=family_counts,
                branch_counts=branch_counts,
                branch_family_counts=branch_family_counts,
            )
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
    _write_search_taxonomy_snapshot(
        target_path.parent,
        taxonomy_rules=taxonomy_rules,
        rows_total=rows_total,
        family_counts=family_counts,
        branch_counts=branch_counts,
        branch_family_counts=branch_family_counts,
    )
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


def build_search_taxonomy_preview(
    source_path: Path,
    *,
    chunksize: int | None = None,
) -> tuple[Path, Path, Path]:
    source_path = Path(source_path)
    if source_path.is_dir():
        direct_merged_path = get_merged_catalog_path(source_path)
        if direct_merged_path.exists():
            merged_path = direct_merged_path
            clean_dir = source_path
        else:
            merged_readiness = get_catalog_readiness(source_path)
            if merged_readiness.state != "ready":
                if merged_readiness.state == "missing":
                    raise FileNotFoundError(merged_readiness.reason or "Merged catalog is missing")
                raise RuntimeError(merged_readiness.reason or f"Merged catalog is not ready: {merged_readiness.state}")
            merged_path = merged_readiness.merged_path
            clean_dir = merged_readiness.clean_dir or merged_path.parent
    elif source_path.is_file() and source_path.name == get_merged_catalog_path(source_path.parent).name and source_path.exists():
        merged_path = source_path
        clean_dir = source_path.parent
    else:
        merged_readiness = get_catalog_readiness(source_path)
        if merged_readiness.state != "ready":
            if merged_readiness.state == "missing":
                raise FileNotFoundError(merged_readiness.reason or "Merged catalog is missing")
            raise RuntimeError(merged_readiness.reason or f"Merged catalog is not ready: {merged_readiness.state}")
        merged_path = merged_readiness.merged_path
        clean_dir = merged_readiness.clean_dir or merged_path.parent
    preview_tree_path = get_search_taxonomy_preview_tree_path(clean_dir)
    preview_summary_path = get_search_taxonomy_preview_branch_summary_path(clean_dir)
    preview_audit_path = get_search_taxonomy_preview_audit_path(clean_dir)

    effective_chunksize = chunksize or _read_search_build_chunksize()
    rows_total = 0
    taxonomy_rules = load_search_taxonomy_rules()
    family_counts: Counter[str] = Counter()
    branch_counts: Counter[str] = Counter()
    branch_family_counts: Counter[tuple[str, str]] = Counter()
    branch_context: Dict[str, Dict[str, Any]] = {}
    logger.info("⚡ Taxonomy preview build start: source=%s clean_dir=%s chunksize=%s", merged_path, clean_dir, effective_chunksize)

    for chunk in pd.read_csv(
        merged_path,
        sep=";",
        encoding="utf-8",
        chunksize=effective_chunksize,
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
        _update_taxonomy_usage_counters(
            output_rows,
            family_counts=family_counts,
            branch_counts=branch_counts,
            branch_family_counts=branch_family_counts,
        )
        rows_total += len(output_rows)
        logger.info("⚡ Taxonomy preview progress: rows=%s", rows_total)

    tree_snapshot = build_taxonomy_tree_snapshot(taxonomy_rules)
    tree_snapshot["catalog_stats"] = {
        "rows_total": int(rows_total),
        "family_counts": [
            {"family": family_name, "rows_count": int(count)}
            for family_name, count in family_counts.most_common()
        ],
        "top_branches": [],
        "mode": "preview",
        "source_path": str(merged_path),
    }

    branch_rows: list[dict[str, Any]] = []
    for branch_path, branch_total_rows in branch_counts.most_common():
        family_items = [
            (family_name, count)
            for (candidate_branch, family_name), count in branch_family_counts.items()
            if candidate_branch == branch_path
        ]
        family_items.sort(key=lambda item: (-item[1], item[0]))
        top_families = [
            {"family": family_name, "rows_count": int(count)}
            for family_name, count in family_items[:5]
        ]
        tree_snapshot["catalog_stats"]["top_branches"].append(
            {
                "search_branch_path": branch_path,
                "rows_total": int(branch_total_rows),
                "top_families": top_families,
            }
        )
        for family_name, count in family_items:
            share = (float(count) / float(branch_total_rows)) if branch_total_rows else 0.0
            branch_rows.append(
                {
                    "search_branch_path": branch_path,
                    "branch_total_rows": int(branch_total_rows),
                    "effective_family": family_name,
                    "rows_count": int(count),
                    "family_share_within_branch": round(share, 6),
                }
            )

    tree_snapshot["catalog_stats"]["top_branches"] = tree_snapshot["catalog_stats"]["top_branches"][:50]
    preview_tree_path.write_text(json.dumps(tree_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    branch_df = pd.DataFrame(
        branch_rows,
        columns=[
            "search_branch_path",
            "branch_total_rows",
            "effective_family",
            "rows_count",
            "family_share_within_branch",
        ],
    )
    branch_df.to_csv(preview_summary_path, sep=";", encoding="utf-8", index=False)

    audit_df = _build_branch_cleanup_audit_frame(branch_df)
    audit_df.to_csv(preview_audit_path, sep=";", encoding="utf-8", index=False)

    logger.info(
        "⚡ Taxonomy preview build complete: tree=%s summary=%s audit=%s rows=%s suspicious_branches=%s",
        preview_tree_path,
        preview_summary_path,
        preview_audit_path,
        rows_total,
        len(audit_df),
    )
    return preview_tree_path, preview_summary_path, preview_audit_path


def build_search_taxonomy_branch_probe(
    clean_dir: Path,
    branch_paths: Iterable[str],
    *,
    chunksize: int | None = None,
) -> tuple[Path, Path, Path]:
    clean_dir = Path(clean_dir)
    selected_branches = [
        clean_text_value(branch)
        for branch in branch_paths
        if clean_text_value(branch)
    ]
    selected_branch_set = {normalize_branch_path([branch]) for branch in selected_branches if branch}
    if not selected_branch_set:
        raise ValueError("At least one branch path must be selected for branch probe.")
    prepared_probe_selection = _prepare_branch_probe_selection(selected_branch_set)

    source_path = _resolve_search_catalog_snapshot_source(clean_dir)
    if source_path is None or not Path(source_path).exists():
        readiness = get_search_catalog_readiness(clean_dir)
        raise RuntimeError(readiness.reason or "Search catalog is not available for branch probe.")

    probe_tree_path = get_search_taxonomy_probe_tree_path(clean_dir)
    probe_summary_path = get_search_taxonomy_probe_branch_summary_path(clean_dir)
    probe_audit_path = get_search_taxonomy_probe_audit_path(clean_dir)
    probe_report_path = get_search_taxonomy_probe_report_path(clean_dir)

    effective_chunksize = chunksize or _read_search_build_chunksize()
    rows_total = 0
    taxonomy_rules = load_search_taxonomy_rules()
    family_counts: Counter[str] = Counter()
    branch_counts: Counter[str] = Counter()
    branch_family_counts: Counter[tuple[str, str]] = Counter()
    branch_context: Dict[str, Dict[str, Any]] = {}
    logger.info(
        "⚡ Taxonomy branch probe start: source=%s clean_dir=%s branches=%s chunksize=%s",
        source_path,
        clean_dir,
        len(selected_branch_set),
        effective_chunksize,
    )

    for chunk in iter_search_catalog_chunks(source_path, chunksize=effective_chunksize):
        if "search_branch_path" not in chunk.columns:
            continue
        filtered = chunk[
            chunk["search_branch_path"].astype(str).map(
                lambda value: _branch_matches_probe_selection(value, prepared_probe_selection)
            )
        ]
        if filtered.empty:
            continue
        output_rows = [
            build_search_projection_row(row, taxonomy_rules=taxonomy_rules)
            for row in filtered.to_dict(orient="records")
        ]
        _update_taxonomy_usage_counters(
            output_rows,
            family_counts=family_counts,
            branch_counts=branch_counts,
            branch_family_counts=branch_family_counts,
        )
        _update_branch_context_from_output_rows(output_rows, branch_context=branch_context)
        rows_total += len(output_rows)
        logger.info("⚡ Taxonomy branch probe progress: rows=%s", rows_total)

    tree_snapshot = build_taxonomy_tree_snapshot(taxonomy_rules)
    tree_snapshot["catalog_stats"] = {
        "rows_total": int(rows_total),
        "branch_count": int(len(branch_counts)),
        "family_count": int(len(family_counts)),
        "family_counts": [
            {"family": family_name, "rows_count": int(count)}
            for family_name, count in family_counts.most_common()
        ],
        "top_branches": [],
        "mode": "branch_probe",
        "source_path": str(source_path),
        "selected_branches": selected_branches,
    }

    branch_rows: list[dict[str, Any]] = []
    for branch_path, branch_total_rows in branch_counts.most_common():
        family_items = [
            (family_name, count)
            for (candidate_branch, family_name), count in branch_family_counts.items()
            if candidate_branch == branch_path
        ]
        family_items.sort(key=lambda item: (-item[1], item[0]))
        top_families = [
            {"family": family_name, "rows_count": int(count)}
            for family_name, count in family_items[:5]
        ]
        tree_snapshot["catalog_stats"]["top_branches"].append(
            {
                "search_branch_path": branch_path,
                "rows_total": int(branch_total_rows),
                "top_families": top_families,
            }
        )
        for family_name, count in family_items:
            share = (float(count) / float(branch_total_rows)) if branch_total_rows else 0.0
            context = branch_context.get(branch_path, _create_branch_context_bucket())
            branch_rows.append(
                {
                    "search_branch_path": branch_path,
                    "branch_total_rows": int(branch_total_rows),
                    "effective_family": family_name,
                    "rows_count": int(count),
                    "family_share_within_branch": round(share, 6),
                    "sample_names_json": _serialize_branch_context_field(context.get("sample_names", []), limit=8),
                    "sample_rows_json": _serialize_branch_context_field(context.get("sample_rows", []), limit=8),
                    "top_class_names_json": _serialize_branch_context_field(context.get("top_class_names", Counter()), limit=5),
                    "top_item_types_json": _serialize_branch_context_field(context.get("top_item_types", Counter()), limit=5),
                    "top_articles_json": _serialize_branch_context_field(context.get("top_articles", []), limit=8),
                }
            )

    tree_snapshot["catalog_stats"]["top_branches"] = tree_snapshot["catalog_stats"]["top_branches"][:50]
    probe_tree_path.write_text(json.dumps(tree_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    branch_df = pd.DataFrame(
        branch_rows,
        columns=[
            "search_branch_path",
            "branch_total_rows",
            "effective_family",
            "rows_count",
            "family_share_within_branch",
            "sample_names_json",
            "sample_rows_json",
            "top_class_names_json",
            "top_item_types_json",
            "top_articles_json",
        ],
    )
    branch_df.to_csv(probe_summary_path, sep=";", encoding="utf-8", index=False)

    audit_df = _build_branch_cleanup_audit_frame(branch_df)
    audit_df.to_csv(probe_audit_path, sep=";", encoding="utf-8", index=False)
    probe_report_payload = _build_branch_probe_report_payload(
        tree_snapshot=tree_snapshot,
        branch_df=branch_df,
        audit_df=audit_df,
    )
    probe_report_path.write_text(json.dumps(probe_report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "⚡ Taxonomy branch probe complete: tree=%s summary=%s audit=%s report=%s rows=%s suspicious_branches=%s",
        probe_tree_path,
        probe_summary_path,
        probe_audit_path,
        probe_report_path,
        rows_total,
        len(audit_df),
    )
    return probe_tree_path, probe_summary_path, probe_audit_path


def _init_search_gemini_backend(api_key: str) -> tuple[str, Any]:
    if SEARCH_GENAI_SDK_AVAILABLE:
        try:
            return "google-genai", genai_sdk.Client(api_key=api_key)
        except Exception as exc:
            logger.warning("Failed to initialize google-genai for taxonomy bootstrap: %s", exc)

    if SEARCH_LEGACY_GENAI_AVAILABLE:
        try:
            legacy_genai_sdk.configure(api_key=api_key)
            return "google-generativeai", legacy_genai_sdk
        except Exception as exc:
            logger.warning("Failed to initialize google-generativeai for taxonomy bootstrap: %s", exc)

    raise RuntimeError("Gemini backend is not available for taxonomy bootstrap draft")


def _generate_search_gemini_text(prompt: str, api_key: str, *, model_name: str = "gemini-2.5-flash") -> str:
    backend, client = _init_search_gemini_backend(api_key)
    if backend == "google-genai":
        request_kwargs: Dict[str, Any] = {"model": model_name, "contents": prompt}
        if genai_types is not None:
            request_kwargs["config"] = genai_types.GenerateContentConfig(
                automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True),
                tool_config=genai_types.ToolConfig(
                    function_calling_config=genai_types.FunctionCallingConfig(mode="NONE"),
                ),
            )
        response = client.models.generate_content(**request_kwargs)
        return (getattr(response, "text", None) or "").strip()

    model = client.GenerativeModel(model_name)
    response = model.generate_content(prompt, stream=False)
    return (response.text or "").strip()


def _parse_json_from_llm_text(raw_text: str) -> Any:
    text = clean_text_value(raw_text)
    if not text:
        raise ValueError("LLM returned empty text")

    fenced_match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    candidate_texts = [text]
    if fenced_match:
        candidate_texts.insert(0, fenced_match.group(1).strip())

    first_object = min((idx for idx in (text.find("{"), text.find("[")) if idx >= 0), default=-1)
    if first_object >= 0:
        candidate_texts.append(text[first_object:].strip())

    for candidate in candidate_texts:
        try:
            return json.loads(candidate)
        except Exception:
            continue

    raise ValueError("LLM did not return valid JSON")


def _normalize_branch_match_key(branch_path: str) -> str:
    text = clean_text_value(branch_path)
    if not text:
        return ""
    segments = [segment.strip() for segment in re.split(r"\s*>\s*", text) if clean_text_value(segment)]
    normalized_branch = normalize_branch_path(segments if segments else [text])
    return normalize_text(normalized_branch)


def _branch_match_score(left_branch_path: str, right_branch_path: str) -> float:
    left_key = _normalize_branch_match_key(left_branch_path)
    right_key = _normalize_branch_match_key(right_branch_path)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0

    seq_score = SequenceMatcher(None, left_key, right_key).ratio()
    left_tokens = set(tokenize(left_key))
    right_tokens = set(tokenize(right_key))
    token_score = 0.0
    if left_tokens and right_tokens:
        token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return max(seq_score, token_score)


def _align_branch_proposals(
    proposal_items: Iterable[Mapping[str, Any]],
    expected_branch_paths: Iterable[str],
) -> Dict[str, Dict[str, Any]]:
    expected = [clean_text_value(branch) for branch in expected_branch_paths if clean_text_value(branch)]
    normalized_expected = {branch: _normalize_branch_match_key(branch) for branch in expected}
    aligned: Dict[str, Dict[str, Any]] = {}

    for raw_item in proposal_items:
        item = dict(raw_item or {})
        response_branch_path = clean_text_value(item.get("search_branch_path"))
        if not response_branch_path:
            continue

        if response_branch_path in normalized_expected:
            item["_matched_branch_path"] = response_branch_path
            item["_branch_match_method"] = "exact"
            aligned[response_branch_path] = item
            continue

        response_key = _normalize_branch_match_key(response_branch_path)
        if not response_key:
            continue

        exact_normalized_matches = [
            branch_path for branch_path, branch_key in normalized_expected.items() if branch_key == response_key
        ]
        if len(exact_normalized_matches) == 1:
            matched_branch = exact_normalized_matches[0]
            item["_matched_branch_path"] = matched_branch
            item["_branch_match_method"] = "normalized_exact"
            aligned[matched_branch] = item
            continue

        scored_matches = sorted(
            (
                (_branch_match_score(response_branch_path, branch_path), branch_path)
                for branch_path in expected
            ),
            key=lambda value: (-value[0], value[1]),
        )
        if not scored_matches:
            continue

        best_score, best_branch = scored_matches[0]
        second_score = scored_matches[1][0] if len(scored_matches) > 1 else 0.0
        if best_score >= 0.88 and (best_score - second_score) >= 0.05:
            item["_matched_branch_path"] = best_branch
            item["_branch_match_method"] = "fuzzy"
            aligned[best_branch] = item

    return aligned


def _collect_branch_probe_context(
    source_path: Path,
    branch_paths: Iterable[str],
    *,
    sample_limit: int = 8,
    chunksize: int | None = None,
) -> Dict[str, Dict[str, Any]]:
    branch_list = [clean_text_value(branch) for branch in branch_paths if clean_text_value(branch)]
    branch_set = set(branch_list)
    contexts: Dict[str, Dict[str, Any]] = {
        branch: {
            "sample_names": [],
            "top_class_names": Counter(),
            "top_item_types": Counter(),
            "top_articles": [],
        }
        for branch in branch_list
    }
    if not branch_set:
        return contexts

    effective_chunksize = chunksize or _read_search_build_chunksize()
    for chunk in iter_search_catalog_chunks(source_path, chunksize=effective_chunksize):
        if "search_branch_path" not in chunk.columns:
            continue
        filtered = chunk[chunk["search_branch_path"].astype(str).isin(branch_set)]
        if filtered.empty:
            continue

        for row in filtered.to_dict(orient="records"):
            branch_path = clean_text_value(row.get("search_branch_path"))
            if not branch_path or branch_path not in contexts:
                continue
            context = contexts[branch_path]

            name = clean_text_value(row.get(CANONICAL_NAME_COLUMN))
            if name and name not in context["sample_names"] and len(context["sample_names"]) < sample_limit:
                context["sample_names"].append(name)

            class_name = clean_text_value(row.get("Название класса"))
            if class_name:
                context["top_class_names"][class_name] += 1

            item_type = clean_text_value(row.get("Тип изделия"))
            if item_type:
                context["top_item_types"][item_type] += 1

            article = clean_text_value(row.get(CANONICAL_ARTICLE_COLUMN))
            if article and article not in context["top_articles"] and len(context["top_articles"]) < sample_limit:
                context["top_articles"].append(article)

    serializable: Dict[str, Dict[str, Any]] = {}
    for branch_path, context in contexts.items():
        serializable[branch_path] = {
            "sample_names": list(context["sample_names"]),
            "top_class_names": [name for name, _ in context["top_class_names"].most_common(5)],
            "top_item_types": [name for name, _ in context["top_item_types"].most_common(5)],
            "top_articles": list(context["top_articles"]),
        }
    return serializable


def _collect_branch_probe_context_richer(
    source_path: Path,
    branch_paths: Iterable[str],
    *,
    sample_limit: int = 8,
    chunksize: int | None = None,
) -> Dict[str, Dict[str, Any]]:
    branch_list = [clean_text_value(branch) for branch in branch_paths if clean_text_value(branch)]
    branch_set = set(branch_list)
    contexts: Dict[str, Dict[str, Any]] = {
        branch: {
            "sample_names": [],
            "sample_rows": [],
            "top_class_names": Counter(),
            "top_item_types": Counter(),
            "top_articles": [],
        }
        for branch in branch_list
    }
    if not branch_set:
        return contexts

    effective_chunksize = chunksize or _read_search_build_chunksize()
    for chunk in iter_search_catalog_chunks(source_path, chunksize=effective_chunksize):
        if "search_branch_path" not in chunk.columns:
            continue
        filtered = chunk[chunk["search_branch_path"].astype(str).isin(branch_set)]
        if filtered.empty:
            continue

        for row in filtered.to_dict(orient="records"):
            branch_path = clean_text_value(row.get("search_branch_path"))
            if not branch_path or branch_path not in contexts:
                continue
            context = contexts[branch_path]

            name = clean_text_value(row.get(CANONICAL_NAME_COLUMN)) or clean_text_value(row.get("search_normalized_name"))
            class_name = clean_text_value(row.get("Название класса"))
            item_type = clean_text_value(row.get("Тип изделия"))
            article = clean_text_value(row.get(CANONICAL_ARTICLE_COLUMN))

            if name and name not in context["sample_names"] and len(context["sample_names"]) < sample_limit:
                context["sample_names"].append(name)
            if class_name:
                context["top_class_names"][class_name] += 1
            if item_type:
                context["top_item_types"][item_type] += 1
            if article and article not in context["top_articles"] and len(context["top_articles"]) < sample_limit:
                context["top_articles"].append(article)

            sample_row = " | ".join(
                part
                for part in (
                    name,
                    f"class={class_name}" if class_name else "",
                    f"type={item_type}" if item_type else "",
                    f"article={article}" if article else "",
                )
                if part
            )
            if sample_row and sample_row not in context["sample_rows"] and len(context["sample_rows"]) < sample_limit:
                context["sample_rows"].append(sample_row)

    serializable: Dict[str, Dict[str, Any]] = {}
    for branch_path, context in contexts.items():
        serializable[branch_path] = {
            "sample_names": list(context["sample_names"]),
            "sample_rows": list(context["sample_rows"]),
            "top_class_names": [name for name, _ in context["top_class_names"].most_common(5)],
            "top_item_types": [name for name, _ in context["top_item_types"].most_common(5)],
            "top_articles": list(context["top_articles"]),
        }
    return serializable


def _compute_bootstrap_split_branch_guardrail(branch_payload: Mapping[str, Any]) -> tuple[bool, str]:
    branch_total_rows = int(branch_payload.get("branch_total_rows", 0) or 0)
    family_count = int(branch_payload.get("family_count", 0) or 0)
    top_family_share = float(branch_payload.get("top_family_share", 0.0) or 0.0)
    second_family_share = float(branch_payload.get("second_family_share", 0.0) or 0.0)
    other_share = float(branch_payload.get("other_share", 0.0) or 0.0)

    is_wide_and_mixed = branch_total_rows >= 20000 and family_count >= 5 and top_family_share < 0.9
    is_very_mixed = branch_total_rows >= 5000 and family_count >= 6 and top_family_share < 0.8
    is_high_entropy = branch_total_rows >= 1000 and family_count >= 8 and top_family_share < 0.7
    has_strong_secondary_signal = second_family_share >= 0.03 or other_share >= 0.08

    should_force_split = has_strong_secondary_signal and (is_wide_and_mixed or is_very_mixed or is_high_entropy)
    if not should_force_split:
        return False, ""
    return (
        True,
        "wide_mixed_branch "
        f"rows={branch_total_rows} family_count={family_count} "
        f"top_family_share={top_family_share:.3f} second_family_share={second_family_share:.3f} other_share={other_share:.3f}",
    )


def _apply_bootstrap_split_branch_guardrail(
    proposal: Mapping[str, Any],
    branch_payload: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(proposal or {})
    should_force_split, reason = _compute_bootstrap_split_branch_guardrail(branch_payload)
    normalized["_split_branch_required"] = should_force_split
    normalized["_split_branch_reason"] = reason
    if not should_force_split:
        return normalized

    current_action = clean_text_value(normalized.get("suggested_action"))
    backend_guardrail = clean_text_value(normalized.get("_backend_guardrail"))
    if current_action != "split_branch":
        normalized["suggested_action"] = "split_branch"
        normalized["suggested_family"] = ""
        normalized["suggested_subfamily"] = ""
        rationale = clean_text_value(normalized.get("rationale"))
        rationale_prefix = "Ветка слишком широкая и смешанная, поэтому требует split_branch."
        normalized["rationale"] = f"{rationale_prefix} {rationale}".strip() if rationale else rationale_prefix
        notes = clean_text_value(normalized.get("notes"))
        notes_prefix = f"Backend guardrail: {reason}"
        normalized["notes"] = f"{notes_prefix}. {notes}".strip() if notes else notes_prefix
        normalized["_backend_guardrail"] = "force_split_branch"
        logger.info(
            "🧠 Taxonomy bootstrap guardrail forced split_branch for %s (%s)",
            clean_text_value(branch_payload.get("search_branch_path")),
            reason,
        )
    elif not backend_guardrail:
        normalized["_backend_guardrail"] = "split_branch_confirmed"
    return normalized


def _compute_bootstrap_new_family_candidate(branch_payload: Mapping[str, Any]) -> tuple[bool, str]:
    branch_total_rows = int(branch_payload.get("branch_total_rows", 0) or 0)
    family_count = int(branch_payload.get("family_count", 0) or 0)
    top_family_share = float(branch_payload.get("top_family_share", 0.0) or 0.0)
    other_share = float(branch_payload.get("other_share", 0.0) or 0.0)
    current_top_families = list(branch_payload.get("current_top_families", []) or [])
    current_top_family = ""
    if current_top_families:
        current_top_family = clean_text_value(current_top_families[0].get("family"))

    should_suggest_new_family = (
        current_top_family == "other"
        and branch_total_rows >= 100
        and top_family_share >= 0.6
        and other_share >= 0.6
        and family_count <= 6
        and not bool(branch_payload.get("split_branch_required"))
    )
    if not should_suggest_new_family:
        return False, ""
    return (
        True,
        "taxonomy_gap_candidate "
        f"rows={branch_total_rows} family_count={family_count} "
        f"top_family_share={top_family_share:.3f} other_share={other_share:.3f}",
    )


def build_search_taxonomy_bootstrap_draft(
    clean_dir: Path,
    *,
    api_key: str,
    max_branches: int = 8,
    sample_limit: int = 8,
    model_name: str = "gemini-2.5-flash",
    generate_text: Callable[[str], str] | None = None,
) -> tuple[Path, Path]:
    clean_dir = Path(clean_dir)
    probe_tree_path = get_search_taxonomy_probe_tree_path(clean_dir)
    probe_summary_path = get_search_taxonomy_probe_branch_summary_path(clean_dir)
    probe_audit_path = get_search_taxonomy_probe_audit_path(clean_dir)
    if not all(path.exists() for path in (probe_tree_path, probe_summary_path, probe_audit_path)):
        raise FileNotFoundError("Branch probe artifacts are required before building taxonomy bootstrap draft")

    probe_snapshot = json.loads(probe_tree_path.read_text(encoding="utf-8"))
    probe_summary_df = pd.read_csv(probe_summary_path, sep=";", encoding="utf-8")
    probe_audit_df = pd.read_csv(probe_audit_path, sep=";", encoding="utf-8")
    summary_branch_rows: Dict[str, int] = {}
    if not probe_summary_df.empty:
        prepared_summary = probe_summary_df.copy()
        prepared_summary["branch_total_rows"] = pd.to_numeric(
            prepared_summary.get("branch_total_rows"), errors="coerce"
        ).fillna(0).astype(int)
        for branch_path, group in prepared_summary.groupby("search_branch_path", dropna=False):
            cleaned_branch = clean_text_value(branch_path)
            if not cleaned_branch:
                continue
            summary_branch_rows[cleaned_branch] = int(group["branch_total_rows"].max())

    candidate_branches: list[str] = []
    seen_candidate_branches: set[str] = set()

    def _append_branch(branch_path: object) -> None:
        cleaned_branch = clean_text_value(branch_path)
        if not cleaned_branch or cleaned_branch in seen_candidate_branches:
            return
        seen_candidate_branches.add(cleaned_branch)
        candidate_branches.append(cleaned_branch)

    selected_probe_roots = [
        clean_text_value(item)
        for item in ((probe_snapshot.get("catalog_stats", {}) or {}).get("selected_branches", []) or [])
        if clean_text_value(item)
    ]
    for branch_path in selected_probe_roots:
        _append_branch(branch_path)

    if not probe_audit_df.empty:
        for branch_path in probe_audit_df["search_branch_path"].astype(str).tolist():
            _append_branch(branch_path)

    for branch_path, _rows_total in sorted(
        summary_branch_rows.items(),
        key=lambda item: (-int(item[1]), item[0]),
    ):
        _append_branch(branch_path)

    selected_branches = candidate_branches[: max(1, int(max_branches))]
    if not selected_branches:
        raise RuntimeError("Branch probe has no branches to bootstrap")
    summary_context: Dict[str, Dict[str, Any]] = {}
    for branch_path in selected_branches:
        branch_group = probe_summary_df[probe_summary_df["search_branch_path"].astype(str) == branch_path].copy()
        if branch_group.empty:
            continue
        first_row = branch_group.iloc[0]
        summary_context[branch_path] = {
            "sample_names": _parse_json_list_field(first_row.get("sample_names_json")),
            "sample_rows": _parse_json_list_field(first_row.get("sample_rows_json")),
            "top_class_names": _parse_json_list_field(first_row.get("top_class_names_json")),
            "top_item_types": _parse_json_list_field(first_row.get("top_item_types_json")),
            "top_articles": _parse_json_list_field(first_row.get("top_articles_json")),
        }

    missing_context_branches = [
        branch_path
        for branch_path, context in summary_context.items()
        if not any(context.get(key) for key in ("sample_names", "sample_rows", "top_class_names", "top_item_types"))
    ]
    source_path_value = clean_text_value((probe_snapshot.get("catalog_stats", {}) or {}).get("source_path"))
    source_path = Path(source_path_value) if source_path_value else None
    if missing_context_branches:
        if source_path is None or not source_path.exists():
            raise FileNotFoundError("Branch probe source path is required to enrich missing branch context")
        fallback_context = _collect_branch_probe_context_richer(
            source_path,
            missing_context_branches,
            sample_limit=max(3, int(sample_limit)),
        )
        for branch_path, context in fallback_context.items():
            current = summary_context.setdefault(branch_path, {})
            for key, value in context.items():
                if not current.get(key):
                    current[key] = value

    branch_context = summary_context
    rules = load_search_taxonomy_rules()
    allowed_families = sorted((build_taxonomy_tree_snapshot(rules).get("families") or {}).keys())
    audit_map = {
        clean_text_value(row.get("search_branch_path")): row
        for row in probe_audit_df.to_dict(orient="records")
        if clean_text_value(row.get("search_branch_path"))
    }

    branch_payloads: list[dict[str, Any]] = []
    for branch_path in selected_branches:
        branch_group = probe_summary_df[probe_summary_df["search_branch_path"].astype(str) == branch_path].copy()
        if branch_group.empty:
            continue
        branch_group["rows_count"] = pd.to_numeric(branch_group["rows_count"], errors="coerce").fillna(0).astype(int)
        branch_group["family_share_within_branch"] = pd.to_numeric(
            branch_group["family_share_within_branch"], errors="coerce"
        ).fillna(0.0)
        branch_group = branch_group.sort_values(["rows_count", "effective_family"], ascending=[False, True], kind="stable")
        top_families = [
            {
                "family": str(row["effective_family"]),
                "rows_count": int(row["rows_count"]),
                "share": round(float(row["family_share_within_branch"]), 6),
            }
            for _, row in branch_group.head(5).iterrows()
        ]
        audit_row = dict(audit_map.get(branch_path, {}) or {})
        branch_payloads.append(
            {
                "search_branch_path": branch_path,
                "branch_total_rows": int(branch_group["branch_total_rows"].iloc[0]),
                "family_count": int(audit_row.get("family_count", len(top_families)) or len(top_families)),
                "top_family_share": float(audit_row.get("top_family_share", top_families[0]["share"] if top_families else 0.0) or 0.0),
                "second_family_share": float(audit_row.get("second_family_share", top_families[1]["share"] if len(top_families) > 1 else 0.0) or 0.0),
                "other_share": float(audit_row.get("other_share", 0.0) or 0.0),
                "current_top_families": top_families,
                "sample_names": branch_context.get(branch_path, {}).get("sample_names", []),
                "sample_rows": branch_context.get(branch_path, {}).get("sample_rows", []),
                "top_class_names": branch_context.get(branch_path, {}).get("top_class_names", []),
                "top_item_types": branch_context.get(branch_path, {}).get("top_item_types", []),
                "top_articles": branch_context.get(branch_path, {}).get("top_articles", []),
                "split_branch_required": False,
                "split_branch_reason": "",
                "taxonomy_gap_candidate": False,
                "taxonomy_gap_reason": "",
            }
        )

    for branch_payload in branch_payloads:
        split_branch_required, split_branch_reason = _compute_bootstrap_split_branch_guardrail(branch_payload)
        branch_payload["split_branch_required"] = split_branch_required
        branch_payload["split_branch_reason"] = split_branch_reason
        taxonomy_gap_candidate, taxonomy_gap_reason = _compute_bootstrap_new_family_candidate(branch_payload)
        branch_payload["taxonomy_gap_candidate"] = taxonomy_gap_candidate
        branch_payload["taxonomy_gap_reason"] = taxonomy_gap_reason

    prompt = (
        "You are helping build taxonomy mapping for a search catalog.\n"
        "Return JSON only. Do not rewrite the input data. Do not explain outside JSON.\n\n"
        "Allowed existing families:\n"
        f"{json.dumps(allowed_families, ensure_ascii=False)}\n\n"
        "For each branch, propose:\n"
        "- suggested_action: keep_mixed | tighten_family_mapping | new_subfamily | exclude_family_from_branch | split_branch | new_family | keep_other\n"
        "- suggested_family: one family from the allowed list, or empty string\n"
        "- suggested_subfamily: short snake_case string or empty string\n"
        "- proposed_family_key: snake_case string for a new family, or empty string\n"
        "- proposed_family_label: short human-readable label for a new family, or empty string\n"
        "- proposed_subfamily_key: snake_case string for a new subfamily under the proposed family, or empty string\n"
        "- confidence: number from 0 to 1\n"
        "- rationale: short explanation\n"
        "- evidence_tokens: list of 2-6 important tokens\n"
        "- notes: short note\n\n"
        "Rules:\n"
        "- If split_branch_required=true, return suggested_action=split_branch and keep suggested_family, suggested_subfamily, proposed_family_key, proposed_family_label, proposed_subfamily_key empty.\n"
        "- If taxonomy_gap_candidate=true, prefer suggested_action=new_family or keep_other. Do not force one of the existing families unless there is a very strong semantic fit.\n"
        "- Use suggested_family only when mapping into an already existing family.\n"
        "- Use proposed_family_key/proposed_family_label when the branch should become a new family instead of staying in other.\n"
        "- Copy search_branch_path from the input as accurately as possible.\n\n"
        "Return JSON in this shape:\n"
        "{\n"
        '  "branches": [\n'
        "    {\n"
        '      "search_branch_path": "...",\n'
        '      "suggested_family": "...",\n'
        '      "suggested_subfamily": "",\n'
        '      "suggested_action": "tighten_family_mapping",\n'
        '      "proposed_family_key": "",\n'
        '      "proposed_family_label": "",\n'
        '      "proposed_subfamily_key": "",\n'
        '      "confidence": 0.91,\n'
        '      "rationale": "...",\n'
        '      "evidence_tokens": ["..."],\n'
        '      "notes": "..."\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Branches to review:\n"
        f"{json.dumps(branch_payloads, ensure_ascii=False, indent=2)}"
    )

    raw_text = generate_text(prompt) if generate_text is not None else _generate_search_gemini_text(
        prompt,
        api_key,
        model_name=model_name,
    )
    parsed = _parse_json_from_llm_text(raw_text)
    if isinstance(parsed, dict):
        proposal_items = parsed.get("branches", [])
    elif isinstance(parsed, list):
        proposal_items = parsed
    else:
        raise ValueError("Unexpected taxonomy bootstrap draft payload")

    proposal_by_branch = _align_branch_proposals(proposal_items, [item["search_branch_path"] for item in branch_payloads])

    rows: list[dict[str, Any]] = []
    for branch_payload in branch_payloads:
        branch_path = branch_payload["search_branch_path"]
        proposal = _apply_bootstrap_split_branch_guardrail(
            proposal_by_branch.get(branch_path, {}),
            branch_payload,
        )
        current_top_family = ""
        current_top_families = branch_payload.get("current_top_families", [])
        if current_top_families:
            current_top_family = clean_text_value(current_top_families[0].get("family"))
        evidence_tokens = proposal.get("evidence_tokens", [])
        if not isinstance(evidence_tokens, list):
            evidence_tokens = []
        rows.append(
            {
                "search_branch_path": branch_path,
                "branch_total_rows": int(branch_payload.get("branch_total_rows", 0)),
                "current_top_family": current_top_family,
                "current_top_families": json.dumps(current_top_families, ensure_ascii=False),
                "family_count": int(branch_payload.get("family_count", 0)),
                "top_family_share": float(branch_payload.get("top_family_share", 0.0) or 0.0),
                "second_family_share": float(branch_payload.get("second_family_share", 0.0) or 0.0),
                "other_share": float(branch_payload.get("other_share", 0.0) or 0.0),
                "split_branch_required": bool(branch_payload.get("split_branch_required")),
                "split_branch_reason": clean_text_value(branch_payload.get("split_branch_reason")),
                "taxonomy_gap_candidate": bool(branch_payload.get("taxonomy_gap_candidate")),
                "taxonomy_gap_reason": clean_text_value(branch_payload.get("taxonomy_gap_reason")),
                "response_branch_path": clean_text_value(proposal.get("search_branch_path")),
                "branch_match_method": clean_text_value(proposal.get("_branch_match_method")),
                "backend_guardrail": clean_text_value(proposal.get("_backend_guardrail")),
                "suggested_family": clean_text_value(proposal.get("suggested_family")),
                "suggested_subfamily": clean_text_value(proposal.get("suggested_subfamily")),
                "suggested_action": clean_text_value(proposal.get("suggested_action")),
                "proposed_family_key": clean_text_value(proposal.get("proposed_family_key")),
                "proposed_family_label": clean_text_value(proposal.get("proposed_family_label")),
                "proposed_subfamily_key": clean_text_value(proposal.get("proposed_subfamily_key")),
                "confidence": float(proposal.get("confidence", 0.0) or 0.0),
                "rationale": clean_text_value(proposal.get("rationale")),
                "evidence_tokens": json.dumps([clean_text_value(token) for token in evidence_tokens if clean_text_value(token)], ensure_ascii=False),
                "notes": clean_text_value(proposal.get("notes")),
                "sample_names": json.dumps(branch_payload.get("sample_names", []), ensure_ascii=False),
                "sample_rows": json.dumps(branch_payload.get("sample_rows", []), ensure_ascii=False),
                "top_class_names": json.dumps(branch_payload.get("top_class_names", []), ensure_ascii=False),
                "top_item_types": json.dumps(branch_payload.get("top_item_types", []), ensure_ascii=False),
            }
        )

    draft_json_path = get_search_taxonomy_bootstrap_draft_json_path(clean_dir)
    draft_csv_path = get_search_taxonomy_bootstrap_draft_csv_path(clean_dir)
    draft_payload = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "mode": "branch_probe_bootstrap_draft",
        "model_name": model_name,
        "source_path": str(source_path) if source_path is not None else "",
        "selected_branches": selected_branches,
        "allowed_families": allowed_families,
        "branches": rows,
        "raw_response": raw_text,
    }
    draft_json_path.write_text(json.dumps(draft_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(rows).to_csv(draft_csv_path, sep=";", encoding="utf-8", index=False)
    logger.info(
        "🧠 Taxonomy bootstrap draft complete: json=%s csv=%s branches=%s",
        draft_json_path,
        draft_csv_path,
        len(rows),
    )
    return draft_json_path, draft_csv_path
