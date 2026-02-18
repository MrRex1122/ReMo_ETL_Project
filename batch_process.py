"""
Batch processing for ReMo prototype.
Processes all Excel files in a folder and produces consolidated report.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import pandas as pd

from matcher import ReMoMatcher, MISSING_POSITION_TEXT
from config import get_catalog_csv_path

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_api_key(explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()

    env = os.getenv("GEMINI_API_KEY")
    if env and env.strip():
        return env.strip()

    secrets = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if secrets.exists():
        try:
            import tomllib

            data = tomllib.loads(secrets.read_text(encoding="utf-8"))
            key = data.get("GEMINI_API_KEY")
            if key and str(key).strip():
                return str(key).strip()
        except Exception:
            pass

    raise SystemExit("GEMINI_API_KEY not found. Set env or .streamlit/secrets.toml or --api-key")


def iter_excel_files(folder: Path) -> List[Path]:
    files = sorted(
        [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in {".xlsx", ".xls"}],
        key=lambda p: p.name.lower(),
    )
    return [
        f for f in files
        if not f.name.startswith("~$") and "_matched" not in f.stem.lower()
    ]


def process_one(matcher: ReMoMatcher, src: Path, out_dir: Path) -> Dict:
    out_file = out_dir / f"{src.stem}_matched{src.suffix}"
    _df, stats = matcher.process_excel(str(src), str(out_file))

    # Use matcher stats to avoid brittle dependency on localized/encoded column names.
    missing_rows = int(stats.get("not_found", 0))

    return {
        "file": src.name,
        "output": out_file.name,
        "total": int(stats.get("total", 0)),
        "found": int(stats.get("found", 0)),
        "not_found": int(stats.get("not_found", 0)),
        "missing_position_rows": missing_rows,
        "from_cache": int(stats.get("from_cache", 0)),
        "errors": int(stats.get("errors", 0)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ReMo batch processor")
    parser.add_argument("--input-dir", required=True, help="Folder with input Excel files")
    parser.add_argument("--output-dir", default="batch_output", help="Folder for processed files")
    parser.add_argument(
        "--db-csv",
        default=str(get_catalog_csv_path()),
        help="Path to catalog csv (or set REMO_DB_CSV)",
    )
    parser.add_argument("--api-key", default=None, help="Gemini API key (optional)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_dir.exists():
        raise SystemExit(f"Input dir not found: {input_dir}")
    if not input_dir.is_dir():
        raise SystemExit(f"Input path is not a directory: {input_dir}")

    files = iter_excel_files(input_dir)
    if not files:
        raise SystemExit(f"No Excel files found in {input_dir}")

    api_key = load_api_key(args.api_key)
    catalog_path = get_catalog_csv_path(args.db_csv)
    if not catalog_path.exists():
        raise SystemExit(f"Catalog CSV not found: {catalog_path}")

    matcher = ReMoMatcher(api_key, str(catalog_path))

    report: List[Dict] = []
    for file_path in files:
        try:
            report.append(process_one(matcher, file_path, output_dir))
        except Exception as e:
            report.append(
                {
                    "file": file_path.name,
                    "output": None,
                    "total": 0,
                    "found": 0,
                    "not_found": 0,
                    "missing_position_rows": 0,
                    "from_cache": 0,
                    "errors": 1,
                    "error_message": str(e),
                }
            )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"batch_report_{ts}.json"
    csv_path = output_dir / f"batch_report_{ts}.csv"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(report).to_csv(csv_path, index=False, encoding="utf-8-sig")

    total_files = len(report)
    total_rows = sum(r.get("total", 0) for r in report)
    total_missing = sum(r.get("missing_position_rows", 0) for r in report)

    print(f"Processed files: {total_files}")
    print(f"Rows processed: {total_rows}")
    print(f"Rows with '{MISSING_POSITION_TEXT}': {total_missing}")
    print(f"Report JSON: {json_path}")
    print(f"Report CSV:  {csv_path}")


if __name__ == "__main__":
    main()
