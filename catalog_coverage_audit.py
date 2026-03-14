from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from catalog_schema import CANONICAL_ARTICLE_COLUMN, CANONICAL_NAME_COLUMN
from catalog_search import (
    SEARCH_BASE_COLUMNS,
    SEARCH_DERIVED_COLUMNS,
    build_search_projection_row,
    clean_text_value,
)
from matcher import MATCH_MODE_EXACT, ReMoMatcher

logger = logging.getLogger(__name__)

CATALOG_COVERAGE_AUDIT_VERSION = 4

TARGET_FAMILY_GROUPS = {
    "patch_panel": "patch_panel",
    "patch_cord": "patch_cord",
    "keystone": "keystone_rj45",
    "rj45_connector": "keystone_rj45",
    "rj45_outlet": "keystone_rj45",
    "bulk_twisted_pair": "twisted_pair",
    "iec_power_cable": "iec_power_cable",
    "optical_cross": "optical_cross",
    "optical_patch_cord": "optical_patch_cord",
    "ats_sts": "ats_sts",
    "airflow_blanking_panel": "airflow_accessories",
    "rack_accessory_strict": "rack_accessories",
}

FAMILY_GROUP_LABELS = {
    "patch_panel": "patch_panel",
    "patch_cord": "patch_cord",
    "keystone_rj45": "keystone/rj45",
    "twisted_pair": "twisted_pair",
    "iec_power_cable": "iec_power_cable",
    "optical_cross": "optical_cross",
    "optical_patch_cord": "optical_patch_cord",
    "ats_sts": "ats_sts",
    "airflow_accessories": "airflow/accessories",
    "rack_accessories": "rack blank/brush",
}

HEADER_QUERY_VALUES = {
    "наименование",
    "наименование оборудования, материалов и кабелей",
    "nomenclature",
}


@dataclass(frozen=True)
class CoverageAuditSummary:
    families_total: int
    rows_analyzed: int
    catalog_missing_family: int
    catalog_has_family_but_no_compatible_specs: int
    catalog_has_compatible_candidates: int
    gap_reason_counts: dict[str, int]


@dataclass(frozen=True)
class CoverageAuditRow:
    run_row_number: int
    query_text: str
    query_family: str
    query_family_group: str
    diagnosis: str
    gap_reason_code: str
    gap_reason_counts: dict[str, int]
    top_gap_reasons: list[dict[str, Any]]
    current_resolution_source: str
    current_compatibility_status: str
    same_family_candidates_count: int
    compatible_candidates_count: int
    candidate_examples: list[dict[str, str]]


@dataclass
class _QueryAuditContext:
    run_row_number: int
    query_text: str
    query_features: dict[str, Any]
    query_family: str
    query_family_group: str | None
    current_resolution_source: str
    current_compatibility_status: str
    same_family_candidates_count: int = 0
    compatible_candidates_count: int = 0
    compatible_examples: list[tuple[float, dict[str, str]]] = field(default_factory=list)
    related_examples: list[tuple[float, dict[str, str]]] = field(default_factory=list)
    gap_reason_counts: Counter[str] = field(default_factory=Counter)
    gap_reason_examples: dict[str, tuple[float, dict[str, str]]] = field(default_factory=dict)


def _safe_catalog_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _mtimes_match(left: Any, right: Any) -> bool:
    try:
        left_value = float(left)
        right_value = float(right)
    except (TypeError, ValueError):
        return left is None and right is None
    return abs(left_value - right_value) < 1e-6


def is_catalog_coverage_audit_fresh(
    payload: dict[str, Any] | None,
    *,
    run_id: str,
    catalog_source_path: Path,
    catalog_source_kind: str,
) -> bool:
    if not payload:
        return False
    return (
        int(payload.get("audit_version") or 0) == CATALOG_COVERAGE_AUDIT_VERSION
        and
        str(payload.get("run_id") or "") == str(run_id)
        and str(payload.get("catalog_source_path") or "") == str(Path(catalog_source_path))
        and str(payload.get("catalog_source_kind") or "") == str(catalog_source_kind)
        and _mtimes_match(payload.get("catalog_mtime"), _safe_catalog_mtime(Path(catalog_source_path)))
    )


