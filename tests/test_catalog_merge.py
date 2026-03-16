import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import catalog_merge
import pandas as pd

from catalog_merge import (
    CANONICAL_ARTICLE_COLUMN,
    CANONICAL_NAME_COLUMN,
    CANONICAL_PRICE_COLUMN,
    _resolve_sharded_parallelism,
    _resolve_sharded_worker_limit_mb,
    _select_merge_mode,
    build_merged_catalog,
    get_catalog_readiness,
    refresh_merged_catalog,
    merge_catalog_frames,
)


class CatalogMergeTests(unittest.TestCase):
    def test_merge_catalog_frames_dedupes_by_article_then_name(self):
        df1 = pd.DataFrame([
            {"Наименование": "Кабель ВВГ 3x1.5", "Артикул": "A-1", "Цена розничная": 100},
            {"Наименование": "Автомат 16A", "Артикул": "", "Цена розничная": 200},
        ])
        df2 = pd.DataFrame([
            {"Наименование": "Кабель ВВГ 3x1.5", "Артикул": "A-1", "Цена розничная": 110},
            {"Наименование": "Автомат 16A", "Артикул": None, "Цена розничная": 210},
        ])

        merged = merge_catalog_frames([df1, df2])

        self.assertEqual(len(merged), 2)
        cable = merged[merged["Артикул"] == "A-1"].iloc[0]
        self.assertEqual(float(cable["Цена розничная"]), 100)

    def test_merge_catalog_frames_treats_unknown_article_as_missing(self):
        df1 = pd.DataFrame([
            {"Наименование": "Кабель UTP cat6", "Артикул": "UNKNOWN", "Цена розничная": 100},
            {"Наименование": "PDU 19", "Артикул": "PDU-1", "Цена розничная": 200},
        ])
        df2 = pd.DataFrame([
            {"Наименование": "Кабель UTP cat6", "Артикул": "", "Цена розничная": 110},
            {"Наименование": "Розетка RJ45", "Артикул": "UNKNOWN", "Цена розничная": 300},
        ])

        merged = merge_catalog_frames([df1, df2])

        self.assertEqual(len(merged), 3)
        self.assertEqual(int((merged["Наименование"] == "Кабель UTP cat6").sum()), 1)

    def test_build_merged_catalog_from_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель ВВГ 3x1.5;A-1;100\n",
                encoding="utf-8",
            )
            (root / "price17_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nАвтомат 16A;;200\n",
                encoding="utf-8",
            )

            output = build_merged_catalog(root, root / "price_clean_merged.csv")

            self.assertTrue(output.exists())
            merged_df = pd.read_csv(output, sep=';', encoding='utf-8')
            self.assertEqual(len(merged_df), 2)
            self.assertFalse((root / "price_clean_merged.csv.lock").exists())
            self.assertEqual(list(root.glob("price_clean_merged.csv.*.part")), [])

    def test_build_merged_catalog_skips_malformed_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bad = root / "bad_clean.csv"
            bad.write_text(
                "Наименование;Артикул;Цена розничная\n"
                "Товар1;A1;100\n"
                "Товар2;A2;200;EXTRA\n"
                "Товар3;A3;300\n",
                encoding="utf-8",
            )

            output = build_merged_catalog(root, root / "price_clean_merged.csv")
            merged_df = pd.read_csv(output, sep=';', encoding='utf-8')
            self.assertEqual(len(merged_df), 2)
            self.assertSetEqual(set(merged_df["Артикул"].astype(str)), {"A1", "A3"})

    def test_build_merged_catalog_prefers_valid_price_and_keeps_union_columns(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            extra_column = "Тип изделия"
            (root / "price14_clean.csv").write_text(
                f"{CANONICAL_NAME_COLUMN};{CANONICAL_ARTICLE_COLUMN};{CANONICAL_PRICE_COLUMN}\n"
                "PDU 19;PDU-1;\n",
                encoding="utf-8",
            )
            (root / "price17_clean.csv").write_text(
                f"{CANONICAL_NAME_COLUMN};{CANONICAL_ARTICLE_COLUMN};{CANONICAL_PRICE_COLUMN};{extra_column}\n"
                "PDU 19;PDU-1;150;PDU\n",
                encoding="utf-8",
            )

            output = build_merged_catalog(root, root / "price_clean_merged.csv")
            merged_df = pd.read_csv(output, sep=";", encoding="utf-8")

            self.assertEqual(len(merged_df), 1)
            self.assertIn(extra_column, merged_df.columns)
            self.assertEqual(float(merged_df.iloc[0][CANONICAL_PRICE_COLUMN]), 150.0)
            self.assertEqual(merged_df.iloc[0][extra_column], "PDU")

    def test_build_merged_catalog_replaces_orphan_lock_from_dead_pid(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output = root / "price_clean_merged.csv"
            lock_path = root / "price_clean_merged.csv.lock"
            (root / "price14_clean.csv").write_text(
                f"{CANONICAL_NAME_COLUMN};{CANONICAL_ARTICLE_COLUMN};{CANONICAL_PRICE_COLUMN}\n"
                "Кабель;A-1;100\n",
                encoding="utf-8",
            )
            lock_path.write_text("999999\n0\n", encoding="utf-8")

            resolved = build_merged_catalog(root, output)

            self.assertEqual(resolved, output)
            self.assertTrue(output.exists())
            self.assertFalse(lock_path.exists())

    def test_get_catalog_readiness_reports_missing_stale_and_ready(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            clean_file = root / "price14_clean.csv"
            clean_file.write_text(
                "Наименование;Артикул;Цена розничная\nКабель;A-1;100\n",
                encoding="utf-8",
            )

            missing = get_catalog_readiness(root)
            self.assertEqual(missing.state, "missing")

            merged_path = refresh_merged_catalog(root)
            ready = get_catalog_readiness(root)
            self.assertEqual(ready.state, "ready")
            self.assertEqual(ready.merged_path, merged_path)

            stale_time = merged_path.stat().st_mtime + 10
            os.utime(clean_file, (stale_time, stale_time))
            stale = get_catalog_readiness(root)
            self.assertEqual(stale.state, "stale")

    def test_get_catalog_readiness_reports_invalid_when_no_clean_sources(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readiness = get_catalog_readiness(root)
            self.assertEqual(readiness.state, "invalid")

    def test_select_merge_mode_defaults_to_streaming_for_invalid_env(self):
        with patch.dict(os.environ, {"REMO_MERGE_MODE": "broken-value"}, clear=False):
            self.assertEqual(_select_merge_mode(), "streaming")

    def test_select_merge_mode_defaults_to_sharded_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_select_merge_mode(), "sharded")

    def test_resolve_sharded_parallelism_clamps_invalid_values(self):
        with patch.dict(
            os.environ,
            {
                "REMO_SHARD_MERGE_WORKERS": "0",
                "REMO_SHARD_MERGE_SHARDS": "999",
                "REMO_MERGE_MAX_RSS_MB": "4096",
            },
            clear=False,
        ):
            workers, shards = _resolve_sharded_parallelism()
            self.assertEqual(workers, 1)
            self.assertEqual(shards, 128)
            self.assertEqual(_resolve_sharded_worker_limit_mb(workers), 3072)

    def test_build_merged_catalog_supports_sharded_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель;A-1;100\n",
                encoding="utf-8",
            )
            (root / "price15_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nАвтомат;B-1;200\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "REMO_MERGE_MODE": "sharded",
                    "REMO_SHARD_MERGE_WORKERS": "1",
                    "REMO_SHARD_MERGE_SHARDS": "4",
                },
                clear=False,
            ):
                output = build_merged_catalog(root, root / "price_clean_merged.csv")

            merged_df = pd.read_csv(output, sep=";", encoding="utf-8")
            self.assertEqual(len(merged_df), 2)
            self.assertSetEqual(set(merged_df["Артикул"].astype(str)), {"A-1", "B-1"})

    def test_build_merged_catalog_sharded_matches_streaming_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output_streaming = root / "streaming.csv"
            output_sharded = root / "sharded.csv"
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nPDU 19;PDU-1;\nКабель UTP cat6;;150\n",
                encoding="utf-8",
            )
            (root / "price15_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная;Тип изделия\nPDU 19;PDU-1;200;PDU\nКабель UTP cat6;;180;Cable\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"REMO_MERGE_MODE": "streaming"}, clear=False):
                build_merged_catalog(root, output_streaming)
            with patch.dict(
                os.environ,
                {
                    "REMO_MERGE_MODE": "sharded",
                    "REMO_SHARD_MERGE_WORKERS": "1",
                    "REMO_SHARD_MERGE_SHARDS": "4",
                },
                clear=False,
            ):
                build_merged_catalog(root, output_sharded)

            streaming_df = pd.read_csv(output_streaming, sep=";", encoding="utf-8").sort_values(
                by=["Артикул", "Наименование"], na_position="last"
            ).reset_index(drop=True)
            sharded_df = pd.read_csv(output_sharded, sep=";", encoding="utf-8").sort_values(
                by=["Артикул", "Наименование"], na_position="last"
            ).reset_index(drop=True)

            self.assertEqual(streaming_df.to_dict("records"), sharded_df.to_dict("records"))

    def test_build_merged_catalog_falls_back_to_streaming_when_sharded_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output = root / "price_clean_merged.csv"
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель;A-1;100\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"REMO_MERGE_MODE": "sharded"}, clear=False):
                with patch.object(catalog_merge, "_build_merged_catalog_sharded", side_effect=MemoryError("oom")):
                    resolved = build_merged_catalog(root, output)

            self.assertEqual(resolved, output)
            self.assertTrue(output.exists())

    def test_build_merged_catalog_replaces_orphan_lock_in_sharded_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output = root / "price_clean_merged.csv"
            lock_path = root / "price_clean_merged.csv.lock"
            (root / "price14_clean.csv").write_text(
                "Наименование;Артикул;Цена розничная\nКабель;A-1;100\n",
                encoding="utf-8",
            )
            lock_path.write_text("999999\n0\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "REMO_MERGE_MODE": "sharded",
                    "REMO_SHARD_MERGE_WORKERS": "1",
                    "REMO_SHARD_MERGE_SHARDS": "4",
                },
                clear=False,
            ):
                resolved = build_merged_catalog(root, output)

            self.assertEqual(resolved, output)
            self.assertFalse(lock_path.exists())
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
