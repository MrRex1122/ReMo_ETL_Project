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

    def fake_stat(self, *args, **kwargs):
        result = original_stat(self, *args, **kwargs)
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


def test_process_raw_catalogs_with_etl_prunes_orphan_processed_files(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    raw_dir = storage / "raw"
    converted_dir = storage / "converted"
    clean_dir = storage / "clean"
    raw_dir.mkdir(parents=True)
    converted_dir.mkdir(parents=True)
    clean_dir.mkdir(parents=True)

    (raw_dir / "a.csv").write_text("x", encoding="utf-8")
    (converted_dir / "a_converted.csv").write_text("old-current", encoding="utf-8")
    (converted_dir / "stale_converted.csv").write_text("stale", encoding="utf-8")
    (clean_dir / "a_clean.csv").write_text("old-current", encoding="utf-8")
    (clean_dir / "stale_clean.csv").write_text("stale", encoding="utf-8")

    monkeypatch.setattr(app, "get_upload_dir", lambda: storage)

    def fake_convert_csv(src, dst):
        Path(dst).write_text("converted", encoding="utf-8")
        return Path(dst)

    monkeypatch.setattr(app, "convert_csv", fake_convert_csv)

    class FakePriceETL:
        def __init__(self, inp, out):
            self.out = Path(out)

        def run(self):
            self.out.write_text("clean", encoding="utf-8")
            return self

    monkeypatch.setattr(app, "PriceETL", FakePriceETL)

    result = app.process_raw_catalogs_with_etl()

    assert [p.name for p in result] == ["a_clean.csv"]
    assert (converted_dir / "a_converted.csv").exists()
    assert not (converted_dir / "stale_converted.csv").exists()
    assert (clean_dir / "a_clean.csv").exists()
    assert not (clean_dir / "stale_clean.csv").exists()


def test_process_raw_catalogs_with_etl_removes_stale_converted_for_chunked_file(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    raw_dir = storage / "raw"
    converted_dir = storage / "converted"
    raw_dir.mkdir(parents=True)
    converted_dir.mkdir(parents=True)
    big = raw_dir / "big.csv"
    big.write_bytes(b"0" * 1024)
    stale_converted = converted_dir / "big_converted.csv"
    stale_converted.write_text("stale", encoding="utf-8")

    monkeypatch.setattr(app, "get_upload_dir", lambda: storage)
    monkeypatch.setenv("REMO_CHUNKED_ETL_THRESHOLD_MB", "1")
    monkeypatch.setenv("REMO_CHUNKED_ETL_CHUNKSIZE", "123")

    class FakePriceETL:
        def __init__(self, inp, out):
            self.out = Path(out)

        def run_chunked(self, *, chunksize):
            self.out.parent.mkdir(parents=True, exist_ok=True)
            self.out.write_text("clean", encoding="utf-8")
            return self

    monkeypatch.setattr(app, "PriceETL", FakePriceETL)

    original_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        result = original_stat(self, *args, **kwargs)
        if self.name == "big.csv":
            class StatProxy:
                st_size = 2 * 1024 * 1024
            return StatProxy()
        return result

    monkeypatch.setattr(Path, "stat", fake_stat)

    app.process_raw_catalogs_with_etl()

    assert not stale_converted.exists()


def test_process_raw_catalogs_with_etl_rebuilds_merged_once_after_pruning(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    raw_dir = storage / "raw"
    converted_dir = storage / "converted"
    clean_dir = storage / "clean"
    raw_dir.mkdir(parents=True)
    converted_dir.mkdir(parents=True)
    clean_dir.mkdir(parents=True)

    (raw_dir / "a.csv").write_text("x", encoding="utf-8")
    (converted_dir / "stale_converted.csv").write_text("stale", encoding="utf-8")
    (clean_dir / "stale_clean.csv").write_text("stale", encoding="utf-8")

    monkeypatch.setattr(app, "get_upload_dir", lambda: storage)

    def fake_convert_csv(src, dst):
        Path(dst).write_text("converted", encoding="utf-8")
        return Path(dst)

    monkeypatch.setattr(app, "convert_csv", fake_convert_csv)

    class FakePriceETL:
        def __init__(self, inp, out):
            self.out = Path(out)

        def run(self):
            self.out.write_text("clean", encoding="utf-8")
            return self

    monkeypatch.setattr(app, "PriceETL", FakePriceETL)

    rebuild_calls = []

    def fake_refresh(clean_path):
        clean_path = Path(clean_path)
        rebuild_calls.append(
            {
                "clean_dir": clean_path,
                "clean_files": sorted(path.name for path in clean_path.glob("*_clean.csv")),
            }
        )
        merged_path = clean_path / "price_clean_merged.csv"
        merged_path.write_text("merged", encoding="utf-8")
        return merged_path

    monkeypatch.setattr(app, "refresh_merged_catalog", fake_refresh)

    result = app.process_raw_catalogs_with_etl()

    assert [p.name for p in result] == ["a_clean.csv"]
    assert rebuild_calls == [
        {
            "clean_dir": clean_dir,
            "clean_files": ["a_clean.csv"],
        }
    ]


def test_sync_catalogs_from_google_drive_rebuilds_merged_once_after_batch_etl(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    raw_dir = storage / "raw"
    raw_dir.mkdir(parents=True)

    downloaded = [
        raw_dir / "a.csv",
        raw_dir / "b.csv",
    ]
    for path in downloaded:
        path.write_text("raw", encoding="utf-8")

    monkeypatch.setattr(app, "get_upload_dir", lambda: storage)
    monkeypatch.setattr(app, "sync_drive_folder_csvs", lambda **kwargs: downloaded)

    convert_calls = []

    def fake_convert_csv(src, dst):
        convert_calls.append((Path(src).name, Path(dst).name))
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

    rebuild_calls = []

    def fake_refresh(clean_path):
        clean_path = Path(clean_path)
        rebuild_calls.append(
            {
                "clean_dir": clean_path,
                "clean_files": sorted(path.name for path in clean_path.glob("*_clean.csv")),
            }
        )
        merged_path = clean_path / "price_clean_merged.csv"
        merged_path.write_text("merged", encoding="utf-8")
        return merged_path

    monkeypatch.setattr(app, "refresh_merged_catalog", fake_refresh)

    result = app.sync_catalogs_from_google_drive(
        folder_url_or_id="folder-id",
        service_account_json='{"client_email": "demo@example.com"}',
        run_etl=True,
    )

    assert [p.name for p in result] == ["a_clean.csv", "b_clean.csv"]
    assert convert_calls == [
        ("a.csv", "a_converted.csv"),
        ("b.csv", "b_converted.csv"),
    ]
    assert etl_calls == [
        ("a_converted.csv", "a_clean.csv"),
        ("b_converted.csv", "b_clean.csv"),
    ]
    assert rebuild_calls == [
        {
            "clean_dir": storage / "clean",
            "clean_files": ["a_clean.csv", "b_clean.csv"],
        }
    ]
