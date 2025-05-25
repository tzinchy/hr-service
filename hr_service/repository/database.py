import psycopg2
from core.config import settings
from minio import Minio
from minio.error import S3Error
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
        endpoint=settings.minio.MINIO_ENDPOINT,  # Обычно "localhost:9000"
        access_key='minioadmin',  # Логин (по умолчанию "minioadmin")
        secret_key='minioadmin',  # Пароль (по умолчанию "minioadmin")
        secure=False,
    )
