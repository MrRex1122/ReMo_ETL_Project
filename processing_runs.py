from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from config import get_matcher_cache_db_path, get_upload_dir

RUN_STATUS = Literal["queued", "running", "completed", "failed", "interrupted"]
ACTIVE_STATUSES = ("queued", "running")

_ACTIVE_RUN_THREADS: dict[str, threading.Thread] = {}
_ACTIVE_RUN_THREADS_LOCK = threading.Lock()


@dataclass(frozen=True)
class ProcessingRunArtifacts:
    run_dir: Path
    input_path: Path
    result_csv_path: Path
    draft_csv_path: Path
    stats_json_path: Path
    error_txt_path: Path
    result_xlsx_path: Path


@dataclass(frozen=True)
class ProcessingRunRecord:
    run_id: str
    status: RUN_STATUS
    input_filename: str
    input_file_path: Path
    catalog_source_path: Path
    catalog_source_kind: Literal["search", "merged"]
    result_csv_path: Path | None
    draft_csv_path: Path | None
    stats_json_path: Path | None
    error_text: str | None
    rows_total: int | None
    found_count: int | None
    missing_count: int | None
    requires_review_count: int | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    updated_at: str


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    db_path = Path(get_matcher_cache_db_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_processing_runs_table_exists(conn)
    return conn


def _cleanup_dead_threads_locked() -> None:
    dead_run_ids = [run_id for run_id, thread in _ACTIVE_RUN_THREADS.items() if not thread.is_alive()]
    for run_id in dead_run_ids:
        _ACTIVE_RUN_THREADS.pop(run_id, None)


def register_processing_run_thread(run_id: str, thread: threading.Thread) -> None:
    with _ACTIVE_RUN_THREADS_LOCK:
        _cleanup_dead_threads_locked()
        _ACTIVE_RUN_THREADS[run_id] = thread


def unregister_processing_run_thread(run_id: str) -> None:
    with _ACTIVE_RUN_THREADS_LOCK:
        _ACTIVE_RUN_THREADS.pop(run_id, None)


def get_active_processing_run_ids() -> set[str]:
    with _ACTIVE_RUN_THREADS_LOCK:
        _cleanup_dead_threads_locked()
        return set(_ACTIVE_RUN_THREADS)


def is_processing_run_active(run_id: str) -> bool:
    with _ACTIVE_RUN_THREADS_LOCK:
        _cleanup_dead_threads_locked()
        return run_id in _ACTIVE_RUN_THREADS


def ensure_processing_runs_table_exists(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processing_runs (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            input_filename TEXT NOT NULL,
            input_file_path TEXT NOT NULL,
            catalog_source_path TEXT NOT NULL,
            catalog_source_kind TEXT NOT NULL,
            result_csv_path TEXT,
            draft_csv_path TEXT,
            stats_json_path TEXT,
            error_text TEXT,
            rows_total INTEGER,
            found_count INTEGER,
            missing_count INTEGER,
            requires_review_count INTEGER,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_processing_runs_created_at ON processing_runs(created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_processing_runs_status ON processing_runs(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_processing_runs_updated_at ON processing_runs(updated_at DESC)"
    )
    conn.commit()


def get_processing_runs_dir() -> Path:
    runs_dir = get_upload_dir() / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    return runs_dir


def build_run_artifacts(run_id: str) -> ProcessingRunArtifacts:
    run_dir = get_processing_runs_dir() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return ProcessingRunArtifacts(
        run_dir=run_dir,
        input_path=run_dir / "input.xlsx",
        result_csv_path=run_dir / "result.csv",
        draft_csv_path=run_dir / "draft.csv",
        stats_json_path=run_dir / "stats.json",
        error_txt_path=run_dir / "error.txt",
        result_xlsx_path=run_dir / "result.xlsx",
    )


def _path_or_none(raw: str | None) -> Path | None:
    if raw and str(raw).strip():
        return Path(raw)
    return None


def _row_to_record(row: sqlite3.Row) -> ProcessingRunRecord:
    return ProcessingRunRecord(
        run_id=str(row["run_id"]),
        status=str(row["status"]),
        input_filename=str(row["input_filename"]),
        input_file_path=Path(str(row["input_file_path"])),
        catalog_source_path=Path(str(row["catalog_source_path"])),
        catalog_source_kind=str(row["catalog_source_kind"]),
        result_csv_path=_path_or_none(row["result_csv_path"]),
        draft_csv_path=_path_or_none(row["draft_csv_path"]),
        stats_json_path=_path_or_none(row["stats_json_path"]),
        error_text=row["error_text"],
        rows_total=row["rows_total"],
        found_count=row["found_count"],
        missing_count=row["missing_count"],
        requires_review_count=row["requires_review_count"],
        created_at=str(row["created_at"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        updated_at=str(row["updated_at"]),
    )


def create_processing_run(
    *,
    input_filename: str,
    catalog_source_path: Path,
    catalog_source_kind: Literal["search", "merged"],
) -> ProcessingRunRecord:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    timestamp = _now_iso()
    artifacts = build_run_artifacts(run_id)
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO processing_runs (
                run_id, status, input_filename, input_file_path, catalog_source_path, catalog_source_kind,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "queued",
                input_filename,
                str(artifacts.input_path),
                str(Path(catalog_source_path)),
                catalog_source_kind,
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM processing_runs WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise RuntimeError(f"Failed to create processing run {run_id}")
    return _row_to_record(row)


def mark_processing_run_started(run_id: str) -> None:
    timestamp = _now_iso()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE processing_runs
            SET status = ?, started_at = COALESCE(started_at, ?), updated_at = ?
            WHERE run_id = ?
            """,
            ("running", timestamp, timestamp, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def touch_processing_run(run_id: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE processing_runs SET updated_at = ? WHERE run_id = ?",
            (_now_iso(), run_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_processing_run_completed(
    run_id: str,
    *,
    result_csv_path: Path,
    stats_json_path: Path,
    rows_total: int,
    found_count: int,
    missing_count: int,
    requires_review_count: int,
) -> None:
    timestamp = _now_iso()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE processing_runs
            SET status = ?, result_csv_path = ?, stats_json_path = ?, rows_total = ?, found_count = ?,
                missing_count = ?, requires_review_count = ?, finished_at = ?, updated_at = ?
            WHERE run_id = ?
            """,
            (
                "completed",
                str(Path(result_csv_path)),
                str(Path(stats_json_path)),
                int(rows_total),
                int(found_count),
                int(missing_count),
                int(requires_review_count),
                timestamp,
                timestamp,
                run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def mark_processing_run_failed(run_id: str, error_text: str) -> None:
    timestamp = _now_iso()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE processing_runs
            SET status = ?, error_text = ?, finished_at = ?, updated_at = ?
            WHERE run_id = ?
            """,
            ("failed", error_text, timestamp, timestamp, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_processing_run_interrupted(
    run_id: str,
    reason: str = "Application restarted during background processing",
) -> None:
    timestamp = _now_iso()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE processing_runs
            SET status = ?, error_text = COALESCE(error_text, ?), finished_at = ?, updated_at = ?
            WHERE run_id = ? AND status IN ('queued', 'running')
            """,
            ("interrupted", reason, timestamp, timestamp, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_processing_run(run_id: str) -> ProcessingRunRecord | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM processing_runs WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_record(row)


def list_processing_runs(limit: int = 50) -> list[ProcessingRunRecord]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT * FROM processing_runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_record(row) for row in rows]


def get_latest_active_processing_run() -> ProcessingRunRecord | None:
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT * FROM processing_runs
            WHERE status IN ('queued', 'running')
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_record(row)


def get_latest_completed_processing_run() -> ProcessingRunRecord | None:
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT * FROM processing_runs
            WHERE status = 'completed'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_record(row)


def get_preferred_run_for_restore() -> ProcessingRunRecord | None:
    active_run = get_latest_active_processing_run()
    if active_run is not None:
        return active_run
    return get_latest_completed_processing_run()


def _write_text_atomic(path: Path, text: str) -> None:
    part_path = path.with_suffix(f"{path.suffix}.part")
    path.parent.mkdir(parents=True, exist_ok=True)
    part_path.write_text(text, encoding="utf-8")
    part_path.replace(path)


def write_processing_run_result(run_id: str, df: pd.DataFrame, stats: dict[str, Any]) -> None:
    artifacts = build_run_artifacts(run_id)
    result_part_path = artifacts.result_csv_path.with_suffix(f"{artifacts.result_csv_path.suffix}.part")
    stats_part_path = artifacts.stats_json_path.with_suffix(f"{artifacts.stats_json_path.suffix}.part")

    df.to_csv(
        result_part_path,
        sep=";",
        index=False,
        encoding="utf-8",
    )
    with stats_part_path.open("w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)

    result_part_path.replace(artifacts.result_csv_path)
    stats_part_path.replace(artifacts.stats_json_path)


def load_processing_run_dataframe(run: ProcessingRunRecord, prefer_draft: bool = True) -> pd.DataFrame:
    draft_path = run.draft_csv_path if prefer_draft and run.draft_csv_path and run.draft_csv_path.exists() else None
    result_path = run.result_csv_path

    if draft_path is not None:
        try:
            return pd.read_csv(draft_path, sep=";", encoding="utf-8", low_memory=False)
        except Exception:
            if result_path is None or not result_path.exists():
                raise

    if result_path is None or not result_path.exists():
        raise FileNotFoundError(f"Run result is missing for {run.run_id}")
    return pd.read_csv(result_path, sep=";", encoding="utf-8", low_memory=False)


def load_processing_run_stats(run: ProcessingRunRecord) -> dict[str, Any]:
    if run.stats_json_path is None or not run.stats_json_path.exists():
        raise FileNotFoundError(f"Run stats are missing for {run.run_id}")
    with run.stats_json_path.open("r", encoding="utf-8") as fh:
        loaded = json.load(fh)
    if isinstance(loaded, dict):
        return loaded
    raise ValueError(f"Run stats payload is invalid for {run.run_id}")


def save_processing_run_draft(run_id: str, df: pd.DataFrame) -> Path:
    artifacts = build_run_artifacts(run_id)
    draft_part_path = artifacts.draft_csv_path.with_suffix(f"{artifacts.draft_csv_path.suffix}.part")
    df.to_csv(
        draft_part_path,
        sep=";",
        index=False,
        encoding="utf-8",
    )
    draft_part_path.replace(artifacts.draft_csv_path)

    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE processing_runs
            SET draft_csv_path = ?, updated_at = ?
            WHERE run_id = ?
            """,
            (str(artifacts.draft_csv_path), _now_iso(), run_id),
        )
        conn.commit()
    finally:
        conn.close()
    return artifacts.draft_csv_path


def has_processing_run_draft(run: ProcessingRunRecord) -> bool:
    return bool(run.draft_csv_path and run.draft_csv_path.exists())


def write_processing_run_error(run_id: str, error_text: str) -> Path:
    artifacts = build_run_artifacts(run_id)
    _write_text_atomic(artifacts.error_txt_path, error_text)
    return artifacts.error_txt_path


def mark_stale_running_runs_as_interrupted() -> int:
    active_run_ids = get_active_processing_run_ids()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT run_id FROM processing_runs
            WHERE status IN ('queued', 'running')
            """
        ).fetchall()
        stale_ids = [str(row["run_id"]) for row in rows if str(row["run_id"]) not in active_run_ids]
        if not stale_ids:
            return 0
        timestamp = _now_iso()
        conn.executemany(
            """
            UPDATE processing_runs
            SET status = 'interrupted',
                error_text = COALESCE(error_text, ?),
                finished_at = ?,
                updated_at = ?
            WHERE run_id = ?
            """,
            [
                (
                    "Application restarted during background processing",
                    timestamp,
                    timestamp,
                    run_id,
                )
                for run_id in stale_ids
            ],
        )
        conn.commit()
        return len(stale_ids)
    finally:
        conn.close()
