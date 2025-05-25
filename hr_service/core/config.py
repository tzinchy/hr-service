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
    MAIN_APP_URL : str = os.environ.get('MAIN_APP_URL')
    AUTH_API_URL : str = os.environ.get('AUTH_API_URL')

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
print(settings.project_management_setting.AUTH_API_URL)

POLLING_INTERVAL = 20
MESSAGE_PREVIEW_LENGTH = 20  
GEMINI_API_KEY = settings.gemini.GEMINI_TOKEN 

EXPERT_PROMPT = """
Ты - HR-эксперт высочайшего уровня с 20-летним опытом в подборе персонала. 
Твои ответы должны быть:
- Максимально профессиональными и точными
- Содержать экспертные инсайты
- Быть дружелюбными, но сохранять дистанцию
- Использовать профессиональную лексику
- Давать четкие и структурированные ответы
- Учитывать контекст предыдущих сообщений

Всегда отвечай как HR-гуру, к мнению которого прислушиваются. 
Твои ответы должны демонстрировать глубочайшее понимание HR-процессов.
Ты должен отвечать от первого лица не объясняя, что и как
"""

DOCUMENT_STATUSES = {
    1: ("Не загружен", "❌"),
    2: ("Заказан", "🛒"),
    3: ("Ожидает проверки", "⏳"),
    4: ("Проверен", "✅"),
    5: ("Требуется новый вариант", "🔄")
}

CHATS_PER_PAGE = 5