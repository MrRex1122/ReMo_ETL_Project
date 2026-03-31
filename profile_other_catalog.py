from __future__ import annotations

import argparse
import csv
import json
import random
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping

import pandas as pd

from catalog_schema import canonicalize_catalog_columns
from catalog_search import (
    SEARCH_BASE_COLUMNS,
    SEARCH_DERIVED_COLUMNS,
    build_search_projection_row,
    clean_text_value,
    iter_search_catalog_chunks,
    load_search_taxonomy_rules,
)
from taxonomy_registry import entity_family_for_type

NAME_COL = "ÐÐ°Ð¸Ð¼ÐµÐ½Ð¾Ð²Ð°Ð½Ð¸Ðµ"
ARTICLE_COL = "ÐÑ€Ñ‚Ð¸ÐºÑƒÐ»"
CLASS_COL = "ÐÐ°Ð·Ð²Ð°Ð½Ð¸Ðµ ÐºÐ»Ð°ÑÑÐ°"
ITEM_TYPE_COL = "Ð¢Ð¸Ð¿ Ð¸Ð·Ð´ÐµÐ»Ð¸Ñ"
MANUFACTURER_COL = "ÐŸÑ€Ð¾Ð¸Ð·Ð²Ð¾Ð´Ð¸Ñ‚ÐµÐ»ÑŒ"

PROJECTED_PROFILE_COLUMNS = {
    NAME_COL,
    ARTICLE_COL,
    CLASS_COL,
    ITEM_TYPE_COL,
    MANUFACTURER_COL,
    "search_branch_path",
    "search_tokens_json",
    "search_entity_type",
    "search_effective_family",
    "search_effective_entity_type",
    "search_item_markers_json",
}


def _emit(message: str, *, verbose: bool) -> None:
    if verbose:
        print(message, flush=True)


def _iter_catalog_rows(source_path: Path, *, chunksize: int) -> Iterator[Dict[str, Any]]:
    if source_path.suffix.lower() == ".duckdb":
        chunk_iter = iter_search_catalog_chunks(source_path, chunksize=chunksize)
    else:
        header_frame = pd.read_csv(source_path, sep=";", encoding="utf-8", nrows=0)
        raw_columns = {str(column) for column in header_frame.columns}
        if PROJECTED_PROFILE_COLUMNS.issubset(raw_columns):
            selected_columns = PROJECTED_PROFILE_COLUMNS
        else:
            selected_columns = set(SEARCH_BASE_COLUMNS)
        chunk_iter = pd.read_csv(
            source_path,
            sep=";",
            encoding="utf-8",
            chunksize=chunksize,
            low_memory=False,
            usecols=lambda column_name: str(column_name) in selected_columns,
        )
    for chunk in chunk_iter:
        chunk = canonicalize_catalog_columns(chunk, create_missing=True)
        for row in chunk.to_dict(orient="records"):
            yield row


def _has_full_projection(row: Mapping[str, Any]) -> bool:
    required = {
        "search_branch_path",
        "search_normalized_name",
        "search_tokens_json",
        "search_entity_type",
        "search_effective_family",
        "search_effective_entity_type",
        "search_item_markers_json",
    }
    return required.issubset({str(key) for key in row.keys()})


def _project_row(row: Mapping[str, Any], taxonomy_rules: Mapping[str, Any]) -> Dict[str, Any]:
    if _has_full_projection(row):
        projected = {column: row.get(column, "") for column in SEARCH_BASE_COLUMNS + SEARCH_DERIVED_COLUMNS}
    else:
        projected = build_search_projection_row(row, taxonomy_rules=taxonomy_rules)
    effective_entity_type = clean_text_value(projected.get("search_effective_entity_type")) or clean_text_value(
        projected.get("search_entity_type")
    )
    effective_family = clean_text_value(projected.get("search_effective_family")) or entity_family_for_type(
        effective_entity_type,
        taxonomy_rules,
    )
    projected["search_effective_entity_type"] = effective_entity_type
    projected["search_effective_family"] = effective_family
    return projected


def _parse_tokens(raw_value: Any) -> List[str]:
    cleaned = clean_text_value(raw_value)
    if not cleaned:
        return []
    try:
        loaded = json.loads(cleaned)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, list):
        return []
    return [clean_text_value(token) for token in loaded if clean_text_value(token)]


def _reservoir_push(sample: List[Dict[str, Any]], row: Dict[str, Any], seen_count: int, sample_size: int, rng: random.Random) -> None:
    if sample_size <= 0:
        return
    if len(sample) < sample_size:
        sample.append(row)
        return
    replace_at = rng.randint(1, seen_count)
    if replace_at <= sample_size:
        sample[replace_at - 1] = row