class _AuditMatcherAdapter:
    def __init__(self) -> None:
        matcher = ReMoMatcher.__new__(ReMoMatcher)
        matcher.match_mode = MATCH_MODE_EXACT
        matcher.taxonomy_rules = ReMoMatcher._load_taxonomy_rules(matcher)
        self.matcher = matcher

    @property
    def taxonomy_rules(self) -> dict[str, Any]:
        return dict(getattr(self.matcher, "taxonomy_rules", {}) or {})

    def extract_query_features(self, query_text: str) -> dict[str, Any]:
        return self.matcher._extract_query_features(query_text)

    def entity_family(self, entity_type: str) -> str:
        return self.matcher._entity_family(entity_type)

    def compatibility_label(self, query_features: dict[str, Any], item: dict[str, Any]) -> str:
        return self.matcher._compatibility_label(query_features, item)

    def incompatibility_reason(self, query_features: dict[str, Any], item: dict[str, Any]) -> str:
        return self.matcher._explain_incompatibility(query_features, item)

    def normalize_candidate_item(self, row: dict[str, Any], *, prefer_precomputed: bool) -> dict[str, Any] | None:
        name = clean_text_value(row.get(CANONICAL_NAME_COLUMN))
        if not name:
            return None

        projected = build_search_projection_row(row, taxonomy_rules=self.taxonomy_rules)
        entity_type = clean_text_value(projected.get("search_entity_type"))
        branch_path = clean_text_value(projected.get("search_branch_path"))
        normalized_name = clean_text_value(projected.get("search_normalized_name"))
        try:
            item_markers = json.loads(clean_text_value(projected.get("search_item_markers_json")) or "{}")
        except json.JSONDecodeError:
            item_markers = {}

        if prefer_precomputed:
            precomputed_entity_type = clean_text_value(row.get("search_entity_type"))
            precomputed_branch_path = clean_text_value(row.get("search_branch_path"))
            precomputed_normalized_name = clean_text_value(row.get("search_normalized_name"))
            try:
                precomputed_item_markers = json.loads(clean_text_value(row.get("search_item_markers_json")) or "{}")
            except json.JSONDecodeError:
                precomputed_item_markers = {}

            entity_type = entity_type or precomputed_entity_type
            branch_path = branch_path or precomputed_branch_path
            normalized_name = normalized_name or precomputed_normalized_name or self.matcher._normalize_text(name)
            if not item_markers and isinstance(precomputed_item_markers, dict):
                item_markers = precomputed_item_markers

        return {
            "name": name,
            "article": clean_text_value(row.get(CANONICAL_ARTICLE_COLUMN)),
            "branch_path": branch_path,
            "normalized_name": normalized_name,
            "entity_type": entity_type,
            "item_markers": item_markers if isinstance(item_markers, dict) else {},
        }


def _family_group_for(query_family: str) -> str | None:
    return TARGET_FAMILY_GROUPS.get(str(query_family or "").strip().lower())


def _candidate_family_scope(query_family: str) -> set[str]:
    family = str(query_family or "").strip().lower()
    if family == "keystone":
        return {"keystone", "rj45_outlet"}
    if family == "rj45_outlet":
        return {"rj45_outlet", "keystone"}
    return {family}


def _find_query_column(df_result: pd.DataFrame) -> str:
    for column in df_result.columns:
        normalized = str(column).strip().lower()
        if "наименование" in normalized and "оборудован" in normalized:
            return str(column)
    if len(df_result.columns) > 1:
        return str(df_result.columns[1])
    if len(df_result.columns) == 1:
        return str(df_result.columns[0])
    raise ValueError("Result dataframe has no columns")


