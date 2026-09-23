# ReMo Matcher

A production-oriented system for matching line items from commercial proposals against a supplier product catalogue.

The project is no longer a simple "find similar text with an LLM" workflow. It is a structured matching pipeline built around:
- a merged catalogue as the raw source of truth;
- a dedicated search database for the matcher;
- local taxonomy and branch/family routing;
- DuckDB-backed retrieval;
- Gemini as a decision layer inside an already constrained candidate set;
- Debug / Admin tools for analysing and iterating on taxonomy without rebuilding the entire search database every time.

## What the system does

### Core matcher
- Fills commercial proposals using the supplier catalogue.
- Matches through article/designation/name-first paths and a branch-aware semantic path.
- Applies local hard gates for family, kind, dimensions, and compatibility.
- Uses Gemini not as a global search engine over the whole catalogue, but as a confirmation/selection layer inside a shortlist.
- Persists run results and technical artifacts for later inspection and debugging.

### Catalogues
- `price_clean_merged.csv` — merged catalogue and source of truth after ETL/merge.
- `price_clean_search.duckdb` — compact search database used by the matcher.
- The search database stores:
  - `search_branch_path`
  - `search_effective_family`
  - `search_effective_entity_type`
  - search markers and normalised fields used for retrieval.

### Taxonomy and branch routing
- Taxonomy lives in the rule layer, not only in the UI.
- Rebuilding the search database automatically writes taxonomy snapshot artifacts:
  - `taxonomy_tree.json`
  - `taxonomy_branch_family_summary.csv`
- Debug / Admin can also generate:
  - a taxonomy preview without rebuilding the search database;
  - a branch probe for selected branches;
  - a Gemini draft based on the current branch probe.

## Current workflow

### 1. Build the catalogue
- Raw supplier price files are merged into the consolidated CSV.
- The merged CSV is converted into the search database with the `🪶 Обновить поисковую БД` action.
- A rebuild also refreshes taxonomy snapshot artifacts automatically.

### 2. Run proposal matching
- Proposal matching is started from the main application tab.
- The main flow returns a trimmed business-facing result without unnecessary debug columns.
- The full table and technical artifacts remain available under `🧪 Debug / Admin`.
- Section rows such as `ОБОРУДОВАНИЕ` and empty separators are not counted as unmatched product lines.

### 3. Iterate on taxonomy without a full rebuild
The `🧪 Debug / Admin` area provides several levels of analysis:

1. `🧭 Структура taxonomy`
- Shows the current taxonomy tree and branch-family summary from the search database.

2. `⚡ Taxonomy preview без rebuild`
- Runs a dry preview against the merged CSV.
- Useful for broad taxonomy revisions.
- Can be expensive on large catalogues.

3. `⚡ Branch probe по выбранным веткам`
- Recalculates only selected problematic branches.
- This is the main tool for fast taxonomy iteration.

4. `🧠 Gemini draft для taxonomy`
- Produces draft recommendations only for the current branch probe.
- Does not apply changes automatically.
- Acts as a taxonomist assistant rather than a source of truth.

## Taxonomy artifacts

### Snapshot after rebuild
- `taxonomy_tree.json`
- `taxonomy_branch_family_summary.csv`

### Preview without rebuild
- `taxonomy_preview_tree.json`
- `taxonomy_preview_branch_family_summary.csv`
- `taxonomy_preview_branch_cleanup_audit.csv`

### Branch probe
- `taxonomy_probe_tree.json`
- `taxonomy_probe_branch_family_summary.csv`
- `taxonomy_probe_branch_cleanup_audit.csv`

### Gemini draft
- `taxonomy_bootstrap_draft.json`
- `taxonomy_bootstrap_draft.csv`

## How to use the taxonomy workflow

### Snapshot
Use it when you need to understand:
- how the current search database is actually classified;
- how many families have already been materialised in the catalogue;
- which large branches are still mixed.

### Preview
Use it when:
- taxonomy rules have changed;
- you want to inspect the broader effect before rebuilding the search database.

### Branch probe
Use it when:
- 1–3 problematic branches have already been identified;
- you want to validate a hypothesis quickly;
- you do not want to run a full-catalogue preview.

### Gemini draft
Use it when:
- a branch probe has already been generated;
- you want suggestions for `suggested_family`, `suggested_subfamily`, or `split_branch`;
- you want a draft rather than an automatic production rule change.

Important:
- drafts are never applied automatically;
- for broad mixed branches, the backend biases the result toward `split_branch` so Gemini does not force one family across an entire heterogeneous branch.

## Architecture

