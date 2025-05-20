import psycopg2
from core.config import settings
from minio import Minio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
import asyncpg

def get_connection():
    return psycopg2.connect(
        database=settings.project_management_setting.DB_NAME,
        host=settings.project_management_setting.DB_HOST,
        user=settings.project_management_setting.DB_USER,
        password=settings.project_management_setting.DB_PASSWORD,
        port=settings.project_management_setting.DB_PORT
    )

async def get_async_connection():
    """Get an async database connection"""
    return await asyncpg.connect(settings.project_management_setting.FOR_ASYNC_URL)

def get_minio_client():
    """
    Создает и возвращает клиент MinIO с настройками из конфига
    """
    return Minio(
        endpoint=settings.minio.MINIO_ENDPOINT,  # Обычно "localhost:9000"
        access_key=settings.minio.MINIO_USER,     # Логин (по умолчанию "minioadmin")
        secret_key=settings.minio.MINIO_PASSWORD, # Пароль (по умолчанию "minioadmin")
        secure=False
    )

