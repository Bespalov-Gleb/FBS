# Тесты FBS Backend

## Запуск

```bash
cd backend
poetry install
poetry run pytest tests/ -v
```

Или с покрытием:

```bash
poetry run pytest tests/ -v --cov=app --cov-report=term-missing --cov-report=html
```

## Окружение

Тесты используют SQLite in-memory. Переменные `TESTING=1`, `SECRET_KEY` и др. задаются в `conftest.py` до импорта app.

## Структура

- `conftest.py` — фикстуры (client, db_session, packer_user, admin_user, headers)
- `test_health.py` — health check endpoints
- `test_auth.py` — регистрация, вход, refresh, /me
- `test_orders.py` — список заказов
- `test_marketplaces.py` — CRUD маркетплейсов
- `test_users.py` — пользователи (admin)
- `test_warehouses.py` — склады
- `test_print_settings.py` — настройки печати
- `test_security.py` — хеширование паролей, JWT токены
