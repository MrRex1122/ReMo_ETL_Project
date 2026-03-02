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


def test_process_raw_catalogs_with_etl_uses_chunked_for_large_files(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    raw_dir = storage / "raw"
    raw_dir.mkdir(parents=True)
    big = raw_dir / "big.csv"
    big.write_bytes(b"0" * 1024)  # small real file, size will be faked

    monkeypatch.setattr(app, "get_upload_dir", lambda: storage)
    monkeypatch.setenv("REMO_CHUNKED_ETL_THRESHOLD_MB", "1")
    monkeypatch.setenv("REMO_CHUNKED_ETL_CHUNKSIZE", "123")

    convert_called = {"value": False}

    def fake_convert_csv(src, dst):
        convert_called["value"] = True
        return Path(dst)

    monkeypatch.setattr(app, "convert_csv", fake_convert_csv)

    calls = []

    class FakePriceETL:
        def __init__(self, inp, out):
            self.inp = Path(inp)
            self.out = Path(out)

        def run(self):
            calls.append(("run", self.inp.name, self.out.name))
            return self

        def run_chunked(self, *, chunksize):
            calls.append(("run_chunked", self.inp.name, self.out.name, chunksize))
            self.out.parent.mkdir(parents=True, exist_ok=True)
            self.out.write_text("clean", encoding="utf-8")
            return self

    monkeypatch.setattr(app, "PriceETL", FakePriceETL)

    # Force large size reading without writing huge files.
    original_stat = Path.stat

    def fake_stat(self):
        result = original_stat(self)
        if self.name == "big.csv":
            class StatProxy:
                st_size = 2 * 1024 * 1024
            return StatProxy()
        return result

    monkeypatch.setattr(Path, "stat", fake_stat)

    result = app.process_raw_catalogs_with_etl()

    assert [p.name for p in result] == ["big_clean.csv"]
    assert convert_called["value"] is False
    assert calls == [("run_chunked", "big.csv", "big_clean.csv", 123)]
