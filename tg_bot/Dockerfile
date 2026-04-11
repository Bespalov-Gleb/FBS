FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

COPY . /app

RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app

# Старт от root: entrypoint делает chown на смонтированные ./uploads и ./outputs (bind-mount с хоста),
# затем gosu переключает процесс на botuser.
ENTRYPOINT ["/bin/sh", "/docker-entrypoint.sh"]
CMD ["python", "main.py"]
