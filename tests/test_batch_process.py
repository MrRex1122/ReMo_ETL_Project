import os
import tempfile
import unittest
from pathlib import Path

from batch_process import iter_excel_files, load_api_key


class BatchProcessTests(unittest.TestCase):
    def test_iter_excel_files_handles_uppercase_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "A.XLSX").write_text("x")
            (tmp / "b.xls").write_text("x")
            (tmp / "~$temp.xlsx").write_text("x")
            (tmp / "file_matched.xlsx").write_text("x")
            (tmp / "notes.txt").write_text("x")

            files = iter_excel_files(tmp)

            self.assertEqual([f.name for f in files], ["A.XLSX", "b.xls"])

    def test_load_api_key_strips_whitespace(self):
        previous = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "  env-key  "
        try:
            self.assertEqual(load_api_key("  cli-key  "), "cli-key")
            self.assertEqual(load_api_key(None), "env-key")
        finally:
            if previous is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = previous


if __name__ == "__main__":
    unittest.main()
