from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import pandas as pd

from taxonomy_registry import audited_families as registry_audited_families, load_registry_taxonomy_rules

MATCH_DIAGNOSTICS_VERSION = 5
MISSING_POSITION_TEXT = "Позиция отсутствует"

HEADER_QUERY_VALUES = {
    "наименование",
    "наименование оборудования, материалов и кабелей",
    "nomenclature",
}

EARLY_FAILURE_STAGES = {"catalog_gap", "local_recall", "compatibility_filter"}
INPUT_REASON_CODES = {"empty_query", "section_row_detected", "header_like_row"}
GEMINI_REASON_CODES = {
    "gemini_rejected_all_candidates",
    "gemini_returned_no_valid_candidate",
    "gemini_rejected_incompatible",
    "gemini_family_gate_rejected",
    "gemini_selected_incompatible_candidate",
    "candidate_tiebreaker_rejected",
    "family_router_uncertain",
    "article_conflict_rejected_by_gemini",
}
FALLBACK_REASON_CODES = {
    "strict_fallback_family_mismatch",
    "strict_class_requires_compatible_match",
    "article_conflict_rejected",
    "series_match_ambiguous",
}
GENERIC_CATALOG_GAP_CODES = {
    "resolved",
    "no_compatible_candidates",
    "strict_class_no_compatible_candidate",
    "strict_class_requires_compatible_match",
    "no_confirmed_compatible_candidate",
    "gemini_rejected_all_candidates",
    "gemini_returned_no_valid_candidate",
}

REASON_CLASS_LABELS = {
    "catalog_gap": "catalog gap",
    "matcher_retrieval_or_ranking": "retrieval/ranking",
    "gemini_or_decision_policy": "Gemini/policy",
    "input_or_query_shape": "input/query shape",
    "not_audited_family": "not audited family",
    "runtime_error": "runtime error",
    "resolved": "resolved",
}

AUDITED_QUERY_FAMILIES = registry_audited_families(load_registry_taxonomy_rules())


def _clean_text_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_reason_code(value: Any) -> str:
    reason_code = _clean_text_value(value)
    return reason_code or "resolved"


def infer_reason_class(stage_of_failure: str, reason_code: str) -> str:
    stage = _clean_text_value(stage_of_failure) or "runtime_error"
    code = _normalize_reason_code(reason_code)
    if stage == "resolved":
        return "resolved"
    if stage in {"query_input", "query_classification"} or code in INPUT_REASON_CODES:
        return "input_or_query_shape"
    if stage == "catalog_gap":
        return "catalog_gap"
    if stage in {"gemini_selection", "fallback_policy"} or code in GEMINI_REASON_CODES or code in FALLBACK_REASON_CODES:
        return "gemini_or_decision_policy"
    if stage == "runtime_error" or code == "runtime_exception":
        return "runtime_error"
    return "matcher_retrieval_or_ranking"


def _infer_coverage_scope(query_family: str) -> str:
    normalized_family = _clean_text_value(query_family)
    if normalized_family in AUDITED_QUERY_FAMILIES:
        return "audited_family"
    return "non_target_family"


