# Инструкция по деплою FBS

Руководство по настройке сервера и запуску приложения FBS (управление FBS-заказами маркетплейсов).

---

## 1. Требования к серверу

- **ОС:** Ubuntu 22.04 LTS (или Debian 12)
- **RAM:** минимум 2 GB (рекомендуется 4 GB)
- **Диск:** 20 GB
- **Порты:** 80, 443 (HTTP/HTTPS), 8000 (опционально, для прямого доступа к API)

---

## 2. Подготовка сервера

### 2.1 Обновление системы

```bash
sudo apt update && sudo apt upgrade -y
```

### 2.2 Установка Docker и Docker Compose

```bash
# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Выйти и зайти снова, чтобы группа применилась

# Docker Compose (плагин)
sudo apt install docker-compose-plugin -y

# Проверка
docker --version
docker compose version
```

### 2.3 Установка Git

```bash
sudo apt install git -y
```

---

## 3. Развёртывание приложения

### 3.1 Клонирование репозитория

```bash
cd /opt  # или другая директория
sudo git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ> fbs
cd fbs
```

### 3.2 Создание файла переменных окружения

Создайте файл `.env` в **корне проекта** (рядом с `docker-compose.yml`). Docker Compose автоматически подставит переменные из `.env`:

```bash
cp backend/.env.example .env
nano .env
```

**Обязательно измените следующие переменные:**

| Переменная | Описание | Пример |
|------------|----------|--------|
| `SECRET_KEY` | Секретный ключ для JWT (минимум 32 символа) | `openssl rand -hex 32` |
| `ENCRYPTION_KEY` | Ключ шифрования API ключей маркетплейсов | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL | Сильный пароль |
| `FIRST_SUPERUSER_EMAIL` | Email первого администратора | `admin@yourdomain.com` |
| `FIRST_SUPERUSER_PASSWORD` | Пароль администратора | Сильный пароль |

**Пример `.env` для production:**

```env
# Application
DEBUG=False
ENVIRONMENT=production

# Security (ОБЯЗАТЕЛЬНО СГЕНЕРИРОВАТЬ!)
SECRET_KEY=ваш-секретный-ключ-минимум-32-символа
ENCRYPTION_KEY=ваш-fernet-ключ-из-cryptography

# Database (POSTGRES_SERVER=postgres — имя сервиса в Docker)
POSTGRES_SERVER=postgres
POSTGRES_PORT=5432
POSTGRES_USER=fbs_user
POSTGRES_PASSWORD=сильный_пароль_для_бд
POSTGRES_DB=fbs_db
DATABASE_URL=postgresql://fbs_user:сильный_пароль_для_бд@postgres:5432/fbs_db

# Redis
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# CORS — укажите ваш домен
BACKEND_CORS_ORIGINS=["https://yourdomain.com","https://www.yourdomain.com"]

# Frontend (для сборки production)
VITE_API_URL=https://yourdomain.com/api/v1

# First superuser
FIRST_SUPERUSER_EMAIL=admin@yourdomain.com
FIRST_SUPERUSER_PASSWORD=ваш_пароль_админа
FIRST_SUPERUSER_FULLNAME=Administrator
```

---

## 4. Запуск (вариант A: простой)

Подходит для внутренних сетей или тестового окружения.

### 4.1 Запуск в production-режиме

Используйте `docker-compose.prod.yml` — он переключает backend в production и собирает frontend как статику:

```bash
# Добавьте в .env:
# VITE_API_URL=https://yourdomain.com/api/v1

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
# или docker-compose (v1):
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

**При таймаутах pypi.org** (ReadTimeoutError) добавьте в `.env`:
```env
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
```
Или выполните сборку с зеркалом:
```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple docker-compose -f docker-compose.yml -f docker-compose.prod.yml build --no-cache
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 4.2 Запуск в dev-режиме

```bash
# Только backend, postgres, redis
docker compose up -d

# С frontend (Vite dev-сервер)
docker compose --profile full up -d
```

