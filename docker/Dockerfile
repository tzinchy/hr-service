FROM python:3.13-slim

# Устанавливаем uv (менеджер пакетов и рантайм)
RUN pip install uv && \
    uv venv -q && \
    uv pip install --no-cache-dir "uvicorn[standard]" "streamlit" "redis" "asyncpg" "minio" "httpx"

# Копируем все сервисы разом
COPY . .

ENTRYPOINT ["uv"]