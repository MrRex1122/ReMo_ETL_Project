import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from processing_runs import (
    build_run_artifacts,
    create_processing_run,
    get_latest_completed_processing_run,
    get_preferred_run_for_restore,
    get_processing_run,
    has_processing_run_draft,
    load_processing_run_dataframe,
    load_processing_run_coverage_audit,
    load_processing_run_stats,
    mark_processing_run_completed,
    mark_processing_run_started,
    mark_stale_running_runs_as_interrupted,
    save_processing_run_draft,
    write_processing_run_coverage_audit,
    write_processing_run_result,
)


class ProcessingRunsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._old_upload_dir = os.environ.get("REMO_UPLOAD_DIR")
        self._old_cache_db = os.environ.get("REMO_MATCHER_CACHE_DB")
        root = Path(self._tmp_dir.name)
        os.environ["REMO_UPLOAD_DIR"] = str(root / "runtime")
        os.environ["REMO_MATCHER_CACHE_DB"] = str(root / "runtime" / "matcher_cache.db")

    def tearDown(self) -> None:
        if self._old_upload_dir is None:
            os.environ.pop("REMO_UPLOAD_DIR", None)
        else:
            os.environ["REMO_UPLOAD_DIR"] = self._old_upload_dir
        if self._old_cache_db is None:
            os.environ.pop("REMO_MATCHER_CACHE_DB", None)
        else:
            os.environ["REMO_MATCHER_CACHE_DB"] = self._old_cache_db
        self._tmp_dir.cleanup()

    def test_processing_run_persists_result_stats_and_draft(self):
        run = create_processing_run(
            input_filename="input.xlsx",
            catalog_source_path=Path("catalog.csv"),
            catalog_source_kind="search",
        )
        mark_processing_run_started(run.run_id)

        df_result = pd.DataFrame(
            [
                {
                    "Наименование оборудования, материалов и кабелей": "PDU",
                    "Найденная номенклатура": "PDU Basic",
                    "Требует проверки": "нет",
                }
            ]
        )
        stats = {"total": 1, "found": 1, "not_found": 0}

        write_processing_run_result(run.run_id, df_result, stats)
        artifacts = build_run_artifacts(run.run_id)
        mark_processing_run_completed(
            run.run_id,
            result_csv_path=artifacts.result_csv_path,
            stats_json_path=artifacts.stats_json_path,
            rows_total=1,
            found_count=1,
            missing_count=0,
            requires_review_count=0,
        )

        completed_run = get_processing_run(run.run_id)
        assert completed_run is not None
        self.assertEqual(completed_run.status, "completed")

        loaded_df = load_processing_run_dataframe(completed_run)
        loaded_stats = load_processing_run_stats(completed_run)
        self.assertEqual(len(loaded_df), 1)
        self.assertEqual(loaded_stats["found"], 1)

        draft_df = df_result.copy()
        draft_df.loc[0, "Найденная номенклатура"] = "PDU Advanced"
        save_processing_run_draft(run.run_id, draft_df)

        draft_run = get_processing_run(run.run_id)
        assert draft_run is not None
        self.assertTrue(has_processing_run_draft(draft_run))
        loaded_draft = load_processing_run_dataframe(draft_run)
        self.assertEqual(loaded_draft.loc[0, "Найденная номенклатура"], "PDU Advanced")

    def test_preferred_run_prefers_active_and_marks_stale_running_as_interrupted(self):
        completed = create_processing_run(
            input_filename="done.xlsx",
            catalog_source_path=Path("catalog.csv"),
            catalog_source_kind="merged",
        )
        df_result = pd.DataFrame([{"Наименование оборудования, материалов и кабелей": "A"}])
        stats = {"total": 1, "found": 0, "not_found": 1}
        write_processing_run_result(completed.run_id, df_result, stats)
        completed_artifacts = build_run_artifacts(completed.run_id)
        mark_processing_run_completed(
            completed.run_id,
            result_csv_path=completed_artifacts.result_csv_path,
            stats_json_path=completed_artifacts.stats_json_path,
            rows_total=1,
            found_count=0,
            missing_count=1,
            requires_review_count=1,
        )

        active = create_processing_run(
            input_filename="running.xlsx",
            catalog_source_path=Path("catalog.csv"),
            catalog_source_kind="search",
        )
        mark_processing_run_started(active.run_id)

        preferred_before = get_preferred_run_for_restore()
        assert preferred_before is not None
        self.assertEqual(preferred_before.run_id, active.run_id)

        interrupted_count = mark_stale_running_runs_as_interrupted()
        self.assertEqual(interrupted_count, 1)

        interrupted_run = get_processing_run(active.run_id)
        assert interrupted_run is not None
        self.assertEqual(interrupted_run.status, "interrupted")

        preferred_after = get_preferred_run_for_restore()
        assert preferred_after is not None
        self.assertEqual(preferred_after.run_id, completed.run_id)
        self.assertEqual(get_latest_completed_processing_run().run_id, completed.run_id)

    def test_processing_run_persists_catalog_coverage_audit(self):
        run = create_processing_run(
            input_filename="input.xlsx",
            catalog_source_path=Path("catalog.csv"),
            catalog_source_kind="search",
        )
        payload = {
            "run_id": run.run_id,
            "catalog_source_path": "catalog.csv",
            "catalog_source_kind": "search",
            "catalog_mtime": 123.0,
            "summary": {"rows_analyzed": 1},
            "rows": [
                {
                    "run_row_number": 2,
                    "query_text": "Патч-панель 24 порта",
                    "diagnosis": "catalog_has_compatible_candidates",
                }
            ],
        }

        audit_path = write_processing_run_coverage_audit(run.run_id, payload)
        self.assertTrue(audit_path.exists())

        loaded_payload = load_processing_run_coverage_audit(run.run_id)
        assert loaded_payload is not None
        self.assertEqual(loaded_payload["run_id"], run.run_id)
        self.assertEqual(loaded_payload["summary"]["rows_analyzed"], 1)


if __name__ == "__main__":
    unittest.main()
