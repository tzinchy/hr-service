import psycopg2
from core.config import settings
from minio import Minio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
import asyncpg
from core.config import settings

def get_connection():
        return psycopg2.connect(host=settings.project_management_setting.DB_HOST,  
        port="5432",
        user="user",
        password="password",
        database="database")

def get_minio_client():
    """
    Создает и возвращает клиент MinIO с настройками из конфига
    """
    return Minio(
        endpoint='minio:9000', 
        access_key='minioadmin', 
        secret_key='minioadmin',  
        secure=False,
    )


async def get_async_connection():
    """Get an async database connection"""
    return await asyncpg.connect(settings.project_management_setting.FOR_ASYNC_URL)



