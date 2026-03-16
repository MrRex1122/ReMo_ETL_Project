# ReMo Matcher

Система для сопоставления позиций из коммерческих предложений с товарным каталогом поставщика.

Проект уже ушел далеко от исходной идеи “поискать похожий текст через LLM”. Сейчас это пайплайн с:
- подготовкой входной БД и поисковой БД;
- локальной таксономией и маркерами совместимости;
- DuckDB-backed retrieval;
- Gemini как слоем выбора внутри релевантного candidate set;
- persisted run-артефактами, аудитом покрытия каталога и диагностикой причин ненахода.

## Что есть сейчас

### Матчинг
- Сопоставление Excel КП с каталогом поставщика.
- Локальная классификация query/item по семействам: `patch_panel`, `patch_cord`, `keystone`, `rj45_connector`, `rj45_outlet`, `bulk_twisted_pair`, `iec_power_cable`, `optical_cross`, `optical_patch_cord`, `ats_sts`, `airflow_blanking_panel` и др.
- Strict / semi-strict / generic логика совместимости.
- Gemini используется не как “поиск по всему каталогу”, а как слой уточнения внутри локально отобранных кандидатов.
- Кэш результатов сопоставления в SQLite.

### Каталоги
- Сырой источник истины: merged CSV, например `price_clean_merged.csv`.
- Компактная поисковая БД: `price_clean_search.duckdb`.
- Search catalog строится из merged catalog кнопкой `🪶 Обновить поисковую БД`.
- В DuckDB хранятся нормализованные поля и search-признаки; это значительно меньше и быстрее, чем широкий CSV.

### Retrieval
- Основной режим: `DuckDB whole-category retrieval by derived branch`.
- Matcher больше не обязан preload’ить весь каталог в память для search-пути.
- Whole-category retrieval применяется к typed family по derived branch / family routing.
- Старые слайдеры shortlist/chunk/local recall сохранены, но убраны в `Advanced`, потому что в DuckDB-режиме они уже не являются главным retrieval-механизмом.

### Run-артефакты
Для каждого прогона сохраняются:
- `result.csv`
- `result.xlsx`
- `stats.json`
- `progress.json`
- `coverage_audit.json`
- `match_diagnostics.json`

### Диагностика
- В UI есть `Аудит покрытия каталога`.
- В UI есть `Диагностика причин ненахода`.
- Диагностика разделяет:
  - `pipeline_stage` — где строка остановилась;
  - `root_cause_class/root_cause_code` — почему не нашли.
- Для historical run возможна reconstructed diagnostics.
- Экспорт диагностики и аудита доступен одним `.xlsx` workbook.

### Экспорт каталогов
- Выгрузка входной БД в Cloudflare R2.
- Выгрузка поисковой БД в Cloudflare R2.
- Локальные/Google Drive кнопки экспорта каталогов из UI убраны; для каталогов оставлен Cloudflare-only поток.

### UI и UX
- Фоновая обработка run с persisted progress.
- Автообновление статуса активного прогона — opt-in.
- Есть ручной пересчет аудита и диагностики.
- Есть отдельный блок состояния поисковой БД.

## Архитектура

```text
Excel КП
  -> ReMoMatcher
     -> query classification
     -> derived branch / family routing
     -> DuckDB whole-category retrieval
     -> local scoring + compatibility filter
     -> Gemini shortlist confirmation
     -> result / diagnostics / audit

Catalog pipeline
  merged CSV
    -> search build
    -> price_clean_search.duckdb
```

Основные модули:
- `app.py` — Streamlit UI, background run orchestration, экспорт, аудит, диагностика.
- `matcher.py` — основной matcher.
- `catalog_merge.py` — сборка merged catalog.
- `catalog_search.py` — сборка search catalog в CSV/DuckDB.
- `catalog_coverage_audit.py` — аудит покрытия каталога для выбранного run.
- `match_diagnostics.py` — runtime/reconstructed диагностика причин ненахода.
- `processing_runs.py` — persisted run storage.
- `cloudflare_r2_export.py` — выгрузка больших артефактов в Cloudflare R2.

