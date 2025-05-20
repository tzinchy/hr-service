# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Устанавливаем uv (если нужно)
RUN pip install uv

# Копируем зависимости всех сервисов
COPY pyproject.toml poetry.lock* ./

# Устанавливаем зависимости через uv (аналог pip install)
RUN uv pip install . --no-cache-dir

# Копируем все сервисы
COPY auth_service/ ./auth_service/
COPY frontend_auth/ ./frontend_auth/
COPY user/ ./user/

# Общие переменные окружения
ENV PYTHONPATH=/app
ENV UVICORN_PORT=8001