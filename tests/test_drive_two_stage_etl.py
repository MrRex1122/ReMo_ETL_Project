from pathlib import Path

import app


def test_process_raw_catalogs_with_etl_processes_each_raw_file(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    raw_dir = storage / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "a.csv").write_text("x", encoding="utf-8")
    (raw_dir / "b.csv").write_text("y", encoding="utf-8")

    monkeypatch.setattr(app, "get_upload_dir", lambda: storage)

    converted_calls = []

    def fake_convert_csv(src, dst):
        converted_calls.append((Path(src).name, Path(dst).name))
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_text("converted", encoding="utf-8")
        return Path(dst)

    monkeypatch.setattr(app, "convert_csv", fake_convert_csv)

    etl_calls = []

    class FakePriceETL:
        def __init__(self, inp, out):
            etl_calls.append((Path(inp).name, Path(out).name))
            self.out = Path(out)

        def run(self):
            self.out.parent.mkdir(parents=True, exist_ok=True)
            self.out.write_text("clean", encoding="utf-8")
            return self

    monkeypatch.setattr(app, "PriceETL", FakePriceETL)

    result = app.process_raw_catalogs_with_etl()

    assert [p.name for p in result] == ["a_clean.csv", "b_clean.csv"]
    assert converted_calls == [
        ("a.csv", "a_converted.csv"),
        ("b.csv", "b_converted.csv"),
    ]
    assert etl_calls == [
        ("a_converted.csv", "a_clean.csv"),
        ("b_converted.csv", "b_clean.csv"),
    ]


def test_process_raw_catalogs_with_etl_returns_empty_when_no_raw(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    (storage / "raw").mkdir(parents=True)
    monkeypatch.setattr(app, "get_upload_dir", lambda: storage)
    assert app.process_raw_catalogs_with_etl() == []
