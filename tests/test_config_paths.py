import os
import unittest
from pathlib import Path

import config


class ConfigPathTests(unittest.TestCase):
    def setUp(self):
        self._backup = {k: os.environ.get(k) for k in (
            "REMO_UPLOAD_DIR",
            "REMO_DB_CSV",
            "REMO_PRICE_RAW_CSV",
            "REMO_PRICE_CONVERTED_CSV",
            "REMO_SAMPLE_XLSX",
            "RAILWAY_VOLUME_MOUNT_PATH",
            "REMO_MATCHER_PARALLEL_REQUESTS",
            "REMO_MATCHER_CACHE_DB",
            "REMO_MATCHER_MODELS",
            "REMO_MATCHER_LOCAL_CONFIDENCE_THRESHOLD",
            "REMO_MATCHER_LOCAL_MARGIN_THRESHOLD",
            "REMO_MATCHER_CONTEXT_CHUNK_SIZE",
            "REMO_MATCHER_MAX_CONTEXT_CHUNKS",
            "REMO_MATCHER_RETRIEVAL_CANDIDATES",
            "REMO_MATCHER_GEMINI_SHORTLIST_LIMIT",
            "REMO_MATCHER_GEMINI_CHUNK_SIZE",
            "REMO_MATCHER_GEMINI_MAX_CHUNKS",
            "REMO_MATCHER_LOCAL_RECALL_POOL",
            "REMO_MATCHER_SKIP_WEAK_SHORTLIST",
        )}

    def tearDown(self):
        for key, value in self._backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_explicit_path_strips_whitespace(self):
        expected = config.PROJECT_ROOT / "data" / "catalog.csv"
        actual = config.get_catalog_csv_path("  data/catalog.csv  ")
        self.assertEqual(actual, expected)

    def test_blank_explicit_falls_back_to_env(self):
        os.environ["REMO_DB_CSV"] = "  env/catalog.csv  "
        expected = config.PROJECT_ROOT / "env" / "catalog.csv"
        actual = config.get_catalog_csv_path("   ")
        self.assertEqual(actual, expected)

    def test_blank_upload_env_uses_default_upload_dir(self):
        os.environ["REMO_UPLOAD_DIR"] = "   "
        os.environ.pop("RAILWAY_VOLUME_MOUNT_PATH", None)
        self.assertEqual(config.get_upload_dir(), config.DEFAULT_UPLOAD_DIR)

    def test_blank_upload_env_uses_railway_volume_when_available(self):
        os.environ["REMO_UPLOAD_DIR"] = "   "
        os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = "/data"
        self.assertEqual(config.get_upload_dir(), Path("/data").resolve() / "remo_data")

    def test_windows_style_path_is_not_prefixed_with_project_root(self):
        os.environ["REMO_DB_CSV"] = r"C:\catalog\price_clean.csv"
        actual = config.get_catalog_csv_path()
        self.assertEqual(str(actual), r"C:\catalog\price_clean.csv")

    def test_matcher_parallel_requests_clamped(self):
        os.environ["REMO_MATCHER_PARALLEL_REQUESTS"] = "99"
        self.assertEqual(config.get_matcher_parallel_requests(), 10)

    def test_matcher_parallel_requests_fallback_on_invalid(self):
        os.environ["REMO_MATCHER_PARALLEL_REQUESTS"] = "oops"
        self.assertEqual(
            config.get_matcher_parallel_requests(),
            config.DEFAULT_MATCHER_PARALLEL_REQUESTS,
        )

    def test_matcher_cache_db_path_uses_env_override(self):
        os.environ["REMO_MATCHER_CACHE_DB"] = "cache/custom.db"
        expected = config.PROJECT_ROOT / "cache" / "custom.db"
        self.assertEqual(config.get_matcher_cache_db_path(), expected)

    def test_matcher_local_thresholds_clamped(self):
        os.environ["REMO_MATCHER_LOCAL_CONFIDENCE_THRESHOLD"] = "1.7"
        os.environ["REMO_MATCHER_LOCAL_MARGIN_THRESHOLD"] = "-0.4"
        self.assertEqual(config.get_matcher_local_confidence_threshold(), 1.0)
        self.assertEqual(config.get_matcher_local_margin_threshold(), 0.0)

    def test_matcher_local_thresholds_fallback_on_invalid(self):
        os.environ["REMO_MATCHER_LOCAL_CONFIDENCE_THRESHOLD"] = "oops"
        os.environ["REMO_MATCHER_LOCAL_MARGIN_THRESHOLD"] = "oops"
        self.assertEqual(
            config.get_matcher_local_confidence_threshold(),
            config.DEFAULT_MATCHER_LOCAL_CONFIDENCE_THRESHOLD,
        )
        self.assertEqual(
            config.get_matcher_local_margin_threshold(),
            config.DEFAULT_MATCHER_LOCAL_MARGIN_THRESHOLD,
        )


    def test_matcher_context_chunk_settings_clamped(self):
        os.environ["REMO_MATCHER_CONTEXT_CHUNK_SIZE"] = "5000"
        os.environ["REMO_MATCHER_MAX_CONTEXT_CHUNKS"] = "99"
        self.assertEqual(config.get_matcher_context_chunk_size(), 1000)
        self.assertEqual(config.get_matcher_max_context_chunks(), 10)

    def test_matcher_context_chunk_settings_fallback_on_invalid(self):
        os.environ["REMO_MATCHER_CONTEXT_CHUNK_SIZE"] = "oops"
        os.environ["REMO_MATCHER_MAX_CONTEXT_CHUNKS"] = "oops"
        self.assertEqual(
            config.get_matcher_context_chunk_size(),
            config.DEFAULT_MATCHER_CONTEXT_CHUNK_SIZE,
        )
        self.assertEqual(
            config.get_matcher_max_context_chunks(),
            config.DEFAULT_MATCHER_MAX_CONTEXT_CHUNKS,
        )

    def test_matcher_retrieval_candidates_clamped(self):
        os.environ["REMO_MATCHER_RETRIEVAL_CANDIDATES"] = "99999"
        self.assertEqual(config.get_matcher_retrieval_candidates(), 10000)

    def test_matcher_retrieval_candidates_fallback_on_invalid(self):
        os.environ["REMO_MATCHER_RETRIEVAL_CANDIDATES"] = "oops"
        self.assertEqual(
            config.get_matcher_retrieval_candidates(),
            config.DEFAULT_MATCHER_RETRIEVAL_CANDIDATES,
        )

    def test_matcher_gemini_tuning_clamped(self):
        os.environ["REMO_MATCHER_GEMINI_SHORTLIST_LIMIT"] = "999"
        os.environ["REMO_MATCHER_GEMINI_CHUNK_SIZE"] = "2"
        os.environ["REMO_MATCHER_GEMINI_MAX_CHUNKS"] = "99"
        os.environ["REMO_MATCHER_LOCAL_RECALL_POOL"] = "5"
        self.assertEqual(config.get_matcher_gemini_shortlist_limit(), 200)
        self.assertEqual(config.get_matcher_gemini_chunk_size(), 6)
        self.assertEqual(config.get_matcher_gemini_max_chunks(), 12)
        self.assertEqual(config.get_matcher_local_recall_pool(), 100)

    def test_matcher_gemini_tuning_fallback_on_invalid(self):
        os.environ["REMO_MATCHER_GEMINI_SHORTLIST_LIMIT"] = "oops"
        os.environ["REMO_MATCHER_GEMINI_CHUNK_SIZE"] = "oops"
        os.environ["REMO_MATCHER_GEMINI_MAX_CHUNKS"] = "oops"
        os.environ["REMO_MATCHER_LOCAL_RECALL_POOL"] = "oops"
        self.assertEqual(
            config.get_matcher_gemini_shortlist_limit(),
            config.DEFAULT_MATCHER_GEMINI_SHORTLIST_LIMIT,
        )
        self.assertEqual(
            config.get_matcher_gemini_chunk_size(),
            config.DEFAULT_MATCHER_GEMINI_CHUNK_SIZE,
        )
        self.assertEqual(
            config.get_matcher_gemini_max_chunks(),
            config.DEFAULT_MATCHER_GEMINI_MAX_CHUNKS,
        )
        self.assertEqual(
            config.get_matcher_local_recall_pool(),
            config.DEFAULT_MATCHER_LOCAL_RECALL_POOL,
        )

    def test_matcher_skip_weak_shortlist_bool_parsing(self):
        os.environ["REMO_MATCHER_SKIP_WEAK_SHORTLIST"] = "true"
        self.assertTrue(config.get_matcher_skip_weak_shortlist())
        os.environ["REMO_MATCHER_SKIP_WEAK_SHORTLIST"] = "off"
        self.assertFalse(config.get_matcher_skip_weak_shortlist())
        os.environ["REMO_MATCHER_SKIP_WEAK_SHORTLIST"] = "oops"
        self.assertEqual(
            config.get_matcher_skip_weak_shortlist(),
            config.DEFAULT_MATCHER_SKIP_WEAK_SHORTLIST,
        )

    def test_matcher_models_parsed_from_env(self):
        os.environ["REMO_MATCHER_MODELS"] = " model-a, model-b ,,  model-c "
        self.assertEqual(config.get_matcher_models(), ["model-a", "model-b", "model-c"])

    def test_matcher_models_fallback_on_blank(self):
        os.environ["REMO_MATCHER_MODELS"] = " , , "
        self.assertEqual(
            config.get_matcher_models(),
            [value.strip() for value in config.DEFAULT_MATCHER_MODELS.split(",") if value.strip()],
        )


if __name__ == "__main__":
    unittest.main()
