import unittest

from google_drive_sync import extract_drive_folder_id


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


if __name__ == "__main__":
    unittest.main()
