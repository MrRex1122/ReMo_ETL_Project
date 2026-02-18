import tempfile
import unittest
from pathlib import Path

from batch_process import iter_excel_files


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


if __name__ == "__main__":
    unittest.main()
