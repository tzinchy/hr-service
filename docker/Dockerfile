FROM python:3.12-slim

WORKDIR /app

# Устанавливаем зависимости через pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код
COPY . .

# Настраиваем окружение
ENV PYTHONPATH=/app \
    UVICORN_PORT=8001