from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from core.config import settings

print(settings.project_management_setting.DATABASE_URL)

EGNINE = create_async_engine('postgresql+asyncpg://user:password@postgres:5432/database')

auth_session = sessionmaker(EGNINE, class_=AsyncSession, expire_on_commit=False)

