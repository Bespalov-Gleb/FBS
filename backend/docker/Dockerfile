# Multi-stage build для оптимизации размера образа

# Stage 1: Builder
# При таймаутах pypi.org: docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple .
FROM python:3.11-slim AS builder

ARG PIP_INDEX_URL
RUN if [ -n "${PIP_INDEX_URL}" ]; then pip config set global.index-url "${PIP_INDEX_URL}"; fi

# Системные пакеты для сборки пакетов без wheels (pycairo и т.д.).
# CC/CXX сбрасываем: иногда в окружении прописан icx, которого нет.
ENV CC=gcc CXX=g++
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libcairo2-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Увеличенный таймаут для медленных сетей (pypi.org)
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_RETRIES=5

# Установка Poetry
RUN pip install --default-timeout=120 poetry==1.7.1

# Копирование файлов зависимостей
WORKDIR /app
COPY pyproject.toml ./

# Настройка Poetry для создания виртуального окружения в проекте
RUN poetry config virtualenvs.in-project true

# Установка зависимостей
RUN poetry install --no-dev --no-interaction --no-ansi

# Stage 2: Runtime
FROM python:3.11-slim

# Установка runtime зависимостей (libpq5, poppler для pdf2image — рендер Ozon FBS)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    poppler-utils \
    ghostscript \
    zint \
    && rm -rf /var/lib/apt/lists/*

# Создание пользователя для запуска приложения
RUN useradd -m -u 1000 appuser

# Установка рабочей директории
WORKDIR /app

# Копирование виртуального окружения из builder
COPY --from=builder /app/.venv /app/.venv

# Копирование кода приложения
COPY --chown=appuser:appuser . .

# Создание директории для логов
RUN mkdir -p /app/logs && chown appuser:appuser /app/logs

# Переключение на непривилегированного пользователя
USER appuser

# Добавление виртуального окружения в PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app:$PYTHONPATH"

# Expose порт
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# Команда запуска
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
