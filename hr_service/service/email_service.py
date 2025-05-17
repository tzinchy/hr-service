import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def send_invitation_email(email: str, invitation_code: str):
    """Отправляет email с кодом приглашения"""
    try:
        # Создаем сообщение
        msg = MIMEMultipart()
        msg["From"] = settings.email_settings.EMAIL_LOGIN
        msg["To"] = email
        msg["Subject"] = "Ваш код доступа к системе"

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
        with smtplib.SMTP(
            settings.email_settings.EMAIL_SERVER, settings.email_settings.EMAIL_PORT
        ) as server:
            server.starttls()
            server.login(
                settings.email_settings.EMAIL_LOGIN,
                settings.email_settings.EMAIL_PASSWORD,
            )
            server.send_message(msg)

        logger.info(f"Письмо с кодом отправлено на {email}")

    except Exception as e:
        logger.error(f"Ошибка отправки email: {str(e)}")
        raise
