# ReMo Matcher

Система для сопоставления строк из коммерческих предложений с товарным каталогом поставщика.

Проект уже давно не сводится к "поискать похожий текст через LLM". Сейчас это production-oriented пайплайн с:
- merged catalog как сырьем;
- отдельной поисковой БД для matcher;
- локальной taxonomy и branch/family routing;
- DuckDB-backed retrieval;
- Gemini как слоем выбора внутри уже отобранного candidate set;
- Debug / Admin инструментами для анализа taxonomy без полного rebuild на каждой итерации.

## Что умеет система

### Основной matcher
- Заполняет КП по каталогу поставщика.
- Сопоставляет по article/designation/name-first путям и по branch-aware semantic path.
- Использует локальные hard gates по family, kind, размерам и совместимости.
- Применяет Gemini не как глобальный поиск по всему каталогу, а как подтверждающий слой внутри shortlist.
- Сохраняет результат прогона и технические артефакты для последующего разбора.

### Каталоги
- `price_clean_merged.csv` — merged catalog, источник правды после ETL/merge.
- `price_clean_search.duckdb` — compact search DB для matcher.
- В search DB сохраняются:
  - `search_branch_path`
  - `search_effective_family`
  - `search_effective_entity_type`
  - search markers и нормализованные поля для retrieval.

### Taxonomy и branch routing
- Taxonomy живет в rule-layer, а не только в UI.
- При rebuild search DB автоматически сохраняются snapshot-артефакты:
  - `taxonomy_tree.json`
  - `taxonomy_branch_family_summary.csv`
- В Debug / Admin можно отдельно строить:
  - `taxonomy preview` без rebuild search DB;
  - `branch probe` по выбранным веткам;
  - `Gemini draft` по текущему branch probe.

## Текущий рабочий цикл

### 1. Сборка каталогов
- Сырые прайсы объединяются в merged CSV.
- Из merged CSV собирается search DB кнопкой `🪶 Обновить поисковую БД`.
- При rebuild автоматически обновляются taxonomy snapshot-артефакты.

### 2. Основной КП-run
- На главной вкладке запускается заполнение КП.
- Main flow отдает бизнес-результат без лишних debug-колонок.
- Полная таблица и технические артефакты остаются во вкладке `🧪 Debug / Admin`.
- Section rows вроде `ОБОРУДОВАНИЕ` и пустые разделители не считаются ненайденными товарными позициями.

### 3. Taxonomy-итерации без полного rebuild
Во вкладке `🧪 Debug / Admin` доступны три уровня:

1. `🧭 Структура taxonomy`
- Показывает текущее дерево и branch-family summary из search DB.

2. `⚡ Taxonomy preview без rebuild`
- Dry-run по merged CSV.
- Полезен для крупного пересмотра taxonomy.
- Может быть тяжелым на больших каталогах.

3. `⚡ Branch probe по выбранным веткам`
- Быстрый пересчет только по выбранным проблемным веткам.
- Это основной инструмент для быстрых taxonomy-итераций.

4. `🧠 Gemini draft для taxonomy`
- Строит draft-рекомендации только по текущему branch probe.
- Ничего автоматически не применяет.
- Используется как taxonomist-assistant, а не как источник правды.

## Артефакты taxonomy

### Snapshot после rebuild
- `taxonomy_tree.json`
- `taxonomy_branch_family_summary.csv`

### Preview без rebuild
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

## Как читать taxonomy workflow

### Snapshot
Используйте, когда нужно понять:
- как сейчас реально размечена search DB;
- сколько family уже материализовано в каталоге;
- какие крупные ветки остаются смешанными.

### Preview
Используйте, когда:
- меняли taxonomy rules;
- хотите посмотреть общий эффект без полного rebuild search DB.

### Branch probe
Используйте, когда:
- уже нашли 1-3 проблемные ветки;
- хотите быстро проверить гипотезу;
- не хотите гонять preview по всему merged catalog.

### Gemini draft
Используйте, когда:
- branch probe уже построен;
- нужна подсказка по `suggested_family`, `suggested_subfamily` или `split_branch`;
- вы хотите получить draft, а не сразу менять боевые правила.

