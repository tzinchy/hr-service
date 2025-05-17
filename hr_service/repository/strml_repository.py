from repository.database import get_connection, get_minio_client
from datetime import datetime
import logging
import io
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def save_message(chat_id: int, text: str, is_from_admin: bool = False):
    """Сохраняет сообщение в базу данных с проверкой существования чата"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Проверяем существование чата
                cursor.execute(
                    """SELECT 1 FROM comm.telegram_chat WHERE chat_id = %s""",
                    (chat_id,),
                )
                chat_exists = cursor.fetchone()

                # Если чат не существует, создаем его
                if not chat_exists:
                    cursor.execute(
                        """
                        INSERT INTO comm.telegram_chat (
                            chat_id, 
                            chat_type,
                            created_at,
                            updated_at
                        ) VALUES (%s, %s, %s, %s)
                    """,
                        (chat_id, "private", datetime.now(), datetime.now()),
                    )

                # Сохраняем сообщение
                cursor.execute(
                    """
                    INSERT INTO comm.message (
                        chat_id, 
                        content, 
                        sender_type, 
                        sent_at, 
                        is_from_admin
                    ) VALUES (%s, %s, %s, %s, %s)
                """,
                    (
                        chat_id,
                        text,
                        "admin" if is_from_admin else "candidate",
                        datetime.now(),
                        is_from_admin,
                    ),
                )
                conn.commit()
    except Exception as e:
        logger.error(f"Error saving message: {e}")


def add_candidate_to_db(first_name: str, last_name: str, email: str, sex: bool):
    """
    Добавляет кандидата в систему
    :param first_name: Имя
    :param last_name: Фамилия
    :param email: Email
    :param sex: Пол (True - мужской, False - женский)
    :return: tuple (candidate_uuid, invitation_code)
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            try:
                # Вставка кандидата
                cursor.execute(
                    """
                    INSERT INTO hr.candidate (
                        first_name, last_name, email, sex
                    ) VALUES (%s, %s, %s, %s)
                    RETURNING candidate_uuid, invitation_code
                    """,
                    (first_name, last_name, email, sex),
                )

                candidate_uuid, invitation_code = cursor.fetchone()

                # Создание папки в MinIO
                minio_client = get_minio_client()
                bucket_name = "candidates"
                folder_name = f"{candidate_uuid}/"

                if not minio_client.bucket_exists(bucket_name):
                    minio_client.make_bucket(bucket_name)

                minio_client.put_object(bucket_name, folder_name, io.BytesIO(b""), 0)

                connection.commit()
                logger.info(f"Добавлен кандидат {candidate_uuid}")
                return candidate_uuid, invitation_code

            except Exception as e:
                connection.rollback()
                logger.error(f"Ошибка при добавлении кандидата: {str(e)}")
                raise Exception(f"Ошибка при добавлении кандидата: {str(e)}")


def get_all_chats():
    """Получает список всех чатов с последним сообщением"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        c.candidate_uuid::text,
                        c.first_name,
                        c.last_name,
                        c.telegram_chat_id::bigint,
                        cs.name as status,
                        m.content as last_message,
                        m.sent_at as last_message_time,
                        m.is_from_admin as is_last_from_admin,
                        EXISTS (
                            SELECT 1 FROM comm.message 
                            WHERE chat_id = c.telegram_chat_id 
                            AND NOT is_from_admin 
                            AND sent_at > COALESCE(
                                (SELECT last_read FROM comm.chat_status 
                                 WHERE chat_id = c.telegram_chat_id), 
                                '1970-01-01'::timestamp
                            )
                        ) as has_unread
                    FROM hr.candidate c
                    JOIN hr.candidate_status cs ON c.status_id = cs.status_id
                    LEFT JOIN comm.telegram_chat tc ON tc.chat_id = c.telegram_chat_id
                    LEFT JOIN LATERAL (
                        SELECT content, sent_at, is_from_admin 
                        FROM comm.message 
                        WHERE chat_id = c.telegram_chat_id 
                        ORDER BY sent_at DESC 
                        LIMIT 1
                    ) m ON true
                    WHERE c.telegram_chat_id IS NOT NULL
                    ORDER BY m.sent_at DESC NULLS LAST
                """)
                columns = [desc[0] for desc in cursor.description]
                return pd.DataFrame(cursor.fetchall(), columns=columns)
    except Exception as e:
        logger.error(f"Ошибка при получении списка чатов: {e}")
        return pd.DataFrame()


def check_new_messages(chat_id: int, last_check: datetime):
    """Проверяет наличие новых сообщений через поллинг БД"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM comm.message 
                        WHERE chat_id = %s 
                        AND NOT is_from_admin 
                        AND sent_at > %s
                    )
                """,
                    (chat_id, last_check),
                )
                return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Ошибка при проверке новых сообщений: {e}")
        return False

def get_chat_history(chat_id: int):
    """Получает историю сообщений с кандидатом"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Убедимся, что чат существует
                cursor.execute("""
                    INSERT INTO comm.telegram_chat (chat_id, chat_type)
                    VALUES (%s, 'candidate')
                    ON CONFLICT (chat_id) DO NOTHING
                """, (int(chat_id),))
                
                # Обновим время последнего прочтения
                cursor.execute("""
                    INSERT INTO comm.chat_status (chat_id, last_read)
                    VALUES (%s, NOW())
                    ON CONFLICT (chat_id) DO UPDATE 
                    SET last_read = EXCLUDED.last_read
                """, (int(chat_id),))
                
                # Получим историю сообщений
                cursor.execute("""
                    SELECT 
                        content,
                        sent_at,
                        is_from_admin
                    FROM comm.message
                    WHERE chat_id = %s
                    ORDER BY sent_at
                """, (int(chat_id),))
                messages = cursor.fetchall()
                conn.commit()
                return messages
    except Exception as e:
        logger.error(f"Ошибка при получении истории чата {chat_id}: {e}")
        return []