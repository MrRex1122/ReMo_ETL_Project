import os
import tomllib
import json
import time
from matcher import ReMoMatcher

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
    api_key = load_api_key()
    if not api_key:
        raise SystemExit('GEMINI_API_KEY not found in environment or .streamlit/secrets.toml')

    db_csv = r"D:\Data\Downloads\upload\price_clean.csv"
    if not os.path.exists(db_csv):
        raise SystemExit(f'price_clean.csv not found at {db_csv}. Run ETL first.')

    # Пример входного файла (в папке upload)
    sample_xlsx = r"D:\Data\Downloads\upload\РеМо_Шаблон_коммерческого_предложения_020625.xlsx"
    if not os.path.exists(sample_xlsx):
        # pick any .xlsx in folder
        folder = os.path.dirname(sample_xlsx)
        files = [f for f in os.listdir(folder) if f.lower().endswith('.xlsx')]
        if not files:
            raise SystemExit('No xlsx file found in upload folder to run E2E')
        sample_xlsx = os.path.join(folder, files[0])

    print('Using sample file:', sample_xlsx)

    matcher = ReMoMatcher(api_key, db_csv)

    start = time.time()
    df_out, stats = matcher.process_excel(sample_xlsx)
    duration = time.time() - start

    report = {
        'sample_file': sample_xlsx,
        'rows_processed': stats.get('total', 0),
        'found': stats.get('found', 0),
        'not_found': stats.get('not_found', 0),
        'from_cache': stats.get('from_cache', 0),
        'errors': stats.get('errors', 0),
        'success_rate_percent': (stats.get('found',0)/stats.get('total',1))*100 if stats.get('total',0)>0 else 0,
        'duration_seconds': duration
    }

    out_path = os.path.join(os.path.dirname(sample_xlsx), 'e2e_report.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print('\nE2E report saved to:', out_path)
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