## Быстрый старт

### 1. Установка

```bash
pip install -r requirements.txt
```

### 2. Gemini API key

Вариант через `.streamlit/secrets.toml`:

```toml
GEMINI_API_KEY = "your_key"
```

Или через env:

```powershell
$env:GEMINI_API_KEY = "your_key"
```

### 3. Запуск

```bash
streamlit run app.py
```

## Основные настройки

Ключевые переменные окружения:

### Пути и данные
- `REMO_UPLOAD_DIR` — базовая папка данных.
- `REMO_DB_CSV` — путь к активному merged catalog CSV или папке с `*_clean.csv`.
- `REMO_MATCHER_CACHE_DB` — путь к `matcher_cache.db`.
- `RAILWAY_VOLUME_MOUNT_PATH` — volume mount на Railway; если `REMO_UPLOAD_DIR` не задан, проект использует его автоматически.

### Gemini / matcher
- `REMO_MATCHER_MODELS`
- `REMO_MATCHER_PARALLEL_REQUESTS`
- `REMO_MATCHER_CONTEXT_CHUNK_SIZE`
- `REMO_MATCHER_MAX_CONTEXT_CHUNKS`
- `REMO_MATCHER_RETRIEVAL_CANDIDATES`
- `REMO_MATCHER_GEMINI_SHORTLIST_LIMIT`
- `REMO_MATCHER_GEMINI_CHUNK_SIZE`
- `REMO_MATCHER_GEMINI_MAX_CHUNKS`
- `REMO_MATCHER_LOCAL_RECALL_POOL`
- `REMO_MATCHER_SKIP_WEAK_SHORTLIST`
- `REMO_MATCHER_LOCAL_CONFIDENCE_THRESHOLD`
- `REMO_MATCHER_LOCAL_MARGIN_THRESHOLD`

### Cloudflare R2
- `CLOUDFLARE_R2_ACCOUNT_ID`
- `CLOUDFLARE_R2_BUCKET`
- `CLOUDFLARE_R2_ACCESS_KEY_ID`
- `CLOUDFLARE_R2_SECRET_ACCESS_KEY`
- `CLOUDFLARE_R2_PUBLIC_BASE_URL` — опционально, если нужен публичный URL.

## Как работать с каталогами

### Входная БД
- В проект можно указать либо конкретный merged CSV, либо папку с `*_clean.csv`.
- Если указана папка, merged catalog будет пересобран из источников.

### Поисковая БД
- Нажмите `🪶 Обновить поисковую БД`.
- Если все готово, активной поисковой БД становится `price_clean_search.duckdb`.
- Если search DuckDB недоступен или устарел, matcher умеет безопасно откатиться на legacy path.

Почему это важно:
- merged CSV может быть очень широким и тяжелым;
- search DuckDB существенно компактнее;
- это уменьшает cold start и ускоряет retrieval.

## Как выглядит текущий production-пайплайн

### На вкладке загрузки
1. Загружаете Excel КП.
2. Запускаете обработку.
3. Следите за persisted progress.
4. После завершения переходите к run в результатах.

### На вкладке результатов
Доступны:
- итоговая таблица;
- статистика прогона;
- аудит покрытия каталога;
- диагностика причин ненахода;
- экспорт диагностики workbook;
- экспорт аудита workbook.

## Аудит и диагностика

### Аудит покрытия каталога
Отвечает на вопрос:
- есть ли в каталоге нужное семейство;
- есть ли семейство, но не хватает specs;
- или в каталоге реально были compatible candidates.

Типовые диагнозы:
- `catalog_missing_family`
- `catalog_has_family_but_no_compatible_specs`
- `catalog_has_compatible_candidates`
- `non_target_family`

