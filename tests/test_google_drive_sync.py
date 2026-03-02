import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from google_drive_sync import DriveAccessReport, DriveCsvFile, extract_drive_folder_id, sync_drive_folder_csvs


class GoogleDriveSyncTests(unittest.TestCase):
    def test_extract_folder_id_from_full_url(self):
        url = "https://drive.google.com/drive/folders/1T5pU2JsABjJbCHNM4WMSgzbvc9E4iUaM?usp=sharing"
        self.assertEqual(extract_drive_folder_id(url), "1T5pU2JsABjJbCHNM4WMSgzbvc9E4iUaM")

    def test_extract_folder_id_from_plain_id(self):
        folder_id = "1T5pU2JsABjJbCHNM4WMSgzbvc9E4iUaM"
        self.assertEqual(extract_drive_folder_id(folder_id), folder_id)

    def test_extract_folder_id_raises_on_invalid(self):
        with self.assertRaises(ValueError):
            extract_drive_folder_id("https://example.com/no-drive")

    def test_sync_drive_folder_csvs_prunes_orphan_destination_csvs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            destination_dir = Path(tmp_dir)
            stale_path = destination_dir / "stale.csv"
            stale_path.write_text("old", encoding="utf-8")

            file_info = DriveCsvFile(
                file_id="1",
                name="fresh.csv",
                modified_time="2026-01-01T00:00:00Z",
                size_bytes=10,
            )

            def fake_download(service, drive_file, destination):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("fresh", encoding="utf-8")
                return destination

            with (
                patch(
                    "google_drive_sync.check_drive_folder_access",
                    return_value=DriveAccessReport(folder_id="folder", csv_count=1, can_access=True),
                ),
                patch("google_drive_sync._build_drive_service", return_value=object()),
                patch("google_drive_sync._list_csv_files", return_value=[file_info]),
                patch("google_drive_sync._download_csv_file", side_effect=fake_download),
            ):
                paths = sync_drive_folder_csvs(
                    folder_url_or_id="folder",
                    service_account_info={},
                    destination_dir=destination_dir,
                )

            self.assertEqual([path.name for path in paths], ["fresh.csv"])
            self.assertTrue((destination_dir / "fresh.csv").exists())
            self.assertFalse(stale_path.exists())


if __name__ == "__main__":
    unittest.main()
