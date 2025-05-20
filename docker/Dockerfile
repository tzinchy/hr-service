FROM python:3.12-slim

WORKDIR /app

# Устанавливаем системные зависимости для Linux
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем общие зависимости
COPY requirements.txt .

# Устанавливаем Python-зависимости
RUN pip install --no-cache-dir -r requirements.txt && \
    pip cache purge

# Копируем код сервисов
COPY auth_service/ ./auth_service/
COPY frontend_auth/ ./frontend_auth/
COPY user/ ./user/

# Фиксируем переменные окружения
ENV PYTHONPATH=/app \
    UVICORN_PORT=8001 \
    LANG=C.UTF-8