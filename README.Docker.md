# Запуск FBS в Docker

Один контейнер для всего: frontend, backend, PostgreSQL, Redis.

## Быстрый старт

```bash
# Из корня проекта FBS
docker compose up -d

# Или с выводом логов
docker compose up
```

После запуска:
- **Frontend:** http://localhost:5173
- **Backend API:** http://localhost:8000
- **API Docs:** http://localhost:8000/api/docs

## Остановка

```bash
docker compose down
```

## Первый запуск

Зарегистрируйтесь через форму на странице входа (http://localhost:5173) или войдите, если уже есть аккаунт.

## Пересборка

После изменений в коде:

```bash
docker compose up -d --build
```

Frontend с hot-reload — изменения подхватываются без пересборки.
