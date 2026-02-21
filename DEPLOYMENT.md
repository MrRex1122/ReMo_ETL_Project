# CI/CD деплой через GitHub Actions

Этот проект теперь поддерживает сценарий:

1. Push/PR в `main` запускает тесты (`pytest -q`).
2. При `push` в `main` и успешных тестах автоматически запускается деплой на ваш сервер по SSH.
3. На сервере собирается Docker-образ и перезапускается контейнер Streamlit.

## Что добавлено

- `Dockerfile` — контейнеризация Streamlit-приложения.
- `.dockerignore` — исключение лишних файлов из контекста сборки.
- `.github/workflows/ci_cd.yml` — pipeline test -> deploy.

## Требования к серверу

На целевом сервере должны быть установлены:

- Docker
- SSH-доступ для пользователя деплоя
- Открыт порт `8501` (или проксирование через Nginx)

## Настройка GitHub Secrets

В репозитории GitHub откройте:
`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`

Создайте секреты:

- `DEPLOY_HOST` — IP/домен сервера
- `DEPLOY_USER` — SSH-пользователь
- `DEPLOY_SSH_KEY` — приватный SSH-ключ (ed25519), которым action входит на сервер
- `DEPLOY_PATH` — путь проекта на сервере, например `/opt/remo-etl`
- `GEMINI_API_KEY` — ключ Gemini для runtime контейнера

## Первый запуск

1. Подготовьте сервер:

```bash
sudo mkdir -p /opt/remo-etl
sudo chown -R <deploy_user>:<deploy_user> /opt/remo-etl
```

2. Добавьте публичный SSH-ключ в `~/.ssh/authorized_keys` пользователя `<deploy_user>`.
3. Запушьте изменения в `main`.
4. Вкладка `Actions` покажет выполнение pipeline.

## Как это работает

- Job `test`:
  - checkout
  - install dependencies
  - `pytest -q`

- Job `deploy` (только `push`):
  - проверяет наличие секретов
  - синхронизирует код на сервер через `rsync`
  - выполняет на сервере:
    - `docker build -t remo-matcher:latest .`
    - перезапуск контейнера `remo-matcher`

## Проверка после деплоя

Откройте:

- `http://<DEPLOY_HOST>:8501`

Если используете reverse proxy, проверяйте ваш домен.
