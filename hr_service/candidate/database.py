import psycopg2
from core.config import settings
from minio import Minio
from minio.error import S3Error

def get_connection():
    return psycopg2.connect(
        database=settings.project_management_setting.DB_NAME,
        host=settings.project_management_setting.DB_HOST,
        user=settings.project_management_setting.DB_USER,
        password=settings.project_management_setting.DB_PASSWORD,
        port=settings.project_management_setting.DB_PORT
    )


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

