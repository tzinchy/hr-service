import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class ProjectManagementSettings:
    DB_HOST: str = os.environ.get("DB_HOST")
    DB_PORT: str = os.environ.get("DB_PORT")
    DB_USER: str = os.environ.get("DB_USER")
    DB_PASSWORD: str = os.environ.get("DB_PASSWORD")
    DB_NAME: str = os.environ.get("DB_NAME")

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    ALGORITHM: str = os.environ.get("ALGORITHM")
    SECRET_KEY: str = os.environ.get("SECRET_KEY")
    URL : str = os.environ.get('USER_URL')

@dataclass
class EmailSetting:
    EMAIL_SENDER: str = os.environ.get("EMAIL_SENDER")
    EMAIL_PASSWORD: str = os.environ.get("EMAIL_PASSWORD")
    EMAIL_SERVER: str = os.environ.get("EMAIL_SERVER")
    EMAIL_PORT: str = os.environ.get("EMAIL_PORT")
    EMAIL_LOGIN: str = os.environ.get("EMAIL_LOGIN")

@dataclass
class RedisSetting:
    REDIS_HOST : str = os.environ.get("REDIS_HOST")

@dataclass
class MinioSetting: 
    MINIO_USER : str = os.environ.get('MINIO_USER')
    MINIO_PASSWORD : str = os.environ.get('MINIO_PASSWORD')
    MINIO_ENDPOINT : str = os.environ.get('MINIO_ENDPOINT')


@dataclass
class TelegramBotSetting: 
    TELEGRAM_TOKEN : str = os.environ.get('TELEGRAM_TOKEN')

@dataclass
class GEMINI: 
    GEMINI_TOKEN : str = os.environ.get('GEMINI_TOKEN')

@dataclass
class Settings:
    project_management_setting: ProjectManagementSettings = field(default_factory=ProjectManagementSettings)
    email_settings: EmailSetting = field(default_factory=EmailSetting)
    redis : RedisSetting = field(default_factory=RedisSetting)
    minio : MinioSetting = field(default_factory=MinioSetting)
    bot : TelegramBotSetting = field(default_factory=TelegramBotSetting)
    gemini : GEMINI = field(default_factory=GEMINI)

settings = Settings()
print(settings.project_management_setting.DATABASE_URL)
