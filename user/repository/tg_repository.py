from datetime import datetime
from repository.database import get_connection, get_async_connection
import logging
from aiogram.types import Message

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def is_user_authorized(chat_id: int) -> bool:
    """Проверяет, авторизован ли пользователь и принял ли политику"""
    try:
        async with get_async_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """SELECT 1 FROM hr.candidate 
                    WHERE telegram_chat_id = %s AND agreement_accepted = TRUE""",
                    (chat_id,)
                )
                return bool(cursor.fetchone())
    except Exception as e:
        logger.error(f"Error checking authorization: {e}")
        return False

# Update all save_message calls to properly handle message vs text
async def save_message(chat_id: int, text: str, is_bot: bool):
    """Save message to database"""
    try:
        async with await get_async_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("""
                    INSERT INTO comm.telegram_message (
                        chat_id,
                        message_text,
                        is_bot,
                        created_at
                    ) VALUES (%s, %s, %s, %s)
                """, (
                    chat_id,
                    text,
                    is_bot,
                    datetime.now()
                ))
                await conn.commit()
    except Exception as e:
        logger.error(f"Error saving message: {e}")

async def get_candidate_uuid_by_chat_id(chat_id: int):
    """Получить candidate_uuid по chat_id"""
    try:
        async with get_async_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """SELECT candidate_uuid FROM hr.candidate 
                    WHERE telegram_chat_id = %s""",
                    (chat_id,)
                )
                result = cursor.fetchone()
                return result[0] if result else None
    except Exception as e:
        logger.error(f"Error getting candidate UUID: {e}")
        return None

async def create_required_documents(candidate_uuid: str):
    """Создает записи для требуемых документов кандидата"""
    try:
        async with get_async_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT COUNT(*) FROM hr.document_template")
                count = cursor.fetchone()[0]
                
                if count == 0:
                    # Если нет шаблонов, создаем базовые
                    await cursor.execute("""
                        INSERT INTO hr.document_template (name, description, is_required, processing_days, order_position, instructions)
                        VALUES 
                        ('Паспорт', 'Скан паспорта', TRUE, 1, 1, 'Загрузите скан паспорта'),
                        ('ИНН', 'Скан ИНН', TRUE, 1, 2, 'Загрузите скан ИНН'),
                        ('СНИЛС', 'Скан СНИЛС', TRUE, 1, 3, 'Загрузите скан СНИЛС'),
                        ('Выписка банка', 'Выписка с банковского счета в Excel', TRUE, 1, 4, 'Загрузите выписку с банковского счета')
                    """)
                
                # Получаем все шаблоны документов
                await cursor.execute("""
                    SELECT template_id FROM hr.document_template
                    ORDER BY order_position
                """)
                
                templates = cursor.fetchall()
                
                # Проверяем, есть ли уже документы у кандидата
                await cursor.execute("""
                    SELECT template_id FROM hr.candidate_document
                    WHERE candidate_id = %s
                """, (candidate_uuid,))
                
                existing_templates = [row[0] for row in cursor.fetchall()]
                
                for template in templates:
                    template_id = template[0]
                    if template_id not in existing_templates:
                        await cursor.execute("""
                            INSERT INTO hr.candidate_document (
                                document_id,
                                candidate_id,
                                template_id,
                                status_id,
                                created_at,
                                updated_at
                            ) VALUES (
                                gen_random_uuid(),
                                %s,
                                %s,
                                1, -- Статус "Не загружен"
                                NOW(),
                                NOW()
                            )
                        """, (candidate_uuid, template_id))
                
                await conn.commit()
    except Exception as e:
        logger.error(f"Error creating required documents: {e}")

async def save_location(candidate_uuid: str, latitude: float, longitude: float, accuracy: float = None) -> bool:
    """Сохраняет геолокацию кандидата в базу данных"""
    try:
        async with get_async_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("""
                    INSERT INTO hr.candidate_location (
                        candidate_uuid,
                        latitude,
                        longitude,
                        accuracy
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (candidate_uuid) DO UPDATE
                    SET 
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude,
                        accuracy = EXCLUDED.accuracy,
                        updated_at = NOW()
                """, (
                    candidate_uuid,
                    latitude,
                    longitude,
                    accuracy
                ))
                await conn.commit()
                return True
    except Exception as e:
        logger.error(f"Error saving location: {e}")
        return False
    

async def update_document_status(document_id: int, new_status: int):
    """Обновляет статус документа"""
    try:
        async with get_async_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("""
                    UPDATE hr.candidate_document
                    SET status_id = %s,
                        updated_at = NOW()
                    WHERE document_id = %s
                    RETURNING document_id, status_id
                """, (new_status, document_id))
                
                updated_doc = cursor.fetchone()
                
                if updated_doc:
                    await cursor.execute("""
                        INSERT INTO hr.document_history (document_uuid, status_id, created_at)
                        VALUES (%s, %s, NOW())
                    """, (updated_doc[0], updated_doc[1]))
                    
                    await conn.commit()
                    return True
        return False
    except Exception as e:
        logger.error(f"Error updating document status: {e}")
        return False