def _should_skip_query_text(query_text: str) -> bool:
    cleaned = clean_text_value(query_text)
    if not cleaned:
        return True
    lowered = cleaned.strip().lower()
    return lowered in HEADER_QUERY_VALUES or lowered == "nan"


def _should_include_row(
    *,
    query_family_group: str | None,
    current_resolution_source: str,
    current_compatibility_status: str,
) -> bool:
    if current_resolution_source == "unresolved":
        return True
    if current_compatibility_status == "rejected_incompatible_gemini":
        return True
    if query_family_group and current_compatibility_status != "compatible":
        return True
    return False


def _candidate_score(adapter: _AuditMatcherAdapter, query_features: dict[str, Any], item: dict[str, Any], label: str) -> float:
    query_tokens = set(query_features.get("tokens") or [])
    candidate_tokens = set(
        adapter.matcher._tokenize(
            " ".join(
                filter(
                    None,
                    [
                        clean_text_value(item.get("normalized_name")),
                        clean_text_value(item.get("branch_path")),
                    ],
                )
            )
        )
    )
    score = float(len(query_tokens & candidate_tokens))
    if label == "compatible":
        score += 100.0
    if adapter.entity_family(item.get("entity_type", "")) == adapter.entity_family(query_features.get("entity_type", "")):
        score += 5.0
    return score


def _store_example(
    pool: list[tuple[float, dict[str, str]]],
    *,
    score: float,
    example: dict[str, str],
    max_items: int,
) -> None:
    pool.append((score, example))
    pool.sort(key=lambda item: item[0], reverse=True)
    del pool[max_items:]


def _gap_reason_from_incompatibility(reason: str) -> str:
    normalized = clean_text_value(reason)
    if not normalized:
        return "other_spec_mismatch"
    if normalized == "catalog_missing_family":
        return "missing_family"
    if "category" in normalized:
        return "category_mismatch"
    if "shield" in normalized:
        return "shielding_mismatch"
    if "connector" in normalized:
        return "connector_mismatch"
    if "component" in normalized:
        return "component_kind_mismatch"
    if "installation" in normalized or normalized == "floor_box_vs_power_item":
        return "installation_kind_mismatch"
    if "port_count" in normalized:
        return "port_count_mismatch"
    if "fiber" in normalized or "optical_marker" in normalized:
        return "fiber_mode_mismatch"
    if "environment" in normalized:
        return "environment_mismatch"
    if "rack" in normalized or "form_factor" in normalized or "airflow" in normalized:
        return "rack_form_factor_mismatch"
    return "other_spec_mismatch"


def _build_gap_reason_details(context: _QueryAuditContext) -> tuple[str, dict[str, int], list[dict[str, Any]]]:
    if context.same_family_candidates_count == 0:
        return "missing_family", {"missing_family": 1}, []

    if not context.gap_reason_counts:
        return "other_spec_mismatch", {}, []

    sorted_reasons = sorted(
        context.gap_reason_counts.items(),
        key=lambda item: (-int(item[1]), str(item[0])),
    )
    top_count = int(sorted_reasons[0][1])
    top_reason_codes = [reason_code for reason_code, count in sorted_reasons if int(count) == top_count]
    primary_reason = top_reason_codes[0] if len(top_reason_codes) == 1 else "multiple_spec_mismatches"

    top_gap_reasons: list[dict[str, Any]] = []
    for reason_code, count in sorted_reasons[:3]:
        example_entry = context.gap_reason_examples.get(reason_code)
        example = dict(example_entry[1]) if example_entry else {}
        top_gap_reasons.append(
            {
                "reason_code": reason_code,
                "count": int(count),
                "example": example,
            }
        )

    return primary_reason, {reason_code: int(count) for reason_code, count in sorted_reasons}, top_gap_reasons


def _iter_catalog_rows(
    catalog_source_path: Path,
    *,
    chunksize: int = 10_000,
) -> Any:
    required_columns = set(SEARCH_BASE_COLUMNS) | set(SEARCH_DERIVED_COLUMNS)
    for chunk in pd.read_csv(
        catalog_source_path,
        sep=";",
        dtype=str,
        keep_default_na=False,
        chunksize=chunksize,
        usecols=lambda column_name: column_name in required_columns,
        low_memory=False,
    ):
        yield chunk


