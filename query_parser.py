from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Tuple

from catalog_search import (
    clean_text_value,
    classify_item_type,
    derive_branch_from_text,
    extract_item_markers,
    normalize_text,
    tokenize,
)
from taxonomy_registry import classify_entity_type_from_registry, entity_family_for_type

WEAK_FAMILY_CONFIDENCE_FAMILIES = {"", "other", "cable", "wire", "coax", "rack", "sensor"}
SECTION_ROW_DEFAULTS = {
    "скс",
    "лвс",
    "оборудование",
    "сетевая инфраструктура",
    "система кабельных лотков",
    "крепеж и аксессуары",
    "наименование оборудования материалов и кабелей",
}
ARTICLE_PATTERNS = (
    r"(?:^|[\s,;/\(\)])(?:артикул|арт\.?|sku|part\s*number|partnumber|vendor\s*code)\s*[:№#-]?\s*(.+?)\s*$",
)
CABLE_DESIGNATION_BASE_STOPWORDS = {
    "силовой",
    "контрольный",
    "монтажный",
    "однопроволочный",
    "многопроволочный",
    "ок",
    "n",
    "pe",
    "тртс",
    "барабан",
}
GENERIC_CABLE_DESIGNATION_TOKENS = {
    "a",
    "а",
    "кабель",
    "провод",
    "артикул",
    "арт",
    "sku",
}


@dataclass(frozen=True)
class ParsedQuerySpec:
    original_text: str
    normalized_text: str
    tokens: Tuple[str, ...]
    row_type: str
    entity_type: str
    query_family: str
    family_confidence: float
    markers: Dict[str, str]
    branch_hint: str
    parser_source: str
    extracted_article: str
    designation_signature: str
    dimension_pairs: Tuple[str, ...]
    dimension_triples: Tuple[str, ...]
    dimension_lengths: Tuple[str, ...]
    dimension_diameters: Tuple[str, ...]

    def to_feature_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["tokens"] = list(self.tokens)
        data["attributes"] = dict(self.markers)
        data["markers"] = dict(self.markers)
        data["family_confidence"] = float(self.family_confidence)
        return data


def detect_query_row_type(text: str, taxonomy_rules: Mapping[str, Any] | None = None) -> str:
    normalized = normalize_text(clean_text_value(text))
    if not normalized:
        return "empty"
    if normalized in SECTION_ROW_DEFAULTS:
        return "section"
    patterns = list((taxonomy_rules or {}).get("section_row_patterns", []) or [])
    for pattern in patterns:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return "section"
    tokens = tokenize(normalized)
    if normalized.startswith("раздел"):
        return "section"
    if normalized.startswith("наименование ") and len(tokens) <= 8:
        return "section"
    if len(tokens) <= 4 and not re.search(r"\d", normalized):
        for token in ("шкафы", "кабели", "коммутация", "электрика", "датчики", "свет", "аксессуары", "оборудование"):
            if normalized.startswith(token):
                return "section"
    return "item"


def extract_query_article_from_text(query: str) -> str:
    cleaned_query = clean_text_value(query)
    if not cleaned_query:
        return ""
    collapsed = re.sub(r"\s+", " ", cleaned_query).strip()
    for pattern in ARTICLE_PATTERNS:
        match = re.search(pattern, collapsed, flags=re.IGNORECASE)
        if not match:
            continue
        article = re.sub(r"\s+", " ", match.group(1)).strip(" \t\r\n,;:.")
        if article:
            return article
    return ""


