from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from config import get_price_converted_csv_path, get_price_raw_csv_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert source price CSV to UTF-8")
    parser.add_argument("--input", default=str(get_price_raw_csv_path()), help="Path to source price.csv")
    parser.add_argument("--output", default=str(get_price_converted_csv_path()), help="Path to converted CSV")
    return parser.parse_args()


def convert_csv(input_path: str | Path, output_path: str | Path) -> Path:
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    last_error: Exception | None = None
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            df = pd.read_csv(
                input_path,
                sep=";",
                encoding=enc,
                decimal=".",
                low_memory=False,
            )
            break
        except UnicodeDecodeError as e:
            last_error = e
    else:
        raise ValueError(
            "Failed to read CSV with supported encodings: cp1251, utf-8-sig, utf-8. "
            f"Last error: {last_error}"
        )

    # Если есть пустой технический последний столбец — удаляем.
    if len(df.columns) > 0 and (str(df.columns[-1]).startswith("Unnamed") or str(df.columns[-1]) == ""):
        df = df.iloc[:, :-1]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, sep=";", encoding="utf-8", index=False)

    print(df.shape)
    preview = df.head(3).to_string()
    safe_preview = preview.encode(sys.stdout.encoding or "utf-8", errors="backslashreplace").decode(
        sys.stdout.encoding or "utf-8", errors="ignore"
    )
    print(safe_preview)
    print(f"\nFile saved: {output_path}")
    return output_path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    convert_csv(args.input, args.output)


if __name__ == "__main__":
    main()
