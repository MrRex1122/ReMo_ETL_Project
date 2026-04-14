"""Standalone processing worker — runs KP matching in a separate process.

Usage:
    python processing_worker.py <run_id> <settings_json_path>

This module is intentionally free of Streamlit imports so it can be
spawned as a subprocess without pulling in the Streamlit runtime.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from catalog_schema import normalize_header
from config import (
    get_matcher_gemini_chunk_size,
    get_matcher_gemini_max_chunks,
    get_matcher_gemini_shortlist_limit,
    get_matcher_local_recall_pool,
    get_matcher_parallel_requests,
    get_matcher_skip_weak_shortlist,
)
from matcher import MISSING_POSITION_TEXT, ReMoMatcher
from processing_runs import (
    build_run_artifacts,
    get_processing_run,
    mark_processing_run_completed,
    mark_processing_run_failed,
    mark_processing_run_interrupted,
    mark_processing_run_started,
    save_processing_run_draft,
    write_processing_run_error,
    write_processing_run_progress,
    write_processing_run_result,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper functions (extracted from app.py, no Streamlit dependency)
# ---------------------------------------------------------------------------

_DEBUG_RESULT_COLUMNS = {
    "Ошибка сопоставления",
    "Путь категории",
    "Уровень уверенности",
    "Альтернативы",
    "Источник решения",
    "Совместимость решения",
    "Причина несовместимости",
    "Этап отказа",
    "Код причины",
    "Класс причины",
    "Verifier decision",
    "Auto accept",
    "Gemini shortlist",
    "Gemini visible candidates",
    "Gemini truncated",
}


def _looks_like_material_unit_cost_column(column_name: object) -> bool:
    normalized = normalize_header(column_name).lower().replace("ё", "е")
    compact = normalized.replace(" ", "")
    return (
        "стоим" in normalized
        and "материал" in normalized
        and "общ" not in normalized
        and "работ" not in normalized
        and ("за ед" in normalized or "за еди" in normalized or "заед" in compact)
    )


def build_main_kp_result_df(df: pd.DataFrame) -> pd.DataFrame:
    hidden_columns = set(_DEBUG_RESULT_COLUMNS)
    # Note: "Цена" is the DB price for the matched item — never hide it.
    # It is NOT a duplicate of input cost columns like "Стоимость материал за ед."
    visible_columns = [column for column in df.columns if column not in hidden_columns]
    if "Найденная номенклатура" in visible_columns:
        cutoff_index = visible_columns.index("Найденная номенклатура")
        visible_columns = visible_columns[: cutoff_index + 1]
    # Ensure key business-result columns are always included,
    # even if they were after the cutoff point or hidden.
    for result_col in ("Цена", "Причина отсутствия", "Требует проверки"):
        if result_col in df.columns and result_col not in visible_columns:
            visible_columns.append(result_col)
    return df.loc[:, visible_columns].copy()


def _is_source_query_column(column_name: object) -> bool:
    normalized = normalize_header(column_name).lower().replace("ё", "е")
    if "найден" in normalized:
        return False
    return "наименован" in normalized or "номенклатур" in normalized


def compute_business_run_summary(df: pd.DataFrame, stats: dict[str, Any] | None = None) -> dict[str, int]:
    if df is None or df.empty:
        return {
            "total": 0, "found": 0, "not_found": 0,
            "requires_review": 0, "errors": 0,
            "skipped_non_item": 0, "blank_rows": 0,
        }

    query_columns: list[str] = []
    preferred_query_column = str((stats or {}).get("input_query_column") or "").strip()
    if preferred_query_column and preferred_query_column in df.columns:
        query_columns.append(preferred_query_column)
    for column in df.columns:
        if column in query_columns:
            continue
        if _is_source_query_column(column):
            query_columns.append(str(column))

    if query_columns:
        nonempty_query_mask = pd.Series(False, index=df.index)
        for column in query_columns:
            nonempty_query_mask = nonempty_query_mask | (df[column].fillna("").astype(str).str.strip() != "")
    else:
        nonempty_query_mask = pd.Series(True, index=df.index)

    section_mask = pd.Series(False, index=df.index)
    if "Код причины" in df.columns:
        section_mask = section_mask | (
            df["Код причины"].fillna("").astype(str).str.strip().str.lower() == "section_row_detected"
        )
    if "Причина отсутствия" in df.columns:
        section_mask = section_mask | (
            df["Причина отсутствия"].fillna("").astype(str).str.contains("Строка-раздел", regex=False)
        )

    business_mask = nonempty_query_mask & ~section_mask

    if "Найденная номенклатура" in df.columns:
        missing_mask = (
            df["Найденная номенклатура"].isna()
            | (df["Найденная номенклатура"].astype(str).str.strip() == "")
            | (df["Найденная номенклатура"].astype(str).str.strip() == MISSING_POSITION_TEXT)
        )
    else:
        missing_mask = pd.Series(False, index=df.index)

    review_mask = pd.Series(False, index=df.index)
    if "Требует проверки" in df.columns:
        review_mask = df["Требует проверки"].fillna("").astype(str).str.lower() == "да"

    error_mask = pd.Series(False, index=df.index)
    if "Ошибка сопоставления" in df.columns:
        error_mask = df["Ошибка сопоставления"].fillna("").astype(str).str.strip() != ""

    return {
        "total": int(business_mask.sum()),
        "found": int((business_mask & ~missing_mask).sum()),
        "not_found": int((business_mask & missing_mask).sum()),
        "requires_review": int((business_mask & review_mask).sum()),
        "errors": int((business_mask & error_mask).sum()),
        "skipped_non_item": int(section_mask.sum()),
        "blank_rows": int((~nonempty_query_mask).sum()),
    }


# ---------------------------------------------------------------------------
# Matcher construction
# ---------------------------------------------------------------------------

def create_matcher_instance(db_csv: str, settings: dict[str, Any]) -> ReMoMatcher:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY не установлен")
    if not Path(db_csv).exists():
        raise FileNotFoundError(f"Файл не найден: {db_csv}")
    return ReMoMatcher(
        api_key,
        db_csv,
        parallel_requests=int(settings.get("parallel_requests", get_matcher_parallel_requests())),
        match_mode=str(settings.get("match_mode", "exact")),
        gemini_shortlist_limit=int(settings.get("gemini_shortlist_limit", get_matcher_gemini_shortlist_limit())),
        gemini_chunk_size=int(settings.get("gemini_chunk_size", get_matcher_gemini_chunk_size())),
        gemini_max_chunks=int(settings.get("gemini_max_chunks", get_matcher_gemini_max_chunks())),
        local_recall_pool=int(settings.get("local_recall_pool", get_matcher_local_recall_pool())),
        skip_weak_shortlist=bool(settings.get("skip_weak_shortlist", get_matcher_skip_weak_shortlist())),
    )


# ---------------------------------------------------------------------------
# Cancel mechanism (file-based, cross-process)
# ---------------------------------------------------------------------------

def _cancel_flag_path(run_id: str) -> Path:
    return build_run_artifacts(run_id).run_dir / "cancel.flag"


def is_cancel_requested(run_id: str) -> bool:
    return _cancel_flag_path(run_id).exists()


def request_cancel(run_id: str) -> None:
    _cancel_flag_path(run_id).write_text("cancel", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main processing job
# ---------------------------------------------------------------------------

def run_processing_job(run_id: str, matcher_settings: dict[str, Any]) -> None:
    """Execute the full KP matching pipeline for *run_id*."""

    def _is_cancel_requested() -> bool:
        return is_cancel_requested(run_id)

    try:
        run = get_processing_run(run_id)
        if run is None:
            raise RuntimeError(f"Run not found: {run_id}")

        mark_processing_run_started(run_id)
        write_processing_run_progress(
            run_id, stage="matcher_init", percent=0.02,
            message="Инициализация matcher и загрузка каталога",
        )
        logger.info("🚀 Processing run started: %s", run_id)

        matcher = create_matcher_instance(str(run.catalog_source_path), matcher_settings)
        if _is_cancel_requested():
            raise InterruptedError("Run cancelled by user")

        artifacts = build_run_artifacts(run_id)
        write_processing_run_progress(
            run_id, stage="processing", percent=0.08,
            message="Matcher готов, начинается обработка файла",
        )
        logger.info("⏳ Processing run %s: processing %s", run_id, run.input_file_path)

        def _progress_callback(
            *, stage: str,
            current: int | None = None,
            total: int | None = None,
            message: str | None = None,
        ) -> None:
            percent = None
            if stage == "matching" and total:
                percent = 0.08 + (0.87 * (max(0, min(int(current or 0), int(total))) / max(1, int(total))))
            elif stage == "reading_excel":
                percent = 0.08
            elif stage == "saving_results":
                percent = 0.97
            write_processing_run_progress(
                run_id, stage=stage, current=current, total=total,
                message=message, percent=percent,
            )

        df_result, stats = matcher.process_excel(
            str(run.input_file_path),
            output_path=str(artifacts.result_xlsx_path),
            progress_callback=_progress_callback,
            cancel_requested=_is_cancel_requested,
            build_runtime_diagnostics=False,
        )

        if bool(stats.get("_interrupted")) or _is_cancel_requested():
            partial_total = int(stats.get("total", len(df_result)))
            partial_processed = int(stats.get("processed", 0))
            try:
                save_processing_run_draft(run_id, df_result)
            except Exception:
                logger.exception("Failed to save interrupted run draft: %s", run_id)
            write_processing_run_progress(
                run_id, stage="interrupted",
                current=partial_processed, total=partial_total,
                percent=(partial_processed / partial_total) if partial_total > 0 else 0.0,
                message="Обработка остановлена пользователем. Частичный черновик сохранен.",
            )
            mark_processing_run_interrupted(run_id, "Run cancelled by user")
            logger.info("🛑 Processing run interrupted: %s processed=%s total=%s", run_id, partial_processed, partial_total)
            return

        write_processing_run_progress(
            run_id, stage="saving_results",
            current=int(stats.get("total", len(df_result))),
            total=int(stats.get("total", len(df_result))),
            percent=0.98, message="Сохранение результатов",
        )
        stats["diagnostics_mode"] = "lite"
        stats["runtime_diagnostics_saved"] = False
        business_summary = compute_business_run_summary(df_result, stats)
        stats["business_summary"] = business_summary
        stats["business_total"] = int(business_summary.get("total", 0))
        stats["business_found"] = int(business_summary.get("found", 0))
        stats["business_not_found"] = int(business_summary.get("not_found", 0))
        stats["business_requires_review"] = int(business_summary.get("requires_review", 0))
        stats["business_errors"] = int(business_summary.get("errors", 0))
        stats["business_skipped_non_item"] = int(business_summary.get("skipped_non_item", 0))
        stats["business_blank_rows"] = int(business_summary.get("blank_rows", 0))

        try:
            build_main_kp_result_df(df_result).to_excel(
                artifacts.result_xlsx_path, index=False, engine="openpyxl",
            )
        except Exception:
            logger.exception("Failed to save trimmed KP workbook for run %s", run_id)

        write_processing_run_result(run_id, df_result, stats)
        rows_total = int(business_summary.get("total", 0))
        found_count = int(business_summary.get("found", 0))
        missing_count = int(business_summary.get("not_found", 0))
        requires_review_count = int(business_summary.get("requires_review", 0))
        mark_processing_run_completed(
            run_id,
            result_csv_path=artifacts.result_csv_path,
            stats_json_path=artifacts.stats_json_path,
            rows_total=rows_total,
            found_count=found_count,
            missing_count=missing_count,
            requires_review_count=requires_review_count,
        )
        write_processing_run_progress(
            run_id, stage="completed",
            current=rows_total, total=rows_total,
            percent=1.0, message="Обработка завершена",
        )
        logger.info("✅ Processing run completed: %s", run_id)
    except InterruptedError as exc:
        logger.info("🛑 Processing run interrupted: %s reason=%s", run_id, exc)
        write_processing_run_progress(
            run_id, stage="interrupted",
            message=str(exc) or "Обработка остановлена пользователем",
        )
        mark_processing_run_interrupted(run_id, str(exc) or "Run cancelled by user")
    except Exception as exc:
        logger.error("❌ Processing run failed: %s", run_id, exc_info=True)
        error_text = str(exc)
        try:
            write_processing_run_error(run_id, error_text)
            write_processing_run_progress(run_id, stage="failed", message=error_text)
        except Exception:
            logger.exception("Failed to write run error file: %s", run_id)
        mark_processing_run_failed(run_id, error_text)


# ---------------------------------------------------------------------------
# CLI entry point — called via subprocess.Popen from Streamlit app
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <run_id> <settings_json_path>", file=sys.stderr)
        sys.exit(1)

    _run_id = sys.argv[1]
    _settings_path = Path(sys.argv[2])
    _settings = json.loads(_settings_path.read_text(encoding="utf-8"))
    logger.info("Worker started: run_id=%s settings=%s", _run_id, _settings_path)
    run_processing_job(_run_id, _settings)
