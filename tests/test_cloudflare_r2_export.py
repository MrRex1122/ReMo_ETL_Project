import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cloudflare_r2_export import (
    build_r2_endpoint_url,
    upload_file_to_r2,
)


class CloudflareR2ExportTests(unittest.TestCase):
    def test_build_r2_endpoint_url_uses_account_id(self):
        self.assertEqual(
            build_r2_endpoint_url("abc123"),
            "https://abc123.r2.cloudflarestorage.com",
        )

    def test_upload_file_to_r2_uses_presigned_url_when_public_base_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "catalog.csv"
            source_path.write_text("Наименование;Артикул\nКабель;A-1\n", encoding="utf-8")

            client = Mock()
            client.generate_presigned_url.return_value = "https://signed.example.com/download"

            with (
                patch("cloudflare_r2_export._build_r2_client", return_value=client),
                patch("cloudflare_r2_export._build_transfer_config", return_value=object()),
            ):
                result = upload_file_to_r2(
                    source_path=source_path,
                    account_id="abc123",
                    bucket="exports",
                    access_key_id="key",
                    secret_access_key="secret",
                    object_key="catalog-exports/demo.csv",
                )

            client.upload_file.assert_called_once()
            client.generate_presigned_url.assert_called_once()
            self.assertEqual(result.bucket, "exports")
            self.assertEqual(result.object_key, "catalog-exports/demo.csv")
            self.assertEqual(result.download_url, "https://signed.example.com/download")

    def test_upload_file_to_r2_uses_public_base_url_when_provided(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "catalog.csv"
            source_path.write_text("Наименование;Артикул\nКабель;A-1\n", encoding="utf-8")

            client = Mock()

            with (
                patch("cloudflare_r2_export._build_r2_client", return_value=client),
                patch("cloudflare_r2_export._build_transfer_config", return_value=object()),
            ):
                result = upload_file_to_r2(
                    source_path=source_path,
                    account_id="abc123",
                    bucket="exports",
                    access_key_id="key",
                    secret_access_key="secret",
                    object_key="catalog-exports/folder/demo file.csv",
                    public_base_url="https://pub.example.com/base/",
                )

            client.upload_file.assert_called_once()
            client.generate_presigned_url.assert_not_called()
            self.assertEqual(
                result.download_url,
                "https://pub.example.com/base/catalog-exports/folder/demo%20file.csv",
            )


if __name__ == "__main__":
    unittest.main()
