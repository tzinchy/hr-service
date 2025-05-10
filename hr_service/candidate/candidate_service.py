from candidate.database import get_connection, get_minio_client
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from core.config import settings
import logging
import pandas 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_invitation_email(email: str, invitation_code: str):
    """Отправляет email с кодом приглашения"""
    try:
        # Создаем сообщение
        msg = MIMEMultipart()
        msg['From'] = settings.email_settings.EMAIL_LOGIN
        msg['To'] = email
        msg['Subject'] = "Ваш код доступа к системе"
        
        # Текст письма
        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; margin: 0; padding: 0; background-color: #f3f4f6; height: 100%;">
                <div style="
                    max-width: 600px;
                    width: 100%;
                    margin: 20px auto;
                    background-color: #ffffff;
                    padding: 30px;
                    border-radius: 8px;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                    <div style="font-size: 16px; color: #4b5563;">
                        {invitation_code}
                    </div>
                    <p style="font-size: 14px; color: #6b7280; margin-top: 30px;">
                        С уважением,<br>Ваша команда
                    </p>
                </div>
            </body>
        </html>
        """
        
        msg.attach(MIMEText(html, "html"))
        
        # Отправка
        with smtplib.SMTP(settings.email_settings.EMAIL_SERVER, settings.email_settings.EMAIL_PORT) as server:
            server.starttls()
            server.login(settings.email_settings.EMAIL_LOGIN, settings.email_settings.EMAIL_PASSWORD)
            server.send_message(msg)
            
        logger.info(f"Письмо с кодом отправлено на {email}")
        
    except Exception as e:
        logger.error(f"Ошибка отправки email: {str(e)}")
        raise

def add_candidate(first_name: str, last_name: str, email: str, sex: bool):
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
                    (first_name, last_name, email, sex)
                )
                
                candidate_uuid, invitation_code = cursor.fetchone()
                
                # Создание папки в MinIO
                minio_client = get_minio_client()
                bucket_name = "candidates"
                folder_name = f"{candidate_uuid}/"
                
                if not minio_client.bucket_exists(bucket_name):
                    minio_client.make_bucket(bucket_name)
                
                minio_client.put_object(
                    bucket_name,
                    folder_name,
                    io.BytesIO(b""),
                    0
                )
                
                # Отправка письма
                send_invitation_email(email, invitation_code)
                
                connection.commit()
                logger.info(f"Добавлен кандидат {candidate_uuid}")
                return candidate_uuid, invitation_code
                
            except Exception as e:
                connection.rollback()
                logger.error(f"Ошибка при добавлении кандидата: {str(e)}")
                raise Exception(f"Ошибка при добавлении кандидата: {str(e)}")
            
def update_candidate(telegram_chat_id, code): 
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'''UPDATE hr.candiadte set telegram_chat_id = {telegram_chat_id}' \
            where invitation_code = {code}''')
            connection.commit()