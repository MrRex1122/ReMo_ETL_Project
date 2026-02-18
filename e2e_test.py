import os
import tomllib
import json
import time
import argparse
from pathlib import Path
from matcher import ReMoMatcher
from config import get_catalog_csv_path, get_sample_excel_path, get_upload_dir

# Найти GEMINI_API_KEY: сначала переменные окружения, иначе .streamlit/secrets.toml
def load_api_key():
    key = os.getenv('GEMINI_API_KEY')
    if key:
        return key
    secrets_path = os.path.join(os.path.dirname(__file__), '.streamlit', 'secrets.toml')
    if os.path.exists(secrets_path):
        with open(secrets_path, 'rb') as f:
            data = tomllib.load(f)
            return data.get('GEMINI_API_KEY')
    return None


def main():
    parser = argparse.ArgumentParser(description="Run end-to-end matcher test")
    parser.add_argument("--db-csv", default=None, help="Path to price_clean.csv")
    parser.add_argument("--sample-xlsx", default=None, help="Path to input Excel file")
    args = parser.parse_args()

    api_key = load_api_key()
    if not api_key:
        raise SystemExit('GEMINI_API_KEY not found in environment or .streamlit/secrets.toml')

    db_csv = str(get_catalog_csv_path(args.db_csv))
    if not Path(db_csv).exists():
        raise SystemExit(f'price_clean.csv not found at {db_csv}. Run ETL first.')

    sample_xlsx = get_sample_excel_path(args.sample_xlsx)
    if not sample_xlsx.exists():
        # pick any .xlsx in upload folder
        folder = get_upload_dir()
        if not folder.exists():
            raise SystemExit(f'Upload folder not found: {folder}')
        files = [f for f in os.listdir(folder) if f.lower().endswith('.xlsx')]
        if not files:
            raise SystemExit('No xlsx file found in upload folder to run E2E')
        sample_xlsx = folder / files[0]

    print('Using sample file:', str(sample_xlsx))

    matcher = ReMoMatcher(api_key, db_csv)

    start = time.time()
    df_out, stats = matcher.process_excel(str(sample_xlsx))
    duration = time.time() - start

    report = {
        'sample_file': str(sample_xlsx),
        'rows_processed': stats.get('total', 0),
        'found': stats.get('found', 0),
        'not_found': stats.get('not_found', 0),
        'from_cache': stats.get('from_cache', 0),
        'errors': stats.get('errors', 0),
        'success_rate_percent': (stats.get('found',0)/stats.get('total',1))*100 if stats.get('total',0)>0 else 0,
        'duration_seconds': duration
    }

    out_path = sample_xlsx.parent / 'e2e_report.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print('\nE2E report saved to:', str(out_path))
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
