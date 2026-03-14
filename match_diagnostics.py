from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import pandas as pd

MATCH_DIAGNOSTICS_VERSION = 2
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
}
FALLBACK_REASON_CODES = {
    "strict_fallback_family_mismatch",
    "strict_class_requires_compatible_match",
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
    "runtime_error": "runtime error",
    "resolved": "resolved",
}


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
    enriched = dict(row)
    if not isinstance(coverage_row, dict):
        enriched.setdefault("catalog_audit_diagnosis", "")
        return enriched

    diagnosis = _clean_text_value(coverage_row.get("diagnosis"))
    enriched["catalog_audit_diagnosis"] = diagnosis

    pipeline_counts = dict(enriched.get("pipeline_counts") or {})
    if "same_family_count" not in pipeline_counts:
        pipeline_counts["same_family_count"] = _safe_int(coverage_row.get("same_family_candidates_count"))
    if "compatible_count" not in pipeline_counts:
        pipeline_counts["compatible_count"] = _safe_int(coverage_row.get("compatible_candidates_count"))
    enriched["pipeline_counts"] = pipeline_counts

    stage = _clean_text_value(enriched.get("stage_of_failure"))
    reason_code = _normalize_reason_code(enriched.get("reason_code"))
    same_family_count = _safe_int(pipeline_counts.get("same_family_count"))
    compatible_count = _safe_int(pipeline_counts.get("compatible_count"))

    if stage not in {"resolved", "query_input", "runtime_error"} and reason_code == "resolved":
        if stage in {"gemini_selection", "fallback_policy"}:
            enriched["reason_code"] = "gemini_returned_no_valid_candidate"
        else:
            enriched["reason_code"] = "no_compatible_candidates"
        reason_code = _normalize_reason_code(enriched.get("reason_code"))

    if (
        diagnosis in {"catalog_missing_family", "catalog_has_family_but_no_compatible_specs"}
        and stage != "resolved"
        and compatible_count <= 0
    ):
        enriched["stage_of_failure"] = "catalog_gap"
        enriched["reason_class"] = "catalog_gap"
        if diagnosis == "catalog_missing_family" and (
            reason_code in GENERIC_CATALOG_GAP_CODES or same_family_count <= 0
        ):
            enriched["reason_code"] = "catalog_missing_family"
        elif diagnosis == "catalog_has_family_but_no_compatible_specs" and (
            reason_code in GENERIC_CATALOG_GAP_CODES or compatible_count <= 0
        ):
            enriched["reason_code"] = "catalog_has_family_but_no_compatible_specs"
    elif diagnosis == "catalog_has_compatible_candidates" and stage in EARLY_FAILURE_STAGES:
        enriched["reason_class"] = "matcher_retrieval_or_ranking"
        if reason_code == "resolved":
            if same_family_count <= 0:
                enriched["reason_code"] = "compatible_candidates_exist_but_not_retrieved"
            elif compatible_count <= 0:
                enriched["reason_code"] = "compatible_candidates_retrieved_but_filtered_out"

    candidate_snapshots = dict(enriched.get("candidate_snapshots") or {})
    candidate_snapshots.setdefault("display_examples", _row_display_examples(candidate_snapshots, coverage_row))
    enriched["candidate_snapshots"] = candidate_snapshots
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
        enriched["reason_class"] = infer_reason_class(
            _clean_text_value(enriched.get("stage_of_failure")),
            _normalize_reason_code(enriched.get("reason_code")),
        ) if _clean_text_value(enriched.get("reason_class")) == "" else _clean_text_value(enriched.get("reason_class"))
        enriched_rows.append(enriched)

    summary = _build_summary(enriched_rows)
    enriched_payload = dict(payload)
    enriched_payload["summary"] = summary
    enriched_payload["rows"] = enriched_rows
    return enriched_payload


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stage_counts = Counter()
    reason_class_counts = Counter()
    reason_code_counts = Counter()
    rows_resolved = 0
    rows_unresolved = 0

    for row in rows:
        stage = _clean_text_value(row.get("stage_of_failure")) or "runtime_error"
        reason_class = _clean_text_value(row.get("reason_class")) or infer_reason_class(stage, _normalize_reason_code(row.get("reason_code")))
        reason_code = _normalize_reason_code(row.get("reason_code"))
        stage_counts[stage] += 1
        reason_class_counts[reason_class] += 1
        reason_code_counts[reason_code] += 1
        if stage == "resolved":
            rows_resolved += 1
        else:
            rows_unresolved += 1

    return {
        "rows_total": len(rows),
        "rows_resolved": rows_resolved,
        "rows_unresolved": rows_unresolved,
        "stage_counts": dict(sorted(stage_counts.items())),
        "reason_class_counts": dict(sorted(reason_class_counts.items())),
        "reason_code_counts": dict(sorted(reason_code_counts.items())),
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
        normalized = dict(row)
        normalized["reason_code"] = _normalize_reason_code(normalized.get("reason_code"))
        normalized["reason_class"] = _clean_text_value(normalized.get("reason_class")) or infer_reason_class(
            _clean_text_value(normalized.get("stage_of_failure")),
            normalized["reason_code"],
        )
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
                "compatibility_status": _clean_text_value(row.get("Совместимость решения")),
                "incompatibility_reason": _clean_text_value(row.get("Причина несовместимости")),
                "stage_of_failure": stage_of_failure,
                "reason_code": reason_code,
                "reason_class": infer_reason_class(stage_of_failure, reason_code),
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
                "Этап отказа": row.get("stage_of_failure"),
                "Код причины": row.get("reason_code"),
                "Класс причины": row.get("reason_class"),
                "Каталог-аудит": row.get("catalog_audit_diagnosis"),
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
    stage_counts = summary.get("stage_counts")
    if not isinstance(stage_counts, dict):
        return pd.DataFrame()
    return pd.DataFrame(
        [{"Этап отказа": stage, "Строк": _safe_int(count)} for stage, count in stage_counts.items()]
    )


def prepare_match_diagnostics_reason_table(payload: dict[str, Any]) -> pd.DataFrame:
    summary = payload.get("summary") or {}
    reason_counts = summary.get("reason_code_counts")
    if not isinstance(reason_counts, dict):
        return pd.DataFrame()
    return pd.DataFrame(
        [{"Код причины": reason_code, "Строк": _safe_int(count)} for reason_code, count in reason_counts.items()]
    )