def _build_focus_contexts(
    df_result: pd.DataFrame,
    *,
    adapter: _AuditMatcherAdapter,
) -> list[_QueryAuditContext]:
    query_column = _find_query_column(df_result)
    contexts: list[_QueryAuditContext] = []
    for row_index, row in df_result.iterrows():
        query_text = clean_text_value(row.get(query_column))
        if _should_skip_query_text(query_text):
            continue
        current_resolution_source = clean_text_value(row.get("Источник решения"))
        current_compatibility_status = clean_text_value(row.get("Совместимость решения"))
        query_features = adapter.extract_query_features(query_text)
        query_family = adapter.entity_family(query_features.get("entity_type", ""))
        family_group = _family_group_for(query_family)
        if not _should_include_row(
            query_family_group=family_group,
            current_resolution_source=current_resolution_source,
            current_compatibility_status=current_compatibility_status,
        ):
            continue
        contexts.append(
            _QueryAuditContext(
                run_row_number=int(row_index) + 2,
                query_text=query_text,
                query_features=query_features,
                query_family=query_family,
                query_family_group=family_group,
                current_resolution_source=current_resolution_source,
                current_compatibility_status=current_compatibility_status,
            )
        )
    return contexts


def _build_audit_row(
    context: _QueryAuditContext,
    *,
    example_limit: int,
) -> CoverageAuditRow:
    if context.query_family_group is None:
        diagnosis = "non_target_family"
    elif context.same_family_candidates_count == 0:
        diagnosis = "catalog_missing_family"
    elif context.compatible_candidates_count == 0:
        diagnosis = "catalog_has_family_but_no_compatible_specs"
    else:
        diagnosis = "catalog_has_compatible_candidates"

    example_pool = context.compatible_examples if context.compatible_examples else context.related_examples
    examples = [example for _, example in example_pool[:example_limit]]
    gap_reason_code, gap_reason_counts, top_gap_reasons = _build_gap_reason_details(context)
    if diagnosis not in {"catalog_missing_family", "catalog_has_family_but_no_compatible_specs"}:
        gap_reason_code = ""
        gap_reason_counts = {}
        top_gap_reasons = []
    return CoverageAuditRow(
        run_row_number=context.run_row_number,
        query_text=context.query_text,
        query_family=context.query_family,
        query_family_group=context.query_family_group or "",
        diagnosis=diagnosis,
        gap_reason_code=gap_reason_code,
        gap_reason_counts=gap_reason_counts,
        top_gap_reasons=top_gap_reasons,
        current_resolution_source=context.current_resolution_source,
        current_compatibility_status=context.current_compatibility_status,
        same_family_candidates_count=context.same_family_candidates_count,
        compatible_candidates_count=context.compatible_candidates_count,
        candidate_examples=examples,
    )


def _build_summary(rows: list[CoverageAuditRow]) -> tuple[CoverageAuditSummary, dict[str, dict[str, int]]]:
    relevant_rows = [row for row in rows if row.diagnosis != "non_target_family"]
    diagnosis_counter = Counter(row.diagnosis for row in relevant_rows)
    gap_reason_counter = Counter(
        row.gap_reason_code
        for row in relevant_rows
        if row.diagnosis in {"catalog_missing_family", "catalog_has_family_but_no_compatible_specs"} and row.gap_reason_code
    )
    family_breakdown: dict[str, dict[str, int]] = {}
    for row in relevant_rows:
        family_key = row.query_family_group or row.query_family
        bucket = family_breakdown.setdefault(
            family_key,
            {
                "rows": 0,
                "catalog_missing_family": 0,
                "catalog_has_family_but_no_compatible_specs": 0,
                "catalog_has_compatible_candidates": 0,
            },
        )
        bucket["rows"] += 1
        bucket[row.diagnosis] += 1

    summary = CoverageAuditSummary(
        families_total=len(family_breakdown),
        rows_analyzed=len(relevant_rows),
        catalog_missing_family=diagnosis_counter.get("catalog_missing_family", 0),
        catalog_has_family_but_no_compatible_specs=diagnosis_counter.get(
            "catalog_has_family_but_no_compatible_specs",
            0,
        ),
        catalog_has_compatible_candidates=diagnosis_counter.get("catalog_has_compatible_candidates", 0),
        gap_reason_counts=dict(sorted(gap_reason_counter.items())),
    )
    return summary, family_breakdown


