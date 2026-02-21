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
        self.assertEqual(config.get_upload_dir(), Path("/data/remo_data"))

    def test_windows_style_path_is_not_prefixed_with_project_root(self):
        os.environ["REMO_DB_CSV"] = r"D:\Data\Downloads\upload\price_clean.csv"
        actual = config.get_catalog_csv_path()
        self.assertEqual(str(actual), r"D:\Data\Downloads\upload\price_clean.csv")

    def test_matcher_parallel_requests_clamped(self):
        os.environ["REMO_MATCHER_PARALLEL_REQUESTS"] = "99"
        self.assertEqual(config.get_matcher_parallel_requests(), 10)

    def test_matcher_parallel_requests_fallback_on_invalid(self):
        os.environ["REMO_MATCHER_PARALLEL_REQUESTS"] = "oops"
        self.assertEqual(
            config.get_matcher_parallel_requests(),
            config.DEFAULT_MATCHER_PARALLEL_REQUESTS,
        )


if __name__ == "__main__":
    unittest.main()
