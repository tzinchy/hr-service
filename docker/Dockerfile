# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Устанавливаем uv и избегаем предупреждений
RUN pip install --no-warn-script-location --root-user-action=ignore uv

# Создаем общий requirements.txt (если нужно)
RUN echo "uvicorn\nstreamlit\nfastapi" > requirements.txt  # добавьте свои зависимости

# Устанавливаем зависимости через uv
RUN uv pip install -r requirements.txt --no-cache-dir

# Копируем все сервисы
COPY auth_service/ ./auth_service/
COPY frontend_auth/ ./frontend_auth/
COPY user/ ./user/

# Общие переменные окружения
ENV PYTHONPATH=/app
ENV UVICORN_PORT=8001