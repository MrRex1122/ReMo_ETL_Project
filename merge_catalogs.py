from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from catalog_schema import canonicalize_catalog_columns


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge multiple supplier catalogs into one CSV by unique key"
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="Path to source CSV. Repeat the flag for each file.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to merged output CSV",
    )
    parser.add_argument(
        "--key",
        default="Код ЭТМ",
        help="Unique key column for deduplication (default: Код ЭТМ)",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Input/output encoding (default: utf-8)",
    )
    return parser.parse_args()


def _read_catalog(path: Path, encoding: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Input CSV not found: {path}")

    df = pd.read_csv(path, sep=";", encoding=encoding, low_memory=False)
    df = canonicalize_catalog_columns(df, create_missing=True)
    df["_source_file"] = path.name
    return df


def _normalize_key(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.replace("\ufeff", "", regex=False)
    )


def _merge_group(group: pd.DataFrame) -> pd.Series:
    # Start with the most complete row, then fill gaps from other rows.
    completeness = group.notna().sum(axis=1)
    base = group.loc[completeness.idxmax()].copy()

    for _, row in group.iterrows():
        missing_mask = base.isna() | (base.astype(str).str.strip().eq(""))
        base[missing_mask] = row[missing_mask]

    return base


def merge_catalogs(input_paths: list[Path], key_col: str, encoding: str) -> pd.DataFrame:
    frames = [_read_catalog(path, encoding=encoding) for path in input_paths]
    merged = pd.concat(frames, ignore_index=True, sort=False)

    if key_col not in merged.columns:
        raise ValueError(
            f"Key column '{key_col}' is missing in merged data. "
            f"Available columns: {list(merged.columns)}"
        )

    merged[key_col] = _normalize_key(merged[key_col])
    merged = merged[merged[key_col].notna() & merged[key_col].ne("") & merged[key_col].ne("nan")]

    grouped = merged.groupby(key_col, sort=False, dropna=False)
    merged_rows = [_merge_group(group) for _, group in grouped]
    deduped = pd.DataFrame(merged_rows).reset_index(drop=True)

    preferred_order = [key_col, "Наименование", "Артикул", "Цена розничная", "_source_file"]
    ordered_cols = [col for col in preferred_order if col in deduped.columns]
    ordered_cols.extend([col for col in deduped.columns if col not in ordered_cols])
    deduped = deduped[ordered_cols]

    return deduped


def main() -> None:
    args = parse_args()
    input_paths = [Path(path) for path in args.input]
    output_path = Path(args.output)

    merged = merge_catalogs(input_paths, key_col=args.key, encoding=args.encoding)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_path, sep=";", encoding=args.encoding, index=False)

    print(f"Saved: {output_path}")
    print(f"Rows: {len(merged)}")
    print(f"Columns: {len(merged.columns)}")


if __name__ == "__main__":
    main()