**Доступ (production):**
- Frontend: http://IP_СЕРВЕРА:8080
- Backend API: http://IP_СЕРВЕРА:8000
- API docs: http://IP_СЕРВЕРА:8000/docs

**Доступ (dev):**
- Frontend: http://IP_СЕРВЕРА:5173
- Backend: http://IP_СЕРВЕРА:8000

---

## 5. Запуск (вариант B: production с Nginx)

Для production с HTTPS и раздачей статики frontend.

### 5.1 Сборка frontend

```bash
cd frontend
npm ci
VITE_API_URL=https://yourdomain.com/api/v1 npm run build
```

Собранные файлы появятся в `frontend/dist/`.

### 5.2 Настройка Nginx

Скопируйте `backend/docker/nginx.conf` и добавьте раздачу статики frontend:

```nginx
# В блок server, после location /api/
location / {
    root /usr/share/nginx/html;
    index index.html;
    try_files $uri $uri/ /index.html;
}
```

### 5.3 Docker Compose для production

Используйте `backend/docker/docker-compose.yml` как основу. Добавьте сервис для frontend или монтируйте `frontend/dist` в nginx.

---

## 6. SSL-сертификаты (HTTPS)

### Вариант 1: Let's Encrypt (Certbot)

```bash
sudo apt install certbot -y
sudo certbot certonly --standalone -d yourdomain.com
# Сертификаты: /etc/letsencrypt/live/yourdomain.com/
```

Скопируйте в `backend/docker/ssl/`:
```bash
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem backend/docker/ssl/cert.pem
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem backend/docker/ssl/key.pem
```

### Вариант 2: Самоподписанный (для тестов)

```bash
mkdir -p backend/docker/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout backend/docker/ssl/key.pem \
  -out backend/docker/ssl/cert.pem \
  -subj "/CN=localhost"
```

---

## 7. Миграции базы данных

Миграции применяются автоматически при старте backend (команда в `docker-compose`).

**Ручной запуск:**
```bash
docker compose exec backend alembic upgrade head
```

**Проверка текущей версии:**
```bash
docker compose exec backend alembic current
```

---

## 8. Первый вход

1. Откройте frontend в браузере
2. Войдите с учётными данными из `FIRST_SUPERUSER_EMAIL` и `FIRST_SUPERUSER_PASSWORD`
3. Смените пароль в настройках аккаунта

---

## 9. Полезные команды

```bash
# Просмотр логов
docker compose logs -f backend

# Остановка
docker compose down

# Остановка с удалением данных (БД, Redis)
docker compose down -v

# Пересборка после изменений кода
docker compose build --no-cache
docker compose up -d
```

---

## 10. Бэкапы PostgreSQL

```bash
# Создание бэкапа
docker compose exec postgres pg_dump -U fbs_user fbs_db > backup_$(date +%Y%m%d).sql

# Восстановление
docker compose exec -T postgres psql -U fbs_user fbs_db < backup_20250101.sql
```

---

## 11. Обновление приложения

```bash
cd /opt/fbs
git pull
docker compose build --no-cache
docker compose up -d
# Миграции применятся автоматически при старте backend
```

---

## 12. Решение проблем

### Backend не стартует
- Проверьте логи: `docker compose logs backend`
- Убедитесь, что Postgres и Redis запущены: `docker compose ps`
- Проверьте переменные в `.env`

### Ошибка подключения к БД
- Дождитесь готовности Postgres (healthcheck)
- Проверьте `DATABASE_URL` и пароли

### CORS-ошибки в браузере
- Добавьте домен frontend в `BACKEND_CORS_ORIGINS` в `.env`

### Сборка падает с `Killed` (exit code 137)
**Причина:** OOM Killer — нехватка RAM при сборке Docker-образа.

**Решение 1 — добавить swap (рекомендуется):**
```bash
# Создать swap-файл 2 GB
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Сделать постоянным (добавить в /etc/fstab)
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Проверка
free -h
```

**Решение 2:** Dockerfile уже упрощён (без gcc/g++/libpq-dev) — все пакеты используют wheels. Если всё равно падает, добавьте swap.