def _build_canonical_fields(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    pipeline_stage = _clean_text_value(normalized.get("pipeline_stage")) or _clean_text_value(normalized.get("stage_of_failure")) or "runtime_error"
    pipeline_reason_code = _normalize_reason_code(
        normalized.get("pipeline_reason_code") or normalized.get("reason_code")
    )
    root_cause_class = _clean_text_value(normalized.get("root_cause_class")) or _clean_text_value(normalized.get("reason_class"))
    if not root_cause_class:
        root_cause_class = infer_reason_class(pipeline_stage, pipeline_reason_code)
    root_cause_code = _normalize_reason_code(
        normalized.get("root_cause_code") or normalized.get("reason_code") or pipeline_reason_code
    )
    coverage_scope = _clean_text_value(normalized.get("coverage_scope")) or _infer_coverage_scope(
        _clean_text_value(normalized.get("query_family"))
    )

    normalized["pipeline_stage"] = pipeline_stage
    normalized["pipeline_reason_code"] = pipeline_reason_code
    normalized["root_cause_class"] = root_cause_class
    normalized["root_cause_code"] = root_cause_code
    normalized["coverage_scope"] = coverage_scope
    normalized["catalog_gap_reason_code"] = _clean_text_value(normalized.get("catalog_gap_reason_code"))

    # Backward-compatible aliases used by older UI/exports.
    normalized["stage_of_failure"] = pipeline_stage
    normalized["reason_code"] = root_cause_code
    normalized["reason_class"] = root_cause_class
    return normalized


def is_match_diagnostics_fresh(payload: dict[str, Any] | None, *, run_id: str) -> bool:
    if not payload:
        return False
    return (
        _safe_int(payload.get("diagnostics_version")) == MATCH_DIAGNOSTICS_VERSION
        and _clean_text_value(payload.get("run_id")) == _clean_text_value(run_id)
    )


def _coverage_rows_by_number(coverage_audit_payload: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not isinstance(coverage_audit_payload, dict):
        return {}
    rows = coverage_audit_payload.get("rows")
    if not isinstance(rows, list):
        return {}
    prepared: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        prepared[_safe_int(row.get("run_row_number"))] = row
    return prepared


def _row_display_examples(candidate_snapshots: dict[str, Any], coverage_row: dict[str, Any] | None) -> list[dict[str, str]]:
    top_compatible = candidate_snapshots.get("top_compatible")
    if isinstance(top_compatible, list) and top_compatible:
        return [item for item in top_compatible if isinstance(item, dict)]
    top_same_family = candidate_snapshots.get("top_same_family")
    if isinstance(top_same_family, list) and top_same_family:
        return [item for item in top_same_family if isinstance(item, dict)]
    top_scored = candidate_snapshots.get("top_scored")
    if isinstance(top_scored, list) and top_scored:
        return [item for item in top_scored if isinstance(item, dict)]
    if isinstance(coverage_row, dict):
        examples = coverage_row.get("candidate_examples")
        if isinstance(examples, list):
            return [item for item in examples if isinstance(item, dict)]
    return []


def _enrich_row_with_coverage_audit(row: dict[str, Any], coverage_row: dict[str, Any] | None) -> dict[str, Any]:
    enriched = _build_canonical_fields(row)
    if not isinstance(coverage_row, dict):
        enriched.setdefault("catalog_audit_diagnosis", "")
        if (
            enriched.get("coverage_scope") == "non_target_family"
            and enriched.get("pipeline_stage") not in {"resolved", "query_input", "query_classification", "runtime_error"}
        ):
            enriched["root_cause_class"] = "not_audited_family"
            enriched["root_cause_code"] = "non_target_family"
            enriched["reason_class"] = enriched["root_cause_class"]
            enriched["reason_code"] = enriched["root_cause_code"]
        return enriched

    diagnosis = _clean_text_value(coverage_row.get("diagnosis"))
    enriched["catalog_audit_diagnosis"] = diagnosis
    enriched["catalog_gap_reason_code"] = ""
    enriched["coverage_scope"] = "non_target_family" if diagnosis == "non_target_family" else "audited_family"

    pipeline_counts = dict(enriched.get("pipeline_counts") or {})
    if "same_family_count" not in pipeline_counts:
        pipeline_counts["same_family_count"] = _safe_int(coverage_row.get("same_family_candidates_count"))
    if "compatible_count" not in pipeline_counts:
        pipeline_counts["compatible_count"] = _safe_int(coverage_row.get("compatible_candidates_count"))
    enriched["pipeline_counts"] = pipeline_counts

    pipeline_stage = _clean_text_value(enriched.get("pipeline_stage"))
    pipeline_reason_code = _normalize_reason_code(enriched.get("pipeline_reason_code"))
    same_family_count = _safe_int(pipeline_counts.get("same_family_count"))
    compatible_count = _safe_int(pipeline_counts.get("compatible_count"))

    if pipeline_stage not in {"resolved", "query_input", "runtime_error"} and pipeline_reason_code == "resolved":
        if pipeline_stage in {"gemini_selection", "fallback_policy"}:
            pipeline_reason_code = "gemini_returned_no_valid_candidate"
        else:
            pipeline_reason_code = "no_compatible_candidates"
        enriched["pipeline_reason_code"] = pipeline_reason_code

    if diagnosis == "non_target_family":
        if pipeline_stage == "resolved":
            enriched["root_cause_class"] = "resolved"
            enriched["root_cause_code"] = "resolved"
        else:
            enriched["root_cause_class"] = "not_audited_family"
            enriched["root_cause_code"] = "non_target_family"
    else:
        enriched["catalog_gap_reason_code"] = _clean_text_value(coverage_row.get("gap_reason_code"))
    if (
        diagnosis in {"catalog_missing_family", "catalog_has_family_but_no_compatible_specs"}
        and pipeline_stage != "resolved"
        and compatible_count <= 0
    ):
        enriched["root_cause_class"] = "catalog_gap"
        if diagnosis == "catalog_missing_family" and (
            pipeline_reason_code in GENERIC_CATALOG_GAP_CODES or same_family_count <= 0
        ):
            enriched["root_cause_code"] = "missing_family"
        elif diagnosis == "catalog_has_family_but_no_compatible_specs" and (
            pipeline_reason_code in GENERIC_CATALOG_GAP_CODES or compatible_count <= 0
        ):
            enriched["root_cause_code"] = _clean_text_value(coverage_row.get("gap_reason_code")) or "other_spec_mismatch"
    elif diagnosis == "catalog_has_compatible_candidates" and pipeline_stage in EARLY_FAILURE_STAGES:
        enriched["root_cause_class"] = "matcher_retrieval_or_ranking"
        if _normalize_reason_code(enriched.get("root_cause_code")) == "resolved":
            if same_family_count <= 0:
                enriched["root_cause_code"] = "compatible_candidates_exist_but_not_retrieved"
            elif compatible_count <= 0:
                enriched["root_cause_code"] = "compatible_candidates_retrieved_but_filtered_out"
    elif pipeline_stage in {"gemini_selection", "fallback_policy"} and compatible_count > 0 and diagnosis != "non_target_family":
        enriched["root_cause_class"] = "gemini_or_decision_policy"
        enriched["root_cause_code"] = pipeline_reason_code
    elif enriched.get("coverage_scope") == "non_target_family" and pipeline_stage != "resolved":
        enriched["root_cause_class"] = "not_audited_family"
        enriched["root_cause_code"] = "non_target_family"

    candidate_snapshots = dict(enriched.get("candidate_snapshots") or {})
    candidate_snapshots.setdefault("display_examples", _row_display_examples(candidate_snapshots, coverage_row))
    enriched["candidate_snapshots"] = candidate_snapshots
    enriched["stage_of_failure"] = enriched["pipeline_stage"]
    enriched["reason_code"] = enriched["root_cause_code"]
    enriched["reason_class"] = enriched["root_cause_class"]
    return enriched


def enrich_match_diagnostics_payload(
    payload: dict[str, Any],
    *,
    coverage_audit_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_rows = payload.get("rows")
    if not isinstance(base_rows, list):
        return payload

    audit_rows = _coverage_rows_by_number(coverage_audit_payload)
    enriched_rows = []
    for row in base_rows:
        if not isinstance(row, dict):
            continue
        run_row_number = _safe_int(row.get("run_row_number"))
        enriched = _enrich_row_with_coverage_audit(row, audit_rows.get(run_row_number))
        if _clean_text_value(enriched.get("root_cause_class")) == "":
            enriched["root_cause_class"] = infer_reason_class(
                _clean_text_value(enriched.get("pipeline_stage")),
                _normalize_reason_code(enriched.get("pipeline_reason_code")),
            )
        if _normalize_reason_code(enriched.get("root_cause_code")) == "resolved" and enriched.get("root_cause_class") != "resolved":
            enriched["root_cause_code"] = _normalize_reason_code(enriched.get("pipeline_reason_code"))
        enriched["reason_class"] = _clean_text_value(enriched.get("root_cause_class"))
        enriched["reason_code"] = _normalize_reason_code(enriched.get("root_cause_code"))
        enriched_rows.append(enriched)

    summary = _build_summary(enriched_rows)
    enriched_payload = dict(payload)
    enriched_payload["summary"] = summary
    enriched_payload["rows"] = enriched_rows
    return enriched_payload


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pipeline_stage_counts = Counter()
    root_cause_class_counts = Counter()
    root_cause_code_counts = Counter()
    resolver_name_counts = Counter()
    rows_resolved = 0
    rows_unresolved = 0

    for row in rows:
        pipeline_stage = _clean_text_value(row.get("pipeline_stage") or row.get("stage_of_failure")) or "runtime_error"
        pipeline_reason_code = _normalize_reason_code(row.get("pipeline_reason_code") or row.get("reason_code"))
        root_cause_class = _clean_text_value(row.get("root_cause_class") or row.get("reason_class")) or infer_reason_class(
            pipeline_stage,
            pipeline_reason_code,
        )
        root_cause_code = _normalize_reason_code(row.get("root_cause_code") or row.get("reason_code") or pipeline_reason_code)
        resolver_name = _clean_text_value(row.get("resolver_name") or row.get("resolution_source"))
        pipeline_stage_counts[pipeline_stage] += 1
        root_cause_class_counts[root_cause_class] += 1
        root_cause_code_counts[root_cause_code] += 1
        if resolver_name:
            resolver_name_counts[resolver_name] += 1
        if pipeline_stage == "resolved":
            rows_resolved += 1
        else:
            rows_unresolved += 1

    return {
        "rows_total": len(rows),
        "rows_resolved": rows_resolved,
        "rows_unresolved": rows_unresolved,
        "pipeline_stage_counts": dict(sorted(pipeline_stage_counts.items())),
        "root_cause_class_counts": dict(sorted(root_cause_class_counts.items())),
        "root_cause_code_counts": dict(sorted(root_cause_code_counts.items())),
        "resolver_name_counts": dict(sorted(resolver_name_counts.items())),
        # Backward-compatible aliases.
        "stage_counts": dict(sorted(pipeline_stage_counts.items())),
        "reason_class_counts": dict(sorted(root_cause_class_counts.items())),
        "reason_code_counts": dict(sorted(root_cause_code_counts.items())),
    }


def build_match_diagnostics_payload(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    reconstructed: bool = False,
    coverage_audit_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = _build_canonical_fields(row)
        if _clean_text_value(normalized.get("root_cause_class")) == "":
            normalized["root_cause_class"] = infer_reason_class(
                _clean_text_value(normalized.get("pipeline_stage")),
                _normalize_reason_code(normalized.get("pipeline_reason_code")),
            )
        if _normalize_reason_code(normalized.get("root_cause_code")) == "resolved" and normalized["root_cause_class"] != "resolved":
            normalized["root_cause_code"] = _normalize_reason_code(normalized.get("pipeline_reason_code"))
        normalized["reason_code"] = _normalize_reason_code(normalized.get("root_cause_code"))
        normalized["reason_class"] = _clean_text_value(normalized.get("root_cause_class"))
        normalized_rows.append(normalized)

    payload = {
        "diagnostics_version": MATCH_DIAGNOSTICS_VERSION,
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reconstructed": bool(reconstructed),
        "summary": _build_summary(normalized_rows),
        "rows": normalized_rows,
    }
    return enrich_match_diagnostics_payload(payload, coverage_audit_payload=coverage_audit_payload)


def apply_match_diagnostics_to_result_dataframe(
    df_result: pd.DataFrame,
    payload: dict[str, Any] | None,
) -> pd.DataFrame:
    if not isinstance(payload, dict):
        return df_result
    rows = payload.get("rows")
    if not isinstance(rows, list) or df_result is None:
        return df_result

    stage_column = "Этап отказа"
    reason_code_column = "Код причины"
    reason_class_column = "Класс причины"
    resolver_name_column = "Резолвер"
    resolver_confidence_column = "Уверенность резолвера"
    family_confidence_column = "Уверенность family"
    article_validation_column = "Статус article validation"
    gemini_route_column = "Gemini route"
    gemini_validation_column = "Gemini validation"
    secondary_filter_column = "Правила secondary filter"
    for column in (
        stage_column,
        reason_code_column,
        reason_class_column,
        resolver_name_column,
        resolver_confidence_column,
        family_confidence_column,
        article_validation_column,
        gemini_route_column,
        gemini_validation_column,
        secondary_filter_column,
    ):
        if column not in df_result.columns:
            df_result[column] = None

    for row in rows:
        if not isinstance(row, dict):
            continue
        run_row_number = _safe_int(row.get("run_row_number"))
        if run_row_number <= 1:
            continue
        dataframe_index = run_row_number - 2
        if dataframe_index not in df_result.index:
            continue
        pipeline_stage = _clean_text_value(row.get("pipeline_stage") or row.get("stage_of_failure")) or "runtime_error"
        root_cause_code = _normalize_reason_code(row.get("root_cause_code") or row.get("reason_code"))
        root_cause_class = _clean_text_value(row.get("root_cause_class") or row.get("reason_class")) or infer_reason_class(
            pipeline_stage,
            root_cause_code,
        )
        df_result.at[dataframe_index, stage_column] = pipeline_stage
        df_result.at[dataframe_index, reason_code_column] = root_cause_code
        df_result.at[dataframe_index, reason_class_column] = root_cause_class
        df_result.at[dataframe_index, resolver_name_column] = _clean_text_value(
            row.get("resolver_name") or row.get("resolution_source")
        )
        df_result.at[dataframe_index, resolver_confidence_column] = round(_safe_float(row.get("resolver_confidence")), 4)
        df_result.at[dataframe_index, family_confidence_column] = round(_safe_float(row.get("family_confidence")), 4)
        df_result.at[dataframe_index, article_validation_column] = _clean_text_value(row.get("article_validation_status"))
        df_result.at[dataframe_index, gemini_route_column] = bool(row.get("gemini_route_used"))
        df_result.at[dataframe_index, gemini_validation_column] = bool(row.get("gemini_validation_used"))
        df_result.at[dataframe_index, secondary_filter_column] = ", ".join(
            str(item)
            for item in (row.get("secondary_filter_rule_set") or [])
            if _clean_text_value(item)
        )
    return df_result


def apply_match_diagnostics_summary_to_stats(
    stats: dict[str, Any] | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    updated_stats = dict(stats or {})
    if not isinstance(payload, dict):
        return updated_stats
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return updated_stats
    updated_stats["diagnostic_stage_counts"] = dict(summary.get("pipeline_stage_counts") or summary.get("stage_counts") or {})
    updated_stats["diagnostic_reason_class_counts"] = dict(
        summary.get("root_cause_class_counts") or summary.get("reason_class_counts") or {}
    )
    updated_stats["diagnostic_reason_code_counts"] = dict(
        summary.get("root_cause_code_counts") or summary.get("reason_code_counts") or {}
    )
    return updated_stats


def _find_query_column(df_result: pd.DataFrame) -> str:
    for column in df_result.columns:
        normalized = _clean_text_value(column).lower()
        if "наименование" in normalized and "оборудован" in normalized:
            return str(column)
    if len(df_result.columns) > 1:
        return str(df_result.columns[1])
    if len(df_result.columns) == 1:
        return str(df_result.columns[0])
    raise ValueError("Result dataframe has no columns")


def _should_skip_query_text(query_text: str) -> bool:
    cleaned = _clean_text_value(query_text)
    if not cleaned:
        return True
    return cleaned.lower() in HEADER_QUERY_VALUES


def _is_missing_result(found_name: Any) -> bool:
    cleaned = _clean_text_value(found_name)
    return not cleaned or cleaned == MISSING_POSITION_TEXT


def _base_stage_from_result(row: pd.Series) -> tuple[str, str]:
    compatibility_status = _clean_text_value(row.get("Совместимость решения"))
    incompatibility_reason = _normalize_reason_code(row.get("Причина несовместимости"))
    error_text = _clean_text_value(row.get("Ошибка сопоставления"))
    gemini_shortlist = _safe_int(row.get("Gemini shortlist"))

    if not _is_missing_result(row.get("Найденная номенклатура")):
        return "resolved", "resolved"
    if error_text:
        return "runtime_error", "runtime_exception"
    if incompatibility_reason in INPUT_REASON_CODES:
        return "query_input", incompatibility_reason
    if incompatibility_reason in FALLBACK_REASON_CODES:
        return "fallback_policy", incompatibility_reason
    if incompatibility_reason == "resolved":
        if compatibility_status == "rejected_incompatible_gemini" or gemini_shortlist > 0:
            return "gemini_selection", "gemini_rejected_all_candidates"
        return "local_recall", "no_compatible_candidates"
    if compatibility_status == "rejected_incompatible_gemini" or gemini_shortlist > 0:
        if incompatibility_reason == "resolved":
            return "gemini_selection", "gemini_returned_no_valid_candidate"
        if incompatibility_reason in {"no_confirmed_compatible_candidate", "no_compatible_candidates"}:
            return "gemini_selection", "gemini_rejected_all_candidates"
        return "gemini_selection", incompatibility_reason
    if incompatibility_reason.endswith("_mismatch"):
        return "compatibility_filter", incompatibility_reason
    if incompatibility_reason in {"no_compatible_candidates", "strict_class_no_compatible_candidate"}:
        return "local_recall", incompatibility_reason
    return "local_recall", incompatibility_reason


def reconstruct_match_diagnostics(
    df_result: pd.DataFrame,
    *,
    run_id: str,
    coverage_audit_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    query_column = _find_query_column(df_result)
    reconstructed_rows = []
    audit_rows = _coverage_rows_by_number(coverage_audit_payload)

    for row_index, row in df_result.iterrows():
        query_text = _clean_text_value(row.get(query_column))
        if _should_skip_query_text(query_text):
            continue

        run_row_number = int(row_index) + 2
        coverage_row = audit_rows.get(run_row_number)
        query_family = _clean_text_value((coverage_row or {}).get("query_family"))
        stage_of_failure, reason_code = _base_stage_from_result(row)
        pipeline_counts = {
            "local_pool_count": None,
            "scored_count": None,
            "same_family_count": _safe_int((coverage_row or {}).get("same_family_candidates_count")),
            "compatible_count": _safe_int((coverage_row or {}).get("compatible_candidates_count")),
        }
        gemini_shortlist = _safe_int(row.get("Gemini shortlist"))
        gemini_visible = _safe_int(row.get("Gemini visible candidates"))
        gemini_truncated = _safe_int(row.get("Gemini truncated"))
        reconstructed_rows.append(
            {
                "run_row_number": run_row_number,
                "query_text": query_text,
                "row_type": "",
                "entity_type": "",
                "query_family": query_family,
                "resolution_source": _clean_text_value(row.get("Источник решения")),
                "query_article": "",
                "article_source": "none",
                "article_lookup_hit": False,
                "article_lookup_conflict": False,
                "article_validation_status": "",
                "resolver_name": _clean_text_value(row.get("Источник решения")),
                "resolver_confidence": 0.0,
                "family_confidence": 0.0,
                "gemini_route_used": False,
                "gemini_validation_used": False,
                "secondary_filter_rule_set": [],
                "compatibility_status": _clean_text_value(row.get("Совместимость решения")),
                "incompatibility_reason": _clean_text_value(row.get("Причина несовместимости")),
                "pipeline_stage": stage_of_failure,
                "pipeline_reason_code": reason_code,
                "root_cause_class": infer_reason_class(stage_of_failure, reason_code),
                "root_cause_code": reason_code,
                "coverage_scope": _infer_coverage_scope(query_family),
                "pipeline_counts": pipeline_counts,
                "candidate_snapshots": {
                    "display_examples": _row_display_examples({}, coverage_row),
                },
                "gemini": {
                    "attempted": gemini_shortlist > 0,
                    "model": "",
                    "shortlist_count": gemini_shortlist,
                    "visible_candidates": gemini_visible,
                    "truncated_candidates": gemini_truncated,
                    "result_status": "reconstructed",
                },
                "trace_steps": [
                    {
                        "stage": stage_of_failure,
                        "status": "reconstructed",
                        "reason_code": reason_code,
                    }
                ],
            }
        )

    return build_match_diagnostics_payload(
        reconstructed_rows,
        run_id=run_id,
        reconstructed=True,
        coverage_audit_payload=coverage_audit_payload,
    )


def prepare_match_diagnostics_table(payload: dict[str, Any]) -> pd.DataFrame:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return pd.DataFrame()
    prepared_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pipeline_counts = dict(row.get("pipeline_counts") or {})
        candidate_snapshots = dict(row.get("candidate_snapshots") or {})
        examples = candidate_snapshots.get("display_examples") or []
        example_strings = []
        if isinstance(examples, list):
            for example in examples:
                if not isinstance(example, dict):
                    continue
                name = _clean_text_value(example.get("name"))
                article = _clean_text_value(example.get("article"))
                label = _clean_text_value(example.get("compatibility") or example.get("label"))
                reason = _clean_text_value(example.get("reason"))
                parts = [name]
                if article:
                    parts.append(f"[{article}]")
                if label:
                    parts.append(label)
                if reason:
                    parts.append(reason)
                example_strings.append(" | ".join(part for part in parts if part))
        gemini = dict(row.get("gemini") or {})
        prepared_rows.append(
            {
                "Строка": row.get("run_row_number"),
                "Запрос": row.get("query_text"),
                "Family": row.get("query_family"),
                "Pipeline stage": row.get("pipeline_stage") or row.get("stage_of_failure"),
                "Pipeline reason": row.get("pipeline_reason_code") or row.get("reason_code"),
                "Query article": row.get("query_article"),
                "Article source": row.get("article_source"),
                "Article hit": row.get("article_lookup_hit"),
                "Article conflict": row.get("article_lookup_conflict"),
                "Article validation": row.get("article_validation_status"),
                "Resolver": row.get("resolver_name") or row.get("resolution_source"),
                "Resolver confidence": _safe_float(row.get("resolver_confidence")),
                "Family confidence": _safe_float(row.get("family_confidence")),
                "Gemini route used": bool(row.get("gemini_route_used")),
                "Gemini validation used": bool(row.get("gemini_validation_used")),
                "Secondary filter rules": ", ".join(
                    str(item)
                    for item in (row.get("secondary_filter_rule_set") or [])
                    if _clean_text_value(item)
                ),
                "Secondary filter before": pipeline_counts.get("secondary_filter_before_count"),
                "Secondary filter after": pipeline_counts.get("secondary_filter_after_count"),
                "Root cause class": row.get("root_cause_class") or row.get("reason_class"),
                "Root cause code": row.get("root_cause_code") or row.get("reason_code"),
                "Coverage scope": row.get("coverage_scope"),
                "Catalog audit diagnosis": row.get("catalog_audit_diagnosis"),
                "Catalog gap reason": row.get("catalog_gap_reason_code"),
                "Retrieval backend": row.get("retrieval_backend") or pipeline_counts.get("retrieval_backend"),
                "Retrieval mode": row.get("retrieval_mode") or pipeline_counts.get("retrieval_mode"),
                "Category key": pipeline_counts.get("query_category_key"),
                "Category candidates": pipeline_counts.get("category_candidate_count"),
                "Category scanned": pipeline_counts.get("category_rows_scanned"),
                "DuckDB query ms": pipeline_counts.get("duckdb_query_ms"),
                "Python scoring ms": pipeline_counts.get("python_scoring_ms"),
                "Compatibility filter ms": pipeline_counts.get("compatibility_filter_ms"),
                "Gemini ms": pipeline_counts.get("gemini_ms"),
                "Local pool": pipeline_counts.get("local_pool_count"),
                "Scored": pipeline_counts.get("scored_count"),
                "Same family": pipeline_counts.get("same_family_count"),
                "Compatible": pipeline_counts.get("compatible_count"),
                "Gemini shortlist": gemini.get("shortlist_count"),
                "Источник решения": row.get("resolution_source"),
                "Совместимость решения": row.get("compatibility_status"),
                "Примеры кандидатов": "\n".join(example_strings),
            }
        )
    return pd.DataFrame(prepared_rows)


def prepare_match_diagnostics_stage_table(payload: dict[str, Any]) -> pd.DataFrame:
    summary = payload.get("summary") or {}
    stage_counts = summary.get("pipeline_stage_counts") or summary.get("stage_counts")
    if not isinstance(stage_counts, dict):
        return pd.DataFrame()
    return pd.DataFrame(
        [{"Pipeline stage": stage, "Строк": _safe_int(count)} for stage, count in stage_counts.items()]
    )


def prepare_match_diagnostics_reason_table(payload: dict[str, Any]) -> pd.DataFrame:
    summary = payload.get("summary") or {}
    reason_counts = summary.get("root_cause_code_counts") or summary.get("reason_code_counts")
    if not isinstance(reason_counts, dict):
        return pd.DataFrame()
    return pd.DataFrame(
        [{"Root cause code": reason_code, "Строк": _safe_int(count)} for reason_code, count in reason_counts.items()]
    )


def prepare_match_diagnostics_resolver_table(payload: dict[str, Any]) -> pd.DataFrame:
    summary = payload.get("summary") or {}
    resolver_counts = summary.get("resolver_name_counts") or {}
    if not isinstance(resolver_counts, dict):
        return pd.DataFrame()
    return pd.DataFrame(
        [{"Resolver": resolver_name, "Строк": _safe_int(count)} for resolver_name, count in resolver_counts.items()]
    )


def prepare_match_diagnostics_root_cause_table(payload: dict[str, Any]) -> pd.DataFrame:
    summary = payload.get("summary") or {}
    root_cause_counts = summary.get("root_cause_class_counts") or summary.get("reason_class_counts")
    if not isinstance(root_cause_counts, dict):
        return pd.DataFrame()
    return pd.DataFrame(
        [{"Root cause class": reason_class, "Строк": _safe_int(count)} for reason_class, count in root_cause_counts.items()]
    )
