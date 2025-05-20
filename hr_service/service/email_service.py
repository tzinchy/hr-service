import io
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from core.config import settings
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_email(to_email: str, subject: str, message: str, is_html: bool = False):
    """Базовая функция отправки email"""
    try:
        msg = MIMEMultipart()
        msg["From"] = settings.email_settings.EMAIL_LOGIN
        msg["To"] = to_email
        msg["Subject"] = subject

        if is_html:
            msg.attach(MIMEText(message, "html"))
        else:
            msg.attach(MIMEText(message, "plain"))

        with smtplib.SMTP(
            settings.email_settings.EMAIL_SERVER, 
            settings.email_settings.EMAIL_PORT
        ) as server:
            server.starttls()
            server.login(
                settings.email_settings.EMAIL_LOGIN,
                settings.email_settings.EMAIL_PASSWORD,
            )
            server.send_message(msg)

        logger.info(f"Email отправлен на {to_email} с темой '{subject}'")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки email: {str(e)}")
        return False

def send_invitation_email(email: str, invitation_code: str):
    """Отправляет email с кодом приглашения"""
    subject = "Ваш код доступа к системе"
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
                <h2 style="color: #1f2937;">Добро пожаловать!</h2>
                <p style="font-size: 16px; color: #4b5563;">
                    Ваш код для регистрации в системе:
                </p>
                <div style="
                    background-color: #f3f4f6;
                    padding: 15px;
                    border-radius: 6px;
                    text-align: center;
                    font-size: 24px;
                    font-weight: bold;
                    margin: 20px 0;
                    color: #111827;">
                    {invitation_code}
                </div>
                <p style="font-size: 14px; color: #6b7280; margin-top: 30px;">
                    С уважением,<br>Ваша команда
                </p>
            </div>
        </body>
    </html>
    """
    return send_email(email, subject, html, is_html=True)

def send_status_email(email: str, first_name: str, last_name: str, status: str, status_description: str):
    """Отправляет email об изменении статуса кандидата"""
    subject = f"Обновление статуса: {status}"
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
                <h2 style="color: #1f2937;">Уважаемый(ая) {first_name} {last_name},</h2>
                <p style="font-size: 16px; color: #4b5563;">
                    Ваш статус в системе был изменен на: <strong>{status}</strong>
                </p>
                <p style="font-size: 16px; color: #4b5563; margin-top: 20px;">
                    {status_description}
                </p>
                <p style="font-size: 14px; color: #6b7280; margin-top: 30px;">
                    С уважением,<br>Компания {settings.company_name}
                </p>
            </div>
        </body>
    </html>
    """
    return send_email(email, subject, html, is_html=True)

def send_telegram_notification(chat_id: str, message: str):
    """Отправляет уведомление в Telegram"""
    try:
        if not settings.bot.TELEGRAM_TOKEN:
            logger.warning("Telegram bot token не настроен")
            return False

        url = f"https://api.telegram.org/bot{settings.bot.TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        response = requests.post(url, json=payload)
        response.raise_for_status()

        logger.info(f"Telegram уведомление отправлено в чат {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки Telegram уведомления: {str(e)}")
        return False

def send_status_notifications(email: str, telegram_chat_id: Optional[str], 
                            first_name: str, last_name: str, 
                            status: str, status_description: str):
    """Отправляет уведомления о статусе на email и в Telegram"""
    # Отправка email
    email_sent = send_status_email(email, first_name, last_name, status, status_description)
    
    # Отправка в Telegram если chat_id есть
    telegram_sent = False
    if telegram_chat_id:
        telegram_message = f"""
        <b>Уважаемый(ая) {first_name} {last_name},</b>

        Ваш статус был изменен на: <b>{status}</b>

        {status_description}

        С уважением,
        Компания {settings.company_name}
        """
        telegram_sent = send_telegram_notification(telegram_chat_id, telegram_message)
    
    return email_sent, telegram_sent