Для `catalog gap` дополнительно считаются техпричины:
- `missing_family`
- `category_mismatch`
- `connector_mismatch`
- `component_kind_mismatch`
- `installation_kind_mismatch`
- `port_count_mismatch`
- `shielding_mismatch`
- `fiber_mode_mismatch`
- `environment_mismatch`
- `multiple_spec_mismatches`

### Диагностика причин ненахода
Отвечает на два разных вопроса:

1. Где остановилась строка?
- `query_input`
- `query_classification`
- `local_recall`
- `compatibility_filter`
- `gemini_selection`
- `fallback_policy`
- `resolved`

2. Почему не нашли?
- `catalog_gap`
- `matcher_retrieval_or_ranking`
- `gemini_or_decision_policy`
- `not_audited_family`
- `input_or_query_shape`
- `runtime_error`

Это позволяет не путать “где сломалось” и “почему в итоге не нашли”.

## Railway

Рекомендуемая схема деплоя:
- приложение на Railway;
- данные на Railway Volume;
- merged catalog и search DuckDB лежат на volume;
- экспорты крупных артефактов идут в Cloudflare R2.

Практически это выглядит так:
- `REMO_UPLOAD_DIR=/data/remo`
- merged catalog живет в volume;
- search catalog `price_clean_search.duckdb` тоже живет в volume и переживает деплой.

Это снимает необходимость гонять полную ETL/merge/search сборку после каждого релиза.

## Актуальные важные изменения по сравнению со старой версией

- Search catalog переведен на DuckDB.
- Matcher переведен на whole-category retrieval по derived branch.
- Убрана зависимость от full preload всего search-каталога в память для DuckDB-path.
- Введены persisted processing runs.
- Добавлены progress bar и persisted progress state.
- Добавлены `coverage_audit.json` и `match_diagnostics.json`.
- Диагностика теперь двухосевая: `pipeline stage` и `root cause`.
- Экспорты диагностики и аудита стали workbook-based.
- Экспорт catalog/search catalog в UI оставлен через Cloudflare R2.

## Ограничения текущего состояния

Важно понимать текущее поведение системы:
- если каталог реально не содержит нужного семейства/specs, matcher не “дотягивает” мусор до совпадения;
- большое число `unresolved` может быть честным следствием покрытия каталога, а не только багом retrieval;
- для некоторых доменов качество определяется не только matcher-логикой, но и наполнением входной БД.

## Тесты

Проект покрыт набором unit/regression тестов по:
- taxonomy/classification,
- catalog search build,
- matcher modes и candidate routing,
- coverage audit,
- match diagnostics,
- UI regressions.

Пример запуска:

```bash
python -m unittest tests.test_match_diagnostics tests.test_catalog_coverage_audit -q
python -m unittest tests.test_match_taxonomy tests.test_match_candidates tests.test_process_excel -q
```

## Troubleshooting

### Поисковая БД не готова
- Сначала соберите merged catalog.
- Затем нажмите `🪶 Обновить поисковую БД`.

### `result.csv` и workbook diagnostics расходятся
На новых прогонах они должны быть синхронизированы автоматически.
Если это historical run, пересчитайте аудит и диагностику вручную из UI.

### Прогресс кажется “застывшим”
- Проверьте, включено ли автообновление статуса.
- На повторных прогонах matcher теперь приоритизирует cache-hit и более легкие задачи, поэтому счетчик должен двигаться заметно раньше.

### Cloudflare R2 export не работает
Проверьте:
- `CLOUDFLARE_R2_ACCOUNT_ID`
- `CLOUDFLARE_R2_BUCKET`
- `CLOUDFLARE_R2_ACCESS_KEY_ID`
- `CLOUDFLARE_R2_SECRET_ACCESS_KEY`

## Лицензия / заметка по эксплуатации

README описывает текущее рабочее состояние проекта, а не “идеальную архитектуру в вакууме”.
Если вы меняете matcher policy, taxonomy или search storage, обновляйте README одновременно с кодом: в этом проекте это реально важно, потому что UI, run-артефакты и operational flow тесно связаны.
