from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from catalog_coverage_audit import (
    build_catalog_coverage_audit,
    prepare_catalog_coverage_audit_table,
    prepare_catalog_coverage_family_table,
    prepare_catalog_gap_reason_table,
)
from catalog_search import (
    SEARCH_CATALOG_CSV_FILENAME,
    SEARCH_CATALOG_DUCKDB_FILENAME,
    is_search_catalog_path,
)
from config import get_catalog_csv_path
from match_diagnostics import (
    apply_match_diagnostics_summary_to_stats,
    apply_match_diagnostics_to_result_dataframe,
    enrich_match_diagnostics_payload,
    prepare_match_diagnostics_reason_table,
    prepare_match_diagnostics_resolver_table,
    prepare_match_diagnostics_root_cause_table,
    prepare_match_diagnostics_table,
    reconstruct_match_diagnostics,
)
from matcher import MATCH_MODE_EXACT, MISSING_POSITION_TEXT, ReMoMatcher

FIXTURE_COLUMNS = (
    "case_id",
    "suite",
    "tier",
    "input_mode",
    "query_text",
    "query_article",
    "expected_family",
    "expected_outcome",
    "expected_articles_json",
    "forbidden_articles_json",
    "allowed_resolvers_json",
    "notes",
    "source_ref",
)
VALID_TIERS = {"smoke", "full"}
VALID_INPUT_MODES = {"article_column", "article_in_text", "name_only"}
VALID_EXPECTED_OUTCOMES = {"exact", "review", "catalog_gap", "non_target"}
DEFAULT_FIXTURE_PATH = Path("tests/fixtures/golden_match_cases.csv")
DEFAULT_BENCHMARK_ROOT = Path("batch_output/benchmarks")
AUTO_ACCEPT_RESOLVERS = {
    "article_exact",
    "article_extracted_exact",
    "article_designation_exact",
    "name_exact",
    "normalized_name_exact",
}
INPUT_REJECTION_REASON_CODES = {"empty_query", "section_row_detected", "header_like_row"}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _parse_json_list(raw: str, *, field_name: str, case_id: str) -> list[str]:
    text = _clean_text(raw)
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Case {case_id}: invalid JSON in {field_name}: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError(f"Case {case_id}: {field_name} must be a JSON list")
    return [_clean_text(item) for item in payload if _clean_text(item)]