Важно:
- draft не применяется автоматически;
- для широких mixed branches backend теперь принудительно склоняет результат к `split_branch`, чтобы Gemini не натягивал одну family на всю ветку.

## Архитектура

```text
Excel КП
  -> ReMoMatcher
     -> query parsing
     -> branch / family routing
     -> DuckDB retrieval
     -> local scoring + compatibility filter
     -> Gemini shortlist decision
     -> KP result + debug artifacts

Catalog pipeline
  raw price files
    -> merge / clean
    -> price_clean_merged.csv
    -> search build
    -> price_clean_search.duckdb
    -> taxonomy snapshots
```

Основные модули:
- `app.py` — Streamlit UI, main KP flow, Debug / Admin, rebuild actions.
- `matcher.py` — основной matcher и decision policy.
- `catalog_merge.py` — merge/clean каталогов.
- `catalog_search.py` — build search DB, taxonomy snapshots, preview, branch probe, Gemini draft.
- `taxonomy_registry.py` — family/subfamily registry и default branch mapping.
- `processing_runs.py` — persisted runs и run storage.

## Быстрый старт

### Установка
```bash
pip install -r requirements.txt
```

### Gemini API key
Через `.streamlit/secrets.toml`:

```toml
GEMINI_API_KEY = "your_key"
```

или через env:

```powershell
$env:GEMINI_API_KEY = "your_key"
```

### Запуск
```bash
streamlit run app.py
```

## Основные переменные окружения

### Пути
- `REMO_UPLOAD_DIR` — базовая папка данных.
- `REMO_DB_CSV` — merged CSV или папка с `*_clean.csv`.
- `REMO_MATCHER_CACHE_DB` — путь к `matcher_cache.db`.
- `RAILWAY_VOLUME_MOUNT_PATH` — volume mount на Railway.

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

## Что сейчас важно operationally

### Main KP flow
- На главной вкладке показывается trimmed KP-результат.
- Полная техническая таблица доступна только в `Debug / Admin`.
- Runtime diagnostics и тяжелые taxonomy-инструменты не должны тормозить основной пользовательский сценарий больше, чем это необходимо.

### Heavy operations
- Полный rebuild search DB — тяжелая операция.
- Preview по всему merged catalog — тоже тяжелая операция.
- Для быстрых итераций по taxonomy предпочтителен `branch probe`.

### Правильный порядок taxonomy-итераций
1. Найти шумную ветку через snapshot/preview.
2. Прогнать `branch probe` по нужным веткам.
3. Построить `Gemini draft`.
4. Перенести хорошие идеи в реальные rules.
5. Только после этого делать полноценный rebuild search DB.

## Ограничения

- Большое число `requires_review` не всегда значит баг: иногда это честное следствие mixed branches или широкой taxonomy.
- Нельзя автоматически доверять Gemini draft для широких веток.
- Search DB и taxonomy snapshots должны рассматриваться как source of truth для текущего build-состояния, а не старые выгруженные файлы из прошлых rebuild.

## Тесты

Базовый набор:

```bash
python -m unittest tests.test_catalog_search -q
python -m unittest tests.test_benchmark_matcher -q
python -m unittest tests.test_app_ui_regressions -q
```

Точечные taxonomy/regression тесты добавляются рядом с изменениями в:
- `tests/test_catalog_search.py`
- `tests/test_match_taxonomy.py`
- `tests/test_app_ui_regressions.py`

## Railway / production notes

Рекомендуемая схема:
- приложение на Railway;
- данные на Railway Volume;
- merged catalog и search DB живут на volume;
- крупные артефакты можно выгружать в Cloudflare R2.

Практически это обычно выглядит так:
- `REMO_UPLOAD_DIR=/data/remo`
- `price_clean_merged.csv` живет в volume
- `price_clean_search.duckdb` живет там же и переживает деплой

## Поддержка README

README описывает текущее рабочее состояние проекта.

Если меняется:
- matcher policy,
- taxonomy workflow,
- search storage,
- Debug / Admin процесс,

README нужно обновлять вместе с кодом. Для этого проекта это часть рабочего контракта, а не опциональная документация.
