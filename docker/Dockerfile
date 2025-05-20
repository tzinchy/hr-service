FROM python:3.12-slim

WORKDIR /app

# Устанавливаем uv без предупреждений
RUN pip install --no-warn-script-location --root-user-action=ignore uv

# Копируем зависимости (выберите один вариант)

# Вариант A: Если есть единый requirements.txt в корне
COPY requirements.txt .
RUN uv pip install -r requirements.txt --no-cache-dir

# Вариант B: Если у каждого сервиса свои зависимости
# COPY auth_service/requirements.txt ./auth_service/
# COPY frontend_auth/requirements.txt ./frontend_auth/
# COPY user/requirements.txt ./user/
# RUN uv pip install -r auth_service/requirements.txt && \
#     uv pip install -r frontend_auth/requirements.txt && \
#     uv pip install -r user/requirements.txt

# Копируем код
COPY auth_service/ ./auth_service/
COPY frontend_auth/ ./frontend_auth/
COPY user/ ./user/

# Настраиваем окружение
ENV PYTHONPATH=/app
ENV UVICORN_PORT=8001