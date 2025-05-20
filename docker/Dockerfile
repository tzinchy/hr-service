FROM python:3.12-slim

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем только нужные директории
COPY auth_service/ ./auth_service/
COPY frontend_auth/ ./frontend_auth/
COPY user/ ./user/

# Настройка окружения
ENV PYTHONPATH=/app \
    UVICORN_PORT=8001