def _write_counter_csv(path: Path, header: List[str], rows: Iterable[Iterable[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(header)
        for row in rows:
            writer.writerow(list(row))


def _format_counter(counter: Counter[str], *, limit: int = 3) -> str:
    parts: List[str] = []
    for key, count in counter.most_common(limit):
        parts.append(f"{key or '<empty>'} ({count})")
    return " | ".join(parts)


def _format_examples(examples: List[str], *, limit: int = 3) -> str:
    return " | ".join(example for example in examples[:limit] if example)


def _branch_alignment_status(*, total_rows: int, other_rows: int) -> str:
    if total_rows <= 0:
        return "empty"
    if other_rows <= 0:
        return "mapped"
    other_share = other_rows / total_rows
    if other_share >= 0.999:
        return "all_other"
    if other_share >= 0.8:
        return "mostly_other"
    return "mixed"


def analyze_other_catalog(
    source_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    sample_size: int = 100,
    seed: int = 42,
    chunksize: int = 50000,
    progress_every: int = 50000,
    verbose: bool = True,
) -> Path:
    source = Path(source_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = Path(output_dir) if output_dir else Path("batch_output") / "other_profiling" / timestamp
    target_dir.mkdir(parents=True, exist_ok=True)

    start_ts = time.perf_counter()
    _emit(
        f"[other-profiler] start source={source} output={target_dir} sample_size={sample_size} chunksize={chunksize} seed={seed}",
        verbose=verbose,
    )

    taxonomy_rules = load_search_taxonomy_rules()
    rng = random.Random(seed)

    total_rows = 0
    other_rows = 0
    sample_rows: List[Dict[str, Any]] = []
    branch_counter: Counter[str] = Counter()
    class_counter: Counter[tuple[str, str, str]] = Counter()
    item_type_counter: Counter[str] = Counter()
    manufacturer_counter: Counter[str] = Counter()
    token_counter: Counter[str] = Counter()
    branch_total_counter: Counter[str] = Counter()
    branch_other_counter: Counter[str] = Counter()
    branch_family_counter: Dict[str, Counter[str]] = defaultdict(Counter)
    branch_other_class_counter: Dict[str, Counter[str]] = defaultdict(Counter)
    branch_examples: Dict[str, List[str]] = defaultdict(list)

    for raw_row in _iter_catalog_rows(source, chunksize=chunksize):
        total_rows += 1
        projected = _project_row(raw_row, taxonomy_rules)
        effective_family = clean_text_value(projected.get("search_effective_family")).lower()

        name = clean_text_value(projected.get(NAME_COL))
        article = clean_text_value(projected.get(ARTICLE_COL))
        class_name = clean_text_value(projected.get(CLASS_COL))
        item_type = clean_text_value(projected.get(ITEM_TYPE_COL))
        manufacturer = clean_text_value(projected.get(MANUFACTURER_COL))
        branch_path = clean_text_value(projected.get("search_branch_path"))
        branch_key = branch_path or ""

        branch_total_counter[branch_key] += 1
        branch_family_counter[branch_key][effective_family or ""] += 1
        if name and name not in branch_examples[branch_key] and len(branch_examples[branch_key]) < 5:
            branch_examples[branch_key].append(name)

        if effective_family == "other":
            other_rows += 1
            effective_entity_type = clean_text_value(projected.get("search_effective_entity_type"))
            markers_json = clean_text_value(projected.get("search_item_markers_json"))

            branch_other_counter[branch_key] += 1
            branch_other_class_counter[branch_key][class_name or ""] += 1
            branch_counter[branch_key] += 1
            class_counter[(class_name or "", branch_key, item_type or "")] += 1
            item_type_counter[item_type or ""] += 1
            manufacturer_counter[manufacturer or ""] += 1
            token_counter.update(token for token in _parse_tokens(projected.get("search_tokens_json")) if len(token) >= 3)

            _reservoir_push(
                sample_rows,
                {
                    NAME_COL: name,
                    ARTICLE_COL: article,
                    CLASS_COL: class_name,
                    ITEM_TYPE_COL: item_type,
                    MANUFACTURER_COL: manufacturer,
                    "search_branch_path": branch_path,
                    "search_entity_type": clean_text_value(projected.get("search_entity_type")),
                    "search_effective_family": effective_family,
                    "search_effective_entity_type": effective_entity_type,
                    "search_item_markers_json": markers_json,
                    "manual_family": "",
                    "manual_subfamily": "",
                    "notes": "",
                },
                other_rows,
                sample_size,
                rng,
            )

        if progress_every > 0 and total_rows % progress_every == 0:
            elapsed = max(time.perf_counter() - start_ts, 0.001)
            rows_per_second = round(total_rows / elapsed, 1)
            _emit(
                f"[other-profiler] progress rows={total_rows} other_rows={other_rows} sample={len(sample_rows)} rate={rows_per_second} rows/s",
                verbose=verbose,
            )

    sample_frame = pd.DataFrame(sample_rows)
    if not sample_frame.empty:
        sample_frame.sort_values(
            by=[CLASS_COL, "search_branch_path", NAME_COL, ARTICLE_COL],
            inplace=True,
            na_position="last",
        )
    sample_frame.to_csv(target_dir / "other_sample_random.csv", sep=";", encoding="utf-8", index=False)

    _write_counter_csv(
        target_dir / "other_branch_summary.csv",
        ["search_branch_path", "count"],
        ((branch, count) for branch, count in branch_counter.most_common()),
    )
    _write_counter_csv(
        target_dir / "other_class_summary.csv",
        [CLASS_COL, "search_branch_path", ITEM_TYPE_COL, "count"],
        ((*key, count) for key, count in class_counter.most_common()),
    )
    _write_counter_csv(
        target_dir / "other_item_type_summary.csv",
        [ITEM_TYPE_COL, "count"],
        ((item_type, count) for item_type, count in item_type_counter.most_common()),
    )
    _write_counter_csv(
        target_dir / "other_manufacturer_summary.csv",
        [MANUFACTURER_COL, "count"],
        ((manufacturer, count) for manufacturer, count in manufacturer_counter.most_common()),
    )
    _write_counter_csv(
        target_dir / "other_token_summary.csv",
        ["token", "count"],
        ((token, count) for token, count in token_counter.most_common(300)),
    )

    branch_alignment_rows: List[List[Any]] = []
    for branch_path, total_count in branch_total_counter.most_common():
        other_count = branch_other_counter.get(branch_path, 0)
        other_share = round((other_count / total_count) * 100, 2) if total_count else 0.0
        family_counter = branch_family_counter.get(branch_path, Counter())
        non_other_families = Counter(
            {family: count for family, count in family_counter.items() if family and family != "other"}
        )
        branch_alignment_rows.append(
            [
                branch_path,
                total_count,
                other_count,
                other_share,
                _branch_alignment_status(total_rows=total_count, other_rows=other_count),
                _format_counter(family_counter, limit=5),
                _format_counter(non_other_families, limit=5),
                _format_counter(branch_other_class_counter.get(branch_path, Counter()), limit=5),
                _format_examples(branch_examples.get(branch_path, []), limit=3),
            ]
        )

    alignment_header = [
        "search_branch_path",
        "total_rows",
        "other_rows",
        "other_share",
        "status",
        "top_families",
        "top_non_other_families",
        "top_other_classes",
        "example_names",
    ]
    _write_counter_csv(target_dir / "branch_family_alignment.csv", alignment_header, branch_alignment_rows)
    _write_counter_csv(
        target_dir / "other_branch_alignment.csv",
        alignment_header,
        (row for row in branch_alignment_rows if int(row[2]) > 0),
    )

    summary_lines = [
        f"source={source}",
        f"output_dir={target_dir}",
        f"total_rows={total_rows}",
        f"other_rows={other_rows}",
        f"other_share={round((other_rows / total_rows) * 100, 2) if total_rows else 0.0}",
        f"sample_size={len(sample_rows)}",
        f"seed={seed}",
    ]
    (target_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    elapsed = max(time.perf_counter() - start_ts, 0.001)
    rows_per_second = round(total_rows / elapsed, 1)
    other_share = round((other_rows / total_rows) * 100, 2) if total_rows else 0.0
    _emit(
        f"[other-profiler] done rows={total_rows} other_rows={other_rows} other_share={other_share}% elapsed_s={round(elapsed, 1)} rate={rows_per_second} rows/s",
        verbose=verbose,
    )
    _emit(
        "[other-profiler] files: other_sample_random.csv, other_branch_summary.csv, other_class_summary.csv, "
        "other_item_type_summary.csv, other_manufacturer_summary.csv, other_token_summary.csv, "
        "branch_family_alignment.csv, other_branch_alignment.csv, summary.txt",
        verbose=verbose,
    )
    return target_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile rows that still land in the 'other' family.")
    parser.add_argument("--input", required=True, help="Path to merged/search catalog CSV or DuckDB")
    parser.add_argument("--sample-size", type=int, default=100, help="Reservoir sample size for other rows")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible sampling")
    parser.add_argument("--chunksize", type=int, default=50000, help="Chunk size for reading large catalogs")
    parser.add_argument("--progress-every", type=int, default=50000, help="Print progress every N processed rows")
    parser.add_argument("--output-dir", default="", help="Optional output directory")
    parser.add_argument("--quiet", action="store_true", help="Disable progress logs and print only the output path")
    args = parser.parse_args()

    output_dir = analyze_other_catalog(
        args.input,
        output_dir=args.output_dir or None,
        sample_size=max(1, int(args.sample_size)),
        seed=int(args.seed),
        chunksize=max(1000, int(args.chunksize)),
        progress_every=max(1000, int(args.progress_every)),
        verbose=not bool(args.quiet),
    )
    print(output_dir)


if __name__ == "__main__":
    main()