def build_catalog_coverage_audit(
    df_result: pd.DataFrame,
    *,
    run_id: str,
    catalog_source_path: Path,
    catalog_source_kind: str,
    example_limit: int = 3,
    chunksize: int = 10_000,
) -> dict[str, Any]:
    adapter = _AuditMatcherAdapter()
    contexts = _build_focus_contexts(df_result, adapter=adapter)
    relevant_contexts = [context for context in contexts if context.query_family_group is not None]

    if relevant_contexts:
        contexts_by_candidate_family: dict[str, list[_QueryAuditContext]] = defaultdict(list)
        relevant_families: set[str] = set()
        for context in relevant_contexts:
            for family in _candidate_family_scope(context.query_family):
                contexts_by_candidate_family[family].append(context)
                relevant_families.add(family)

        prefer_precomputed = str(catalog_source_kind).strip().lower() == "search"
        for chunk in _iter_catalog_rows(Path(catalog_source_path), chunksize=chunksize):
            for record in chunk.to_dict("records"):
                item = adapter.normalize_candidate_item(record, prefer_precomputed=prefer_precomputed)
                if item is None:
                    continue
                candidate_family = adapter.entity_family(item.get("entity_type", ""))
                if candidate_family not in relevant_families:
                    continue
                candidate_contexts = contexts_by_candidate_family.get(candidate_family, [])
                if not candidate_contexts:
                    continue

                for context in candidate_contexts:
                    context.same_family_candidates_count += 1
                    compatibility_label = adapter.compatibility_label(context.query_features, item)
                    incompatibility_reason = adapter.incompatibility_reason(context.query_features, item)
                    example = {
                        "name": clean_text_value(item.get("name")),
                        "article": clean_text_value(item.get("article")),
                        "family": candidate_family,
                        "compatibility": compatibility_label,
                        "reason": incompatibility_reason,
                    }
                    score = _candidate_score(adapter, context.query_features, item, compatibility_label)
                    if compatibility_label == "compatible":
                        context.compatible_candidates_count += 1
                        _store_example(
                            context.compatible_examples,
                            score=score,
                            example=example,
                            max_items=max(3, example_limit),
                        )
                    else:
                        gap_reason_code = _gap_reason_from_incompatibility(incompatibility_reason)
                        context.gap_reason_counts[gap_reason_code] += 1
                        current_gap_example = context.gap_reason_examples.get(gap_reason_code)
                        if current_gap_example is None or score > float(current_gap_example[0]):
                            context.gap_reason_examples[gap_reason_code] = (score, dict(example))
                        _store_example(
                            context.related_examples,
                            score=score,
                            example=example,
                            max_items=max(3, example_limit),
                        )

    rows = [_build_audit_row(context, example_limit=example_limit) for context in contexts]
    summary, family_breakdown = _build_summary(rows)
    payload = {
        "audit_version": CATALOG_COVERAGE_AUDIT_VERSION,
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "catalog_source_path": str(Path(catalog_source_path)),
        "catalog_source_kind": str(catalog_source_kind),
        "catalog_mtime": _safe_catalog_mtime(Path(catalog_source_path)),
        "summary": asdict(summary),
        "family_breakdown": family_breakdown,
        "rows": [asdict(row) for row in rows],
    }
    logger.info(
        "Catalog coverage audit built: run=%s rows=%s analyzed=%s catalog=%s",
        run_id,
        len(rows),
        summary.rows_analyzed,
        catalog_source_path,
    )
    return payload


