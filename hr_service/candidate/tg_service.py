import pandas as pd
from datetime import datetime
from candidate.database import get_connection
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def is_user_authorized(chat_id: int) -> bool:
    """Проверяет, авторизован ли пользователь и принял ли политику"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT 1 FROM hr.candidate 
                    WHERE telegram_chat_id = %s AND agreement_accepted = TRUE""",
                    (chat_id,)
                )
                return bool(cursor.fetchone())
    except Exception as e:
        logger.error(f"Error checking authorization: {e}")
        return False

async def save_message(chat_id: int, text: str, is_from_admin: bool = False):
    """Сохраняет сообщение в базу данных с проверкой существования чата"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Проверяем существование чата
                cursor.execute(
                    """SELECT 1 FROM comm.telegram_chat WHERE chat_id = %s""", 
                    (chat_id,)
                )
                chat_exists = cursor.fetchone()
                
                # Если чат не существует, создаем его
                if not chat_exists:
                    cursor.execute("""
                        INSERT INTO comm.telegram_chat (
                            chat_id, 
                            chat_type,
                            created_at,
                            updated_at
                        ) VALUES (%s, %s, %s, %s)
                    """, (
                        chat_id,
                        'private',
                        datetime.now(),
                        datetime.now()
                    ))
                
                # Сохраняем сообщение
                cursor.execute("""
                    INSERT INTO comm.message (
                        chat_id, 
                        content, 
                        sender_type, 
                        sent_at, 
                        is_from_admin
                    ) VALUES (%s, %s, %s, %s, %s)
                """, (
                    chat_id,
                    text,
                    'admin' if is_from_admin else 'candidate',
                    datetime.now(),
                    is_from_admin
                ))
                conn.commit()
    except Exception as e:
        logger.error(f"Error saving message: {e}")

async def get_candidate_uuid_by_chat_id(chat_id: int):
    """Получить candidate_uuid по chat_id"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
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
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Проверяем, есть ли записи в таблице шаблонов
                cursor.execute("SELECT COUNT(*) FROM hr.document_template")
                count = cursor.fetchone()[0]
                
                if count == 0:
                    # Если нет шаблонов, создаем базовые
                    cursor.execute("""
                        INSERT INTO hr.document_template (name, description, is_required, processing_days, order_position, instructions)
                        VALUES 
                        ('Паспорт', 'Скан паспорта', TRUE, 1, 1, 'Загрузите скан паспорта'),
                        ('ИНН', 'Скан ИНН', TRUE, 1, 2, 'Загрузите скан ИНН'),
                        ('СНИЛС', 'Скан СНИЛС', TRUE, 1, 3, 'Загрузите скан СНИЛС'),
                        ('Выписка банка', 'Выписка с банковского счета в Excel', TRUE, 1, 4, 'Загрузите выписку с банковского счета')
                    """)
                
                # Получаем все шаблоны документов
                cursor.execute("""
                    SELECT template_id FROM hr.document_template
                    ORDER BY order_position
                """)
                
                templates = cursor.fetchall()
                
                # Проверяем, есть ли уже документы у кандидата
                cursor.execute("""
                    SELECT template_id FROM hr.candidate_document
                    WHERE candidate_id = %s
                """, (candidate_uuid,))
                
                existing_templates = [row[0] for row in cursor.fetchall()]
                
                for template in templates:
                    template_id = template[0]
                    if template_id not in existing_templates:
                        cursor.execute("""
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
                
                conn.commit()
    except Exception as e:
        logger.error(f"Error creating required documents: {e}")

async def process_bank_statement(file_path, candidate_uuid):
    """Обработка банковской выписки из Excel файла"""
    try:
        # Загружаем Excel файл
        df = pd.read_excel(file_path)

        required_columns = ['Наименование банка', 'Номер счета (вклада)', 'Дата открытия', 'Дата закрытия', 'Вид счета', 'Состояние счета']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            return False, f"В файле отсутствуют следующие столбцы: {', '.join(missing_columns)}"
        
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Удаляем существующие записи для этого кандидата
                cursor.execute("DELETE FROM hr.bank_accounts WHERE candidate_uuid = %s", (candidate_uuid,))
                
                # Вставляем новые записи
                for _, row in df.iterrows():
                    cursor.execute("""
                        INSERT INTO hr.bank_accounts (
                            candidate_uuid,
                            bank,
                            account_number,
                            open_date,
                            close_date,
                            account_type,
                            status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        candidate_uuid,
                        row['Наименование банка'],
                        row['Номер счета (вклада)'],
                        row['Дата открытия'],
                        row['Дата закрытия'] if not pd.isna(row['Дата закрытия']) else None,
                        row['Вид счета'],
                        row['Состояние счета']
                    ))
                
                # Обновляем статус документа выписки в hr.candidate_document
                cursor.execute("""
                    UPDATE hr.candidate_document
                    SET status_id = 2 -- Статус "Загружен"
                    FROM hr.document_template
                    WHERE candidate_document.candidate_id = %s
                    AND candidate_document.template_id = document_template.template_id
                    AND document_template.name = 'Выписка банка'
                """, (candidate_uuid,))
                
                conn.commit()
                return True, "Банковская выписка успешно обработана"
    except Exception as e:
        logger.error(f"Error processing bank statement: {e}")
        return False, f"Ошибка при обработке файла: {e}"