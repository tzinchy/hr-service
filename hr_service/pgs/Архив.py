import streamlit as st 
import pandas as pd 
from repository.database import get_connection
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib
from core.config import settings
import logging
from io import BytesIO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_email_with_attachment(to_email: str, subject: str, message: str, attachment=None, filename=None):
    """Функция отправки email с вложением"""
    try:
        msg = MIMEMultipart()
        msg["From"] = settings.email_settings.EMAIL_LOGIN
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(message, "plain"))

        if attachment is not None:
            part = MIMEApplication(attachment.read(), Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)

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

        logger.info(f"Email с вложением отправлен на {to_email}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки email: {str(e)}")
        return False

def render_archived_candidates_page():
    st.title("📁 Архивные кандидаты")
    
    # Загрузка данных
    df = pd.read_sql("""
        SELECT 
            candidate_uuid,
            first_name || ' ' || last_name AS full_name,
            email,
            status_id,
            archived_at,
            notes
        FROM hr.candidate_archive
        ORDER BY archived_at DESC
    """, get_connection())

    if df.empty:
        st.info("Нет архивных кандидатов")
        return

    # Разделение на две колонки
    col1, col2 = st.columns([3, 2])

    with col1:
        st.subheader("Список архивных кандидатов")
        st.dataframe(
            df[["full_name", "email", "archived_at"]],
            column_config={
                "full_name": "ФИО",
                "email": "Email",
                "archived_at": "Дата архивации"
            },
            hide_index=True,
            use_container_width=True
        )

    with col2:
        st.subheader("Отправить сообщение")
        
        # Выбор кандидата
        selected_candidate = st.selectbox(
            "Выберите кандидата:",
            options=df["email"],
            format_func=lambda x: df[df["email"] == x]["full_name"].values[0]
        )
        
        if selected_candidate:
            candidate_data = df[df["email"] == selected_candidate].iloc[0]
            
            # Форма для отправки сообщения
            with st.form(key='email_form'):
                st.markdown(f"**Кандидат:** {candidate_data['full_name']}")
                st.markdown(f"**Email:** {candidate_data['email']}")
                
                subject = st.text_input("Тема письма", "Информация от компании")
                message = st.text_area("Текст сообщения", height=200)
                
                # Поле для загрузки файла
                uploaded_file = st.file_uploader(
                    "Прикрепить документ", 
                    type=["pdf", "docx", "xlsx", "jpg", "png"],
                    accept_multiple_files=False
                )
                
                submit_button = st.form_submit_button("📤 Отправить сообщение")
                
                if submit_button:
                    if uploaded_file:
                        # Чтение файла в BytesIO
                        file_bytes = BytesIO(uploaded_file.getvalue())
                        
                        if send_email_with_attachment(
                            to_email=candidate_data['email'],
                            subject=subject,
                            message=message,
                            attachment=file_bytes,
                            filename=uploaded_file.name
                        ):
                            st.success(f"Сообщение с вложением '{uploaded_file.name}' успешно отправлено!")
                        else:
                            st.error("Ошибка при отправке сообщения с вложением")
                    else:
                        if send_email_with_attachment(
                            to_email=candidate_data['email'],
                            subject=subject,
                            message=message
                        ):
                            st.success("Сообщение успешно отправлено!")
                        else:
                            st.error("Ошибка при отправке сообщения")