def prepare_catalog_coverage_audit_table(payload: dict[str, Any]) -> pd.DataFrame:
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return pd.DataFrame()
    prepared_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if clean_text_value(row.get("diagnosis")) == "non_target_family":
            continue
        examples = row.get("candidate_examples", [])
        example_strings: list[str] = []
        if isinstance(examples, list):
            for example in examples:
                if not isinstance(example, dict):
                    continue
                name = clean_text_value(example.get("name"))
                article = clean_text_value(example.get("article"))
                reason = clean_text_value(example.get("reason"))
                compatibility = clean_text_value(example.get("compatibility"))
                parts = [name]
                if article:
                    parts.append(f"[{article}]")
                if compatibility:
                    parts.append(compatibility)
                if reason:
                    parts.append(reason)
                example_strings.append(" | ".join(parts))
        gap_reason_strings: list[str] = []
        top_gap_reasons = row.get("top_gap_reasons", [])
        if isinstance(top_gap_reasons, list):
            for gap_reason in top_gap_reasons:
                if not isinstance(gap_reason, dict):
                    continue
                reason_code = clean_text_value(gap_reason.get("reason_code"))
                count = int(gap_reason.get("count", 0) or 0)
                example = gap_reason.get("example") or {}
                example_name = clean_text_value(example.get("name")) if isinstance(example, dict) else ""
                parts = [reason_code]
                if count:
                    parts.append(str(count))
                if example_name:
                    parts.append(example_name)
                gap_reason_strings.append(" | ".join(parts))
        prepared_rows.append(
            {
                "Строка": row.get("run_row_number"),
                "Запрос": row.get("query_text"),
                "Семейство": row.get("query_family"),
                "Группа": FAMILY_GROUP_LABELS.get(
                    clean_text_value(row.get("query_family_group")),
                    clean_text_value(row.get("query_family_group")),
                ),
                "Диагноз": row.get("diagnosis"),
                "Gap reason": row.get("gap_reason_code"),
                "Источник решения": row.get("current_resolution_source"),
                "Совместимость решения": row.get("current_compatibility_status"),
                "Кандидатов того же семейства": row.get("same_family_candidates_count"),
                "Совместимых кандидатов": row.get("compatible_candidates_count"),
                "Top mismatch reasons": "\n".join(gap_reason_strings),
                "Примеры кандидатов": "\n".join(example_strings),
            }
        )
    return pd.DataFrame(prepared_rows)


def prepare_catalog_coverage_family_table(payload: dict[str, Any]) -> pd.DataFrame:
    breakdown = payload.get("family_breakdown", {})
    if not isinstance(breakdown, dict):
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for family_key, stats in breakdown.items():
        if not isinstance(stats, dict):
            continue
        rows.append(
            {
                "Семейство": FAMILY_GROUP_LABELS.get(str(family_key), str(family_key)),
                "Строк": int(stats.get("rows", 0)),
                "Пробел каталога": int(stats.get("catalog_missing_family", 0)),
                "Есть family, нет specs": int(stats.get("catalog_has_family_but_no_compatible_specs", 0)),
                "Есть совместимые кандидаты": int(stats.get("catalog_has_compatible_candidates", 0)),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(by=["Строк", "Семейство"], ascending=[False, True], ignore_index=True)


def prepare_catalog_gap_reason_table(payload: dict[str, Any]) -> pd.DataFrame:
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        return pd.DataFrame()
    gap_reason_counts = summary.get("gap_reason_counts", {})
    if not isinstance(gap_reason_counts, dict):
        return pd.DataFrame()
    rows = [
        {"Gap reason": str(reason_code), "Строк": int(count)}
        for reason_code, count in gap_reason_counts.items()
    ]
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(by=["Строк", "Gap reason"], ascending=[False, True], ignore_index=True)