def _build_excel_workbook_bytes(sheets: list[tuple[str, pd.DataFrame]]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in sheets:
            export_df = df.copy()
            if export_df.empty:
                export_df = pd.DataFrame({"Статус": ["Нет данных"]})
            export_df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    buffer.seek(0)
    return buffer.getvalue()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return _clean_text(result.stdout)
    except Exception:
        return ""


def _catalog_metadata(path: Path) -> dict[str, Any]:
    resolved = Path(path)
    exists = resolved.exists()
    stat = resolved.stat() if exists else None
    return {
        "catalog_source_path": str(resolved),
        "catalog_source_kind": "search" if is_search_catalog_path(resolved) else "merged",
        "catalog_exists": exists,
        "catalog_mtime": stat.st_mtime if stat else None,
        "catalog_size_bytes": stat.st_size if stat else None,
        "catalog_fingerprint": f"{stat.st_size}:{int(stat.st_mtime)}" if stat else "",
    }


def _matcher_catalog_argument(catalog_path: str | None) -> str:
    candidate = Path(catalog_path) if catalog_path else get_catalog_csv_path()
    if candidate.exists() and is_search_catalog_path(candidate):
        return str(candidate)
    return str(candidate)


def _prepare_catalog_input(catalog_path: str | None, output_dir: Path) -> str:
    if not catalog_path:
        return _matcher_catalog_argument(None)

    candidate = Path(catalog_path)
    if not candidate.exists():
        return _matcher_catalog_argument(catalog_path)

    lower_name = candidate.name.lower()
    if "search" not in lower_name or is_search_catalog_path(candidate):
        return _matcher_catalog_argument(catalog_path)

    stage_dir = output_dir / "_catalog_input"
    stage_dir.mkdir(parents=True, exist_ok=True)
    if candidate.suffix.lower() == ".duckdb":
        staged_path = stage_dir / SEARCH_CATALOG_DUCKDB_FILENAME
    else:
        staged_path = stage_dir / SEARCH_CATALOG_CSV_FILENAME
    shutil.copy2(candidate, staged_path)
    return str(staged_path)


def validate_golden_case(case: dict[str, Any]) -> dict[str, Any]:
    case_id = _clean_text(case.get("case_id"))
    if not case_id:
        raise ValueError("Case is missing case_id")
    tier = _clean_text(case.get("tier")).lower()
    if tier not in VALID_TIERS:
        raise ValueError(f"Case {case_id}: invalid tier {tier!r}")
    input_mode = _clean_text(case.get("input_mode")).lower()
    if input_mode not in VALID_INPUT_MODES:
        raise ValueError(f"Case {case_id}: invalid input_mode {input_mode!r}")
    expected_outcome = _clean_text(case.get("expected_outcome")).lower()
    if expected_outcome not in VALID_EXPECTED_OUTCOMES:
        raise ValueError(f"Case {case_id}: invalid expected_outcome {expected_outcome!r}")
    query_text = _clean_text(case.get("query_text"))
    if not query_text:
        raise ValueError(f"Case {case_id}: query_text is required")
    query_article = _clean_text(case.get("query_article"))
    if input_mode == "article_column" and not query_article:
        raise ValueError(f"Case {case_id}: article_column mode requires query_article")

    expected_articles = _parse_json_list(
        _clean_text(case.get("expected_articles_json")),
        field_name="expected_articles_json",
        case_id=case_id,
    )
    forbidden_articles = _parse_json_list(
        _clean_text(case.get("forbidden_articles_json")),
        field_name="forbidden_articles_json",
        case_id=case_id,
    )
    allowed_resolvers = _parse_json_list(
        _clean_text(case.get("allowed_resolvers_json")),
        field_name="allowed_resolvers_json",
        case_id=case_id,
    )

    if expected_outcome == "exact" and not expected_articles:
        raise ValueError(f"Case {case_id}: exact outcome requires expected_articles_json")

    return {
        "case_id": case_id,
        "suite": _clean_text(case.get("suite")) or "unspecified",
        "tier": tier,
        "input_mode": input_mode,
        "query_text": query_text,
        "query_article": query_article,
        "expected_family": _clean_text(case.get("expected_family")),
        "expected_outcome": expected_outcome,
        "expected_articles": expected_articles,
        "forbidden_articles": forbidden_articles,
        "allowed_resolvers": allowed_resolvers,
        "notes": _clean_text(case.get("notes")),
        "source_ref": _clean_text(case.get("source_ref")),
    }


def load_golden_cases(csv_path: str | Path) -> list[dict[str, Any]]:
    fixture_path = Path(csv_path)
    with fixture_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        if columns != FIXTURE_COLUMNS:
            raise ValueError(
                f"Fixture columns mismatch for {fixture_path}: expected {FIXTURE_COLUMNS}, got {columns}"
            )
        rows = [validate_golden_case(row) for row in reader]

    seen_case_ids: set[str] = set()
    for row in rows:
        case_id = row["case_id"]
        if case_id in seen_case_ids:
            raise ValueError(f"Duplicate case_id in fixture: {case_id}")
        seen_case_ids.add(case_id)
    return rows


def build_benchmark_input_dataframe(cases: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        rows.append(
            {
                "Case ID": case["case_id"],
                "Наименование оборудования, материалов и кабелей": case["query_text"],
                "Артикул": case["query_article"] if case["input_mode"] == "article_column" else "",
            }
        )
    return pd.DataFrame(rows, columns=["Case ID", "Наименование оборудования, материалов и кабелей", "Артикул"])


def _result_value(row: pd.Series, column: str) -> str:
    return _clean_text(row.get(column))


def _top_candidate_examples(diagnostic_row: dict[str, Any]) -> str:
    snapshots = dict(diagnostic_row.get("candidate_snapshots") or {})
    examples = snapshots.get("display_examples") or []
    rendered: list[str] = []
    for example in examples[:3]:
        if not isinstance(example, dict):
            continue
        name = _clean_text(example.get("name"))
        article = _clean_text(example.get("article"))
        compatibility = _clean_text(example.get("compatibility"))
        reason = _clean_text(example.get("reason"))
        parts = [name]
        if article:
            parts.append(f"[{article}]")
        if compatibility:
            parts.append(compatibility)
        if reason:
            parts.append(reason)
        rendered.append(" | ".join(part for part in parts if part))
    return " || ".join(rendered)


def _is_unresolved(actual: dict[str, Any]) -> bool:
    found_name = _clean_text(actual.get("found_name"))
    compatibility_status = _clean_text(actual.get("compatibility_status"))
    resolver_name = _clean_text(actual.get("resolver_name"))
    return (
        not found_name
        or found_name == MISSING_POSITION_TEXT
        or resolver_name == "unresolved"
        or compatibility_status == "unresolved_no_compatible_candidates"
    )


def is_auto_accept_result(case: dict[str, Any], actual: dict[str, Any]) -> bool:
    verifier_decision = _clean_text(actual.get("verifier_decision")).lower()
    if verifier_decision:
        return verifier_decision == "auto_accept"
    resolver_name = _clean_text(actual.get("resolver_name"))
    requires_review = _clean_text(actual.get("requires_review")).lower()
    compatibility_status = _clean_text(actual.get("compatibility_status"))
    if _is_unresolved(actual):
        return False
    if compatibility_status != "compatible":
        return False
    if requires_review == "да":
        return False
    if resolver_name in AUTO_ACCEPT_RESOLVERS:
        return True
    if resolver_name == "article_series_local" and resolver_name in case.get("allowed_resolvers", []):
        return True
    return False


def score_benchmark_case(case: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    found_article = _clean_text(actual.get("found_article"))
    resolver_name = _clean_text(actual.get("resolver_name"))
    compatibility_status = _clean_text(actual.get("compatibility_status"))
    requires_review = _clean_text(actual.get("requires_review")).lower()
    pipeline_stage = _clean_text(actual.get("pipeline_stage"))
    root_cause_code = _clean_text(actual.get("root_cause_code"))
    expected_articles = set(case.get("expected_articles", []))
    forbidden_articles = set(case.get("forbidden_articles", []))
    allowed_resolvers = set(case.get("allowed_resolvers", []))
    auto_accept = is_auto_accept_result(case, actual)
    is_unresolved = _is_unresolved(actual)
    non_target_rejected = pipeline_stage == "query_input" or root_cause_code in INPUT_REJECTION_REASON_CODES
    correct_article = bool(found_article) and found_article in expected_articles
    forbidden_article_hit = bool(found_article) and found_article in forbidden_articles
    resolver_allowed = not allowed_resolvers or resolver_name in allowed_resolvers

    passed = False
    failure_bucket = ""
    explanation = ""
    outcome = case["expected_outcome"]
    if outcome == "exact":
        passed = auto_accept and compatibility_status == "compatible" and correct_article and resolver_allowed
        if not passed:
            failure_bucket = "false_negative"
            explanation = "expected exact auto-accept was not achieved"
    elif outcome == "review":
        passed = (is_unresolved or requires_review == "да" or not auto_accept) and not forbidden_article_hit
        if not passed:
            failure_bucket = "false_positive" if auto_accept else "review_policy_miss"
            explanation = "review case was auto-accepted or matched a forbidden article"
    elif outcome == "catalog_gap":
        passed = is_unresolved and not auto_accept
        if not passed:
            failure_bucket = "false_positive"
            explanation = "catalog gap case should stay unresolved"
    elif outcome == "non_target":
        passed = non_target_rejected and not auto_accept
        if not passed:
            failure_bucket = "false_positive"
            explanation = "non-target row was not rejected as input/query-shape"

    if forbidden_article_hit and not failure_bucket:
        failure_bucket = "forbidden_article"
        explanation = "matched a forbidden article"
        passed = False

    return {
        "benchmark_pass": bool(passed),
        "auto_accept": bool(auto_accept),
        "correct_article": bool(correct_article),
        "forbidden_article_hit": bool(forbidden_article_hit),
        "failure_bucket": failure_bucket,
        "failure_explanation": explanation,
        "resolver_allowed": bool(resolver_allowed),
    }


def _per_case_record(
    case: dict[str, Any],
    result_row: pd.Series,
    diagnostics_row: dict[str, Any] | None,
    coverage_row: dict[str, Any] | None,
) -> dict[str, Any]:
    diagnostics_row = diagnostics_row or {}
    coverage_row = coverage_row or {}
    actual = {
        "found_name": _result_value(result_row, "Найденная номенклатура"),
        "found_article": _result_value(result_row, "Артикул"),
        "resolver_name": _result_value(result_row, "Резолвер") or _result_value(result_row, "Источник решения"),
        "resolver_path": _clean_text(diagnostics_row.get("resolver_path")),
        "verifier_decision": _clean_text(diagnostics_row.get("verifier_decision") or _result_value(result_row, "Verifier decision")),
        "verifier_reason": _clean_text(diagnostics_row.get("verifier_reason") or _result_value(result_row, "Verifier reason")),
        "compatibility_status": _result_value(result_row, "Совместимость решения"),
        "requires_review": _result_value(result_row, "Требует проверки"),
        "pipeline_stage": _result_value(result_row, "Этап отказа"),
        "root_cause_code": _result_value(result_row, "Код причины"),
        "root_cause_class": _result_value(result_row, "Класс причины"),
        "query_family": _clean_text(diagnostics_row.get("query_family")),
        "family_confidence": float(diagnostics_row.get("family_confidence") or 0.0),
        "resolver_confidence": float(diagnostics_row.get("resolver_confidence") or 0.0),
        "article_validation_status": _clean_text(diagnostics_row.get("article_validation_status")),
        "parser_source": _clean_text(diagnostics_row.get("parser_source")),
        "parsed_article_in_text": _clean_text(diagnostics_row.get("parsed_article_in_text")),
        "designation_signature": _clean_text(diagnostics_row.get("designation_signature")),
        "gemini_route_used": bool(diagnostics_row.get("gemini_route_used")),
        "gemini_validation_used": bool(diagnostics_row.get("gemini_validation_used")),
        "incompatibility_reason": _result_value(result_row, "Причина несовместимости"),
        "top_3_candidates": _top_candidate_examples(diagnostics_row),
        "coverage_diagnosis": _clean_text(coverage_row.get("diagnosis")),
        "coverage_gap_reason": _clean_text(coverage_row.get("gap_reason_code")),
        "coverage_same_family_candidates": int(coverage_row.get("same_family_candidates_count") or 0),
        "coverage_compatible_candidates": int(coverage_row.get("compatible_candidates_count") or 0),
    }
    score = score_benchmark_case(case, actual)
    return {
        "case_id": case["case_id"],
        "suite": case["suite"],
        "tier": case["tier"],
        "input_mode": case["input_mode"],
        "expected_family": case["expected_family"],
        "expected_outcome": case["expected_outcome"],
        "expected_articles_json": json.dumps(case["expected_articles"], ensure_ascii=False),
        "forbidden_articles_json": json.dumps(case["forbidden_articles"], ensure_ascii=False),
        "allowed_resolvers_json": json.dumps(case["allowed_resolvers"], ensure_ascii=False),
        "query_text": case["query_text"],
        "query_article": case["query_article"],
        "actual_found_name": actual["found_name"],
        "actual_found_article": actual["found_article"],
        "actual_query_family": actual["query_family"],
        "resolver_name": actual["resolver_name"],
        "resolver_path": actual["resolver_path"],
        "verifier_decision": actual["verifier_decision"],
        "verifier_reason": actual["verifier_reason"],
        "resolver_confidence": round(actual["resolver_confidence"], 4),
        "family_confidence": round(actual["family_confidence"], 4),
        "compatibility_status": actual["compatibility_status"],
        "requires_review": actual["requires_review"],
        "article_validation_status": actual["article_validation_status"],
        "parser_source": actual["parser_source"],
        "parsed_article_in_text": actual["parsed_article_in_text"],
        "designation_signature": actual["designation_signature"],
        "gemini_route_used": actual["gemini_route_used"],
        "gemini_validation_used": actual["gemini_validation_used"],
        "pipeline_stage": actual["pipeline_stage"],
        "root_cause_code": actual["root_cause_code"],
        "root_cause_class": actual["root_cause_class"],
        "incompatibility_reason": actual["incompatibility_reason"],
        "top_3_candidates": actual["top_3_candidates"],
        "coverage_diagnosis": actual["coverage_diagnosis"],
        "coverage_gap_reason": actual["coverage_gap_reason"],
        "coverage_same_family_candidates": actual["coverage_same_family_candidates"],
        "coverage_compatible_candidates": actual["coverage_compatible_candidates"],
        "benchmark_pass": score["benchmark_pass"],
        "auto_accept": score["auto_accept"],
        "correct_article": score["correct_article"],
        "forbidden_article_hit": score["forbidden_article_hit"],
        "failure_bucket": score["failure_bucket"],
        "failure_explanation": score["failure_explanation"],
        "resolver_allowed": score["resolver_allowed"],
        "notes": case["notes"],
        "source_ref": case["source_ref"],
    }


def _summary_frame(df: pd.DataFrame, *, group_column: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    prepared = df.copy()
    prepared["_correct_auto_accept"] = prepared["auto_accept"] & prepared["benchmark_pass"]
    grouped = (
        prepared.groupby(group_column, dropna=False)
        .agg(
            cases=("case_id", "count"),
            passed=("benchmark_pass", "sum"),
            auto_accepts=("auto_accept", "sum"),
            correct_auto_accepts=("_correct_auto_accept", "sum"),
            false_positives=("failure_bucket", lambda values: int(sum(value == "false_positive" for value in values))),
            false_negatives=("failure_bucket", lambda values: int(sum(value == "false_negative" for value in values))),
        )
        .reset_index()
    )
    grouped["pass_rate"] = (grouped["passed"] / grouped["cases"]).round(4)
    grouped["auto_accept_precision"] = grouped.apply(
        lambda row: round(row["correct_auto_accepts"] / row["auto_accepts"], 4) if row["auto_accepts"] else None,
        axis=1,
    )
    grouped = grouped.drop(columns=["correct_auto_accepts"])
    return grouped


def _benchmark_metrics(df: pd.DataFrame) -> dict[str, Any]:
    auto_accept_rows = df[df["auto_accept"]]
    article_exact_rows = df[(df["auto_accept"]) & (df["resolver_name"] == "article_exact")]
    catalog_gap_rows = df[df["expected_outcome"] == "catalog_gap"]
    review_rows = df[df["expected_outcome"] == "review"]
    return {
        "total_cases": int(len(df.index)),
        "passed_cases": int(df["benchmark_pass"].sum()),
        "failed_cases": int((~df["benchmark_pass"]).sum()),
        "auto_accepts": int(auto_accept_rows["auto_accept"].sum()),
        "auto_accept_precision": round(float(auto_accept_rows["benchmark_pass"].mean()), 4)
        if not auto_accept_rows.empty
        else None,
        "article_exact_auto_accepts": int(len(article_exact_rows.index)),
        "article_exact_precision": round(float(article_exact_rows["benchmark_pass"].mean()), 4)
        if not article_exact_rows.empty
        else None,
        "catalog_gap_false_positive_rate": round(
            float((catalog_gap_rows["failure_bucket"] == "false_positive").mean()),
            4,
        )
        if not catalog_gap_rows.empty
        else None,
        "review_capture_rate": round(float(review_rows["benchmark_pass"].mean()), 4)
        if not review_rows.empty
        else None,
    }


def run_benchmark(
    *,
    fixture_path: str | Path = DEFAULT_FIXTURE_PATH,
    output_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    catalog_path: str | None = None,
    tier: str = "smoke",
    match_mode: str = MATCH_MODE_EXACT,
    include_audit: bool = True,
) -> Path:
    all_cases = load_golden_cases(fixture_path)
    selected_cases = [case for case in all_cases if tier == "full" or case["tier"] == "smoke"]
    if not selected_cases:
        raise ValueError(f"No benchmark cases selected for tier={tier!r}")

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(output_root) / run_stamp
    output_dir.mkdir(parents=True, exist_ok=True)

    input_df = build_benchmark_input_dataframe(selected_cases)
    input_path = output_dir / "input.xlsx"
    result_path = output_dir / "result.xlsx"
    input_df.to_excel(input_path, index=False)

    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    matcher = ReMoMatcher(
        gemini_api_key=gemini_api_key,
        db_csv_path=_prepare_catalog_input(catalog_path, output_dir),
        match_mode=match_mode,
    )
    result_df, stats = matcher.process_excel(str(input_path), str(result_path))

    diagnostics_payload = getattr(matcher, "last_match_diagnostics_payload", None)
    if not isinstance(diagnostics_payload, dict):
        diagnostics_payload = reconstruct_match_diagnostics(
            result_df,
            run_id=run_stamp,
        )

    coverage_payload = None
    if include_audit:
        coverage_payload = build_catalog_coverage_audit(
            result_df,
            run_id=run_stamp,
            catalog_source_path=Path(matcher.db_csv_path),
            catalog_source_kind="search" if is_search_catalog_path(matcher.db_csv_path) else "merged",
            diagnostics_payload=diagnostics_payload,
        )
        diagnostics_payload = enrich_match_diagnostics_payload(
            diagnostics_payload,
            coverage_audit_payload=coverage_payload,
        )

    apply_match_diagnostics_to_result_dataframe(result_df, diagnostics_payload)
    stats = apply_match_diagnostics_summary_to_stats(stats, diagnostics_payload)
    result_df.to_excel(result_path, index=False)
    result_df.to_csv(output_dir / "result.csv", index=False, encoding="utf-8-sig")

    diagnostic_rows = list(diagnostics_payload.get("rows") or [])
    diagnostics_by_row = {
        int(row.get("run_row_number")): row
        for row in diagnostic_rows
        if isinstance(row, dict) and int(row.get("run_row_number") or 0) > 1
    }
    coverage_rows = list((coverage_payload or {}).get("rows") or [])
    coverage_by_row = {
        int(row.get("run_row_number")): row
        for row in coverage_rows
        if isinstance(row, dict) and int(row.get("run_row_number") or 0) > 1
    }

    per_case_records = []
    for row_number, case in enumerate(selected_cases, start=2):
        dataframe_index = row_number - 2
        per_case_records.append(
            _per_case_record(
                case,
                result_df.iloc[dataframe_index],
                diagnostics_by_row.get(row_number),
                coverage_by_row.get(row_number),
            )
        )

    per_case_df = pd.DataFrame(per_case_records)
    resolver_summary_df = _summary_frame(per_case_df, group_column="resolver_name")
    resolver_path_summary_df = _summary_frame(per_case_df, group_column="resolver_path")
    verifier_reason_summary_df = _summary_frame(per_case_df, group_column="verifier_reason")
    family_summary_df = _summary_frame(per_case_df, group_column="expected_family")
    suite_summary_df = _summary_frame(per_case_df, group_column="suite")
    false_positive_df = per_case_df[per_case_df["failure_bucket"] == "false_positive"].copy()
    false_negative_df = per_case_df[per_case_df["failure_bucket"] == "false_negative"].copy()

    metrics = _benchmark_metrics(per_case_df)
    metadata = {
        "benchmark_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "fixture_path": str(Path(fixture_path)),
        "tier": tier,
        "match_mode": match_mode,
        "gemini_enabled": bool(_clean_text(gemini_api_key)),
        "selected_cases": len(selected_cases),
        "stats": stats,
    }
    metadata.update(_catalog_metadata(Path(matcher.db_csv_path)))
    summary_payload = {
        "metadata": metadata,
        "metrics": metrics,
        "suite_summary": suite_summary_df.to_dict(orient="records"),
        "family_summary": family_summary_df.to_dict(orient="records"),
        "resolver_summary": resolver_summary_df.to_dict(orient="records"),
        "resolver_path_summary": resolver_path_summary_df.to_dict(orient="records"),
        "verifier_reason_summary": verifier_reason_summary_df.to_dict(orient="records"),
    }

    _write_json(output_dir / "summary.json", summary_payload)
    _write_json(output_dir / "diagnostics.json", diagnostics_payload)
    if coverage_payload is not None:
        _write_json(output_dir / "coverage_audit.json", coverage_payload)

    per_case_df.to_csv(output_dir / "per_case.csv", index=False, encoding="utf-8-sig")
    resolver_summary_df.to_csv(output_dir / "resolver_summary.csv", index=False, encoding="utf-8-sig")
    resolver_path_summary_df.to_csv(output_dir / "resolver_path_summary.csv", index=False, encoding="utf-8-sig")
    verifier_reason_summary_df.to_csv(output_dir / "verifier_reason_summary.csv", index=False, encoding="utf-8-sig")
    family_summary_df.to_csv(output_dir / "family_summary.csv", index=False, encoding="utf-8-sig")
    suite_summary_df.to_csv(output_dir / "suite_summary.csv", index=False, encoding="utf-8-sig")
    false_positive_df.to_csv(output_dir / "false_positives.csv", index=False, encoding="utf-8-sig")
    false_negative_df.to_csv(output_dir / "false_negatives.csv", index=False, encoding="utf-8-sig")

    diagnostics_export = _build_excel_workbook_bytes(
        [
            ("summary", pd.DataFrame([metrics])),
            ("details", prepare_match_diagnostics_table(diagnostics_payload)),
            ("resolver_summary", prepare_match_diagnostics_resolver_table(diagnostics_payload)),
            ("reason_summary", prepare_match_diagnostics_reason_table(diagnostics_payload)),
            ("root_causes", prepare_match_diagnostics_root_cause_table(diagnostics_payload)),
        ]
    )
    (output_dir / "diagnostics.xlsx").write_bytes(diagnostics_export)

    if coverage_payload is not None:
        coverage_export = _build_excel_workbook_bytes(
            [
                ("summary", pd.DataFrame([coverage_payload.get("summary", {})])),
                ("details", prepare_catalog_coverage_audit_table(coverage_payload)),
                ("families", prepare_catalog_coverage_family_table(coverage_payload)),
                ("gap_reasons", prepare_catalog_gap_reason_table(coverage_payload)),
            ]
        )
        (output_dir / "coverage_audit.xlsx").write_bytes(coverage_export)

    print(f"Benchmark artifacts saved to: {output_dir}")
    print(json.dumps({"metrics": metrics, "git_commit": metadata["git_commit"]}, ensure_ascii=False, indent=2))
    return output_dir


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run manual golden-set benchmark for ReMo matcher.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE_PATH), help="Path to golden benchmark CSV fixture.")
    parser.add_argument("--output-root", default=str(DEFAULT_BENCHMARK_ROOT), help="Directory for benchmark artifacts.")
    parser.add_argument("--catalog", default=None, help="Explicit catalog path to pass into matcher.")
    parser.add_argument("--tier", choices=sorted(VALID_TIERS), default="smoke", help="Fixture tier to run.")
    parser.add_argument("--match-mode", default=MATCH_MODE_EXACT, help="Matcher mode to use for benchmark run.")
    parser.add_argument(
        "--skip-audit",
        action="store_true",
        help="Skip catalog coverage audit if you only want matcher + diagnostics timing.",
    )
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()
    run_benchmark(
        fixture_path=args.fixture,
        output_root=args.output_root,
        catalog_path=args.catalog,
        tier=args.tier,
        match_mode=args.match_mode,
        include_audit=not args.skip_audit,
    )


if __name__ == "__main__":
    main()