def _normalize_dimension_value(value: str) -> str:
    cleaned = clean_text_value(value).replace(" ", "").replace(",", ".").replace("х", "x")
    cleaned = re.sub(r"[^0-9.x-]", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(".x-")


def _canonical_dimension_signature(values: Tuple[str, ...]) -> str:
    normalized_values = [_normalize_dimension_value(value) for value in values if _normalize_dimension_value(value)]
    if len(normalized_values) == 2:
        return "x".join(sorted(normalized_values, key=lambda item: float(item)))
    if len(normalized_values) == 3:
        numeric_values = [float(item) for item in normalized_values]
        max_index = max(range(len(numeric_values)), key=numeric_values.__getitem__)
        length_value = normalized_values[max_index]
        pair_values = [normalized_values[index] for index in range(3) if index != max_index]
        return "x".join(sorted(pair_values, key=lambda item: float(item)) + [length_value])
    return "x".join(normalized_values)


def _canonical_cable_designation_dimension(values: Tuple[str, ...]) -> str:
    normalized_values = tuple(
        _normalize_dimension_value(value)
        for value in values
        if _normalize_dimension_value(value)
    )
    if not normalized_values:
        return ""
    return "x".join(normalized_values)


def extract_dimension_signatures(text: str) -> Dict[str, set[str]]:
    normalized = clean_text_value(text).lower().replace("ё", "е")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    signatures: Dict[str, set[str]] = {
        "pairs": set(),
        "triples": set(),
        "lengths": set(),
        "diameters": set(),
    }
    if not normalized:
        return signatures

    for match in re.finditer(
        r"(\d+(?:[.,]\d+)?)\s*[xх×*/]\s*(\d+(?:[.,]\d+)?)(?:\s*[xх×*/]\s*(\d+(?:[.,]\d+)?))?",
        normalized,
        flags=re.IGNORECASE,
    ):
        values = tuple(group for group in match.groups() if group)
        if len(values) == 2:
            signatures["pairs"].add(_canonical_dimension_signature(values))
        elif len(values) == 3:
            signatures["triples"].add(_canonical_dimension_signature(values))

    for match in re.finditer(r"\bl\s*=?\s*(\d+(?:[.,]\d+)?)\b", normalized, flags=re.IGNORECASE):
        signatures["lengths"].add(_normalize_dimension_value(match.group(1)))
    for match in re.finditer(r"\b(\d+(?:[.,]\d+)?)\s*(?:мм|mm)\b", normalized, flags=re.IGNORECASE):
        signatures["lengths"].add(_normalize_dimension_value(match.group(1)))
    for match in re.finditer(
        r"\b(?:d|dn|ø)\s*=?\s*(\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?)\b",
        normalized,
        flags=re.IGNORECASE,
    ):
        diameter_value = re.sub(r"\s+", "", match.group(1)).replace(",", ".").replace("–", "-")
        if diameter_value:
            signatures["diameters"].add(diameter_value)
    return signatures


def extract_cable_designation_signature(text: str, *, synonyms: Mapping[str, str] | None = None) -> Dict[str, str]:
    cleaned_text = clean_text_value(text)
    if not cleaned_text:
        return {}
    normalized = cleaned_text.lower().replace("ё", "е")
    normalized = re.sub(
        r"\b(?:кабель|провод|артикул|арт\.?|sku|part\s*number|partnumber|vendor\s*code)\b",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\s+", " ", normalized).strip(" \t\r\n,;:/-")
    if not normalized:
        return {}
    dimension_match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*[xх×*/]\s*(\d+(?:[.,]\d+)?)(?:\s*[xх×*/]\s*(\d+(?:[.,]\d+)?))?",
        normalized,
        flags=re.IGNORECASE,
    )
    if not dimension_match:
        return {}
    values = tuple(group for group in dimension_match.groups() if group)
    dimension_signature = _canonical_cable_designation_dimension(values)
    if not dimension_signature:
        return {}
    base_part = normalized[: dimension_match.start()]
    base_part = re.sub(r"[\(\)\[\],;:]+", " ", base_part)
    base_tokens = [
        clean_text_value(token).lower()
        for token in re.findall(r"\w+", base_part, flags=re.IGNORECASE)
        if len(clean_text_value(token)) >= 2
        and not clean_text_value(token).isdigit()
        and clean_text_value(token).lower()
        not in (GENERIC_CABLE_DESIGNATION_TOKENS | CABLE_DESIGNATION_BASE_STOPWORDS)
    ]
    if not base_tokens:
        return {}
    base_signature = " ".join(base_tokens)
    return {
        "base": base_signature,
        "dimension": dimension_signature,
        "signature": f"{base_signature}|{dimension_signature}",
        "base_tokens": base_tokens,
    }


def parse_query_spec(query: str, *, taxonomy_rules: Mapping[str, Any] | None = None) -> ParsedQuerySpec:
    rules = dict(taxonomy_rules or {})
    synonyms = rules.get("synonyms", {})
    original = clean_text_value(query)
    normalized = normalize_text(original, synonyms=synonyms)
    tokens = tuple(tokenize(normalized))
    markers = extract_item_markers(
        original,
        attribute_patterns=rules.get("attribute_patterns", {}),
        synonyms=synonyms,
    )
    registry_match = classify_entity_type_from_registry(original, rules=rules, markers=markers)
    entity_type = classify_item_type(original, synonyms=synonyms, taxonomy_rules=rules)
    entity_family = entity_family_for_type(entity_type, rules)
    family_confidence = 0.35 if entity_family in WEAK_FAMILY_CONFIDENCE_FAMILIES else 0.72
    if registry_match is not None:
        registry_entity_type = clean_text_value(registry_match.get("entity_type")) or entity_type
        registry_family = entity_family_for_type(registry_entity_type, rules)
        registry_confidence = float(registry_match.get("confidence") or family_confidence)
        should_apply_registry = (
            registry_family == entity_family
            or entity_family in {"", "other"} and registry_confidence >= 0.72
            or entity_family in {"cable", "wire", "coax", "rack", "sensor"} and registry_confidence >= 0.62
        )
        if should_apply_registry:
            entity_type = registry_entity_type
            entity_family = registry_family
            family_confidence = registry_confidence

    branch_hint = derive_branch_from_text(
        original,
        synonyms=synonyms,
        taxonomy_rules=rules,
    )
    if branch_hint == "прочее":
        branch_hint = ""

    dimension_signatures = extract_dimension_signatures(original)
    designation_signature = clean_text_value(extract_cable_designation_signature(original, synonyms=synonyms).get("signature"))

    return ParsedQuerySpec(
        original_text=original,
        normalized_text=normalized,
        tokens=tokens,
        row_type=detect_query_row_type(original, rules),
        entity_type=entity_type,
        query_family=entity_family,
        family_confidence=family_confidence,
        markers={str(key): str(value) for key, value in markers.items() if clean_text_value(value)},
        branch_hint=branch_hint,
        parser_source="local",
        extracted_article=extract_query_article_from_text(original),
        designation_signature=designation_signature,
        dimension_pairs=tuple(sorted(dimension_signatures["pairs"])),
        dimension_triples=tuple(sorted(dimension_signatures["triples"])),
        dimension_lengths=tuple(sorted(dimension_signatures["lengths"])),
        dimension_diameters=tuple(sorted(dimension_signatures["diameters"])),
    )
