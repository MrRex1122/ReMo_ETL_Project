from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import pandas as pd

from catalog_merge import get_catalog_readiness, get_merged_catalog_path
from catalog_schema import (
    CANONICAL_NAME_COLUMN,
    CANONICAL_PRICE_COLUMN,
    CANONICAL_ARTICLE_COLUMN,
    canonicalize_catalog_columns,
)

logger = logging.getLogger(__name__)

SEARCH_CATALOG_FILENAME = "price_clean_search.csv"
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
    state: str
    reason: str | None
    merged_mtime: float | None
    search_mtime: float | None


def get_search_catalog_path(clean_dir: Path) -> Path:
    return Path(clean_dir) / SEARCH_CATALOG_FILENAME


def load_search_taxonomy_rules() -> Dict[str, Any]:
    path_raw = os.getenv("REMO_TAXONOMY_RULES_PATH")
    path = Path(path_raw) if path_raw else DEFAULT_TAXONOMY_RULES_PATH
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    except Exception as exc:
        logger.warning("⚠️ Failed to load search taxonomy rules from %s: %s", path, exc)
    return {}


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


def classify_item_type(text: str, synonyms: Mapping[str, str] | None = None) -> str:
    normalized = normalize_query_terms(text, synonyms=synonyms)
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
    if "pdu" in normalized or "блок розеток" in normalized:
        if "meter" in normalized or "измерител" in normalized:
            return "pdu_metered"
        return "pdu_basic"
    if any(marker in normalized for marker in ("оптическ", "волокон")) and (
        "патч корд" in normalized or "patch cord" in normalized
    ):
        return "optical_patch_cord"
    if "keystone" in normalized or "кейстоун" in normalized:
        return "keystone_module"
    if "коннектор" in normalized and re.search(r"\brj[\s-]?45\b", normalized, flags=re.IGNORECASE):
        return "rj45_connector"
    if "розетк" in normalized and re.search(r"\brj[\s-]?45\b", normalized, flags=re.IGNORECASE):
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
    if "заземл" in normalized and "шин" in normalized:
        return "ground_bar"
    if any(marker in normalized for marker in ("iec320", "c13", "c14", "c19", "c20")):
        return "iec_power_cable"
    if "патч корд" in normalized:
        return "patch_cord"
    bulk_markers = ("витая пара", "utp", "ftp", "f utp", "u utp", "бухта", "305м", "500м")
    if any(marker in normalized for marker in bulk_markers):
        return "bulk_twisted_pair"
    if "коаксиал" in normalized or "rg " in normalized or "75 ом" in normalized or "50 ом" in normalized:
        return "coax"
    if "шкаф" in normalized or "стойк" in normalized:
        return "rack"
    if "патч панел" in normalized:
        return "patch_panel"
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
    return "other"


def derive_branch_from_text(
    *texts: str,
    keyword_routes: list[dict[str, Any]] | None = None,
    synonyms: Mapping[str, str] | None = None,
) -> str:
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
        if any(pattern and pattern in merged for pattern in patterns):
            return normalize_branch_path(rule.get("path", []))

    entity_type = classify_item_type(merged, synonyms=synonyms)
    if entity_type in {"pdu", "pdu_basic", "pdu_metered"}:
        if "zero u" in merged:
            return "телеком > питание > pdu > zero u"
        return "телеком > питание > pdu"
    if entity_type == "ats_sts":
        return "телеком > питание > ats"
    if entity_type == "patch_panel":
        return "телеком > коммутация > патч панели"
    if entity_type == "optical_patch_cord":
        return "телеком > кабели > оптические патч корды"
    if entity_type == "patch_cord":
        return "телеком > кабели > патч корды"
    if entity_type in {"keystone_module", "rj45_connector", "rj45_outlet"}:
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

    category_match = re.search(r"\b(cat\s*6a|cat\s*6|cat\s*5e)\b", normalized, flags=re.IGNORECASE)
    if category_match:
        markers["category"] = category_match.group(1).replace(" ", "").lower()

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

    if "лючок" in normalized or ("напольн" in normalized and "короб" in normalized):
        markers["installation_kind"] = "floor_box"
    elif re.search(r"\brj[\s-]?45\b", normalized, flags=re.IGNORECASE) and "розетк" in normalized:
        markers["installation_kind"] = "outlet_module"

    length_match = re.search(r"(\d+(?:[.,]\d+)?)\s*м\b", normalized)
    if length_match:
        markers["length_m"] = length_match.group(1).replace(",", ".")

    current_match = re.search(r"(\d+(?:[.,]\d+)?)\s*а\b", normalized)
    if current_match:
        markers["current_a"] = current_match.group(1).replace(",", ".")

    if "zero u" in normalized:
        markers["zero_u"] = "yes"
        markers["rack_unit"] = "zero u"
    if markers.get("rack_unit") == "1":
        markers["rack_1u"] = "yes"
    if "19 inch" in normalized:
        markers["rack_size"] = "19 inch"
        markers["rack_mount_19"] = "yes"

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
    entity_type = classify_item_type(combined_text, synonyms=synonyms)
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
