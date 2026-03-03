import unittest
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

from google_drive_sync import (
    DriveAccessReport,
    DriveCsvFile,
    extract_drive_folder_id,
    sync_drive_folder_csvs,
    upload_file_to_drive,
)


class GoogleDriveSyncTests(unittest.TestCase):
    class _ProgressStatus:
        def __init__(self, progress_value: float):
            self._progress_value = progress_value

        def progress(self) -> float:
            return self._progress_value

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

    def test_upload_file_to_drive_creates_new_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "catalog.csv"
            source_path.write_text("Наименование;Артикул\nКабель;A-1\n", encoding="utf-8")

            files_resource = Mock()
            service = Mock()
            service.files.return_value = files_resource
            files_resource.list.return_value.execute.return_value = {"files": []}

            request = Mock()
            request.next_chunk.side_effect = [
                (self._ProgressStatus(0.5), None),
                (
                    self._ProgressStatus(1.0),
                    {
                        "id": "file-1",
                        "name": "export.csv",
                        "size": str(source_path.stat().st_size),
                        "webViewLink": "https://drive.google.com/file/d/file-1/view",
                    },
                ),
            ]
            files_resource.create.return_value = request

            with (
                patch("google_drive_sync._build_drive_service", return_value=service),
                patch("google_drive_sync.MediaFileUpload", return_value=object()),
            ):
                result = upload_file_to_drive(
                    source_path=source_path,
                    folder_url_or_id="1T5pU2JsABjJbCHNM4WMSgzbvc9E4iUaM",
                    service_account_info={},
                    target_name="export.csv",
                )

            files_resource.create.assert_called_once()
            files_resource.update.assert_not_called()
            self.assertEqual(result.file_id, "file-1")
            self.assertEqual(result.name, "export.csv")
            self.assertEqual(result.folder_id, "1T5pU2JsABjJbCHNM4WMSgzbvc9E4iUaM")
            self.assertIn("file-1", result.web_view_link)
            self.assertIn("file-1", result.web_content_link or "")

    def test_upload_file_to_drive_updates_existing_file_with_same_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "catalog.csv"
            source_path.write_text("Наименование;Артикул\nКабель;A-1\n", encoding="utf-8")

            files_resource = Mock()
            service = Mock()
            service.files.return_value = files_resource
            files_resource.list.return_value.execute.return_value = {"files": [{"id": "existing-1"}]}

            request = Mock()
            request.next_chunk.side_effect = [
                (
                    self._ProgressStatus(1.0),
                    {
                        "id": "existing-1",
                        "name": "export.csv",
                        "size": str(source_path.stat().st_size),
                        "webViewLink": "https://drive.google.com/file/d/existing-1/view",
                        "webContentLink": "https://drive.google.com/uc?id=existing-1&export=download",
                    },
                )
            ]
            files_resource.update.return_value = request

            with (
                patch("google_drive_sync._build_drive_service", return_value=service),
                patch("google_drive_sync.MediaFileUpload", return_value=object()),
            ):
                result = upload_file_to_drive(
                    source_path=source_path,
                    folder_url_or_id="1T5pU2JsABjJbCHNM4WMSgzbvc9E4iUaM",
                    service_account_info={},
                    target_name="export.csv",
                )

            files_resource.update.assert_called_once()
            files_resource.create.assert_not_called()
            self.assertEqual(result.file_id, "existing-1")
            self.assertEqual(result.name, "export.csv")


if __name__ == "__main__":
    unittest.main()