```text
Excel proposal
  -> ReMoMatcher
     -> query parsing
     -> branch / family routing
     -> DuckDB retrieval
     -> local scoring + compatibility filter
     -> Gemini shortlist decision
     -> proposal result + debug artifacts

Catalogue pipeline
  raw price files
    -> merge / clean
    -> price_clean_merged.csv
    -> search build
    -> price_clean_search.duckdb
    -> taxonomy snapshots
```

Main modules:
- `app.py` — Streamlit UI, main proposal flow, Debug / Admin, and rebuild actions.
- `matcher.py` — core matcher and decision policy.
- `catalog_merge.py` — catalogue merge/clean pipeline.
- `catalog_search.py` — search DB build, taxonomy snapshots, preview, branch probe, and Gemini draft.
- `taxonomy_registry.py` — family/subfamily registry and default branch mapping.
- `processing_runs.py` — persisted runs and run storage.

## Quick start

### Install
```bash
pip install -r requirements.txt
```

### Gemini API key
Using `.streamlit/secrets.toml`:

```toml
GEMINI_API_KEY = "your_key"
```

or an environment variable:

```powershell
$env:GEMINI_API_KEY = "your_key"
```

### Run
```bash
streamlit run app.py
```

## Main environment variables

### Paths
- `REMO_UPLOAD_DIR` — base data directory.
- `REMO_DB_CSV` — merged CSV path or a directory containing `*_clean.csv` files.
- `REMO_MATCHER_CACHE_DB` — path to `matcher_cache.db`.
- `RAILWAY_VOLUME_MOUNT_PATH` — Railway volume mount path.

### Matcher / Gemini
- `REMO_MATCHER_MODELS`
- `REMO_MATCHER_PARALLEL_REQUESTS`
- `REMO_MATCHER_RETRIEVAL_CANDIDATES`
- `REMO_MATCHER_GEMINI_SHORTLIST_LIMIT`
- `REMO_MATCHER_LOCAL_RECALL_POOL`
- `REMO_MATCHER_LOCAL_CONFIDENCE_THRESHOLD`
- `REMO_MATCHER_LOCAL_MARGIN_THRESHOLD`

### Storage / export
- `CLOUDFLARE_R2_ACCOUNT_ID`
- `CLOUDFLARE_R2_BUCKET`
- `CLOUDFLARE_R2_ACCESS_KEY_ID`
- `CLOUDFLARE_R2_SECRET_ACCESS_KEY`
- `CLOUDFLARE_R2_PUBLIC_BASE_URL`

## Operational notes

### Main proposal flow
- The main tab displays the trimmed proposal result.
- The full technical table is available only in `Debug / Admin`.
- Runtime diagnostics and expensive taxonomy tools should not slow the main user flow more than necessary.

### Heavy operations
- Rebuilding the full search database is expensive.
- Running a preview across the entire merged catalogue is also expensive.
- For fast taxonomy iteration, prefer a targeted branch probe.

### Recommended taxonomy iteration order
1. Find a noisy branch using a snapshot or preview.
2. Run a branch probe for the relevant branches.
3. Generate a Gemini draft.
4. Move useful ideas into the real rule set.
5. Only then rebuild the full search database.

## Limitations

- A high number of `requires_review` rows does not always indicate a bug; it can be an honest consequence of mixed branches or a broad taxonomy.
- Gemini drafts should not be trusted automatically for broad branches.
- The search database and taxonomy snapshots are the source of truth for the current build state, not old exported files from previous rebuilds.

## Tests

Basic test suite:

```bash
python -m unittest tests.test_catalog_search -q
python -m unittest tests.test_benchmark_matcher -q
python -m unittest tests.test_app_ui_regressions -q
```

Targeted taxonomy/regression tests are added alongside changes in:
- `tests/test_catalog_search.py`
- `tests/test_match_taxonomy.py`
- `tests/test_app_ui_regressions.py`

## Railway / production notes

Recommended deployment model:
- application on Railway;
- data on a Railway Volume;
- merged catalogue and search database persisted on the volume;
- large artifacts optionally exported to Cloudflare R2.

Typical layout:
- `REMO_UPLOAD_DIR=/data/remo`
- `price_clean_merged.csv` stored on the volume
- `price_clean_search.duckdb` stored on the same volume and preserved across deploys

## README maintenance

This README describes the current working state of the project.

When any of the following changes:
- matcher policy,
- taxonomy workflow,
- search storage,
- Debug / Admin process,

the README should be updated together with the code. For this project, documentation is part of the working contract rather than optional cleanup.
