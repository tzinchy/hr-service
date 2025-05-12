import streamlit as st
import psycopg2
import os
from datetime import datetime
import uuid
import random
import string
from minio import Minio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Database connection
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "user"),
        password=os.getenv("DB_PASS", "password"),
        database=os.getenv("DB_NAME", "database")
    )

# MinIO connection
def get_minio_client():
    return Minio(
        "localhost:9000",
        access_key=os.getenv("MINIO_USER", "minioadmin"),
        secret_key=os.getenv("MINIO_PASSWORD", "minioadmin"),
        secure=False
    )

# Send email with invitation code
def send_invitation_email(email, invitation_code):
    sender_email = os.getenv("EMAIL_SENDER")
    sender_password = os.getenv("EMAIL_PASSWORD")
    
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = email
    message["Subject"] = "Ваш код доступа к системе"
    
    body = f"""
    <html>
      <body>
        <p>Здравствуйте!</p>
        <p>Вас добавили в систему подбора персонала.</p>
        <p>Ваш код для доступа: <strong>{invitation_code}</strong></p>
        <p>Пожалуйста, используйте этот код для регистрации в системе.</p>
      </body>
    </html>
    """
    
    message.attach(MIMEText(body, "html"))
    
    with smtplib.SMTP(os.getenv("EMAIL_SERVER"), int(os.getenv("EMAIL_PORT"))) as server:
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(message)

# Create MinIO folder for candidate
def create_candidate_folder(minio_client, candidate_uuid):
    bucket_name = "candidates"
    folder_name = f"{candidate_uuid}/"
    
    try:
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
        
        # Create folder by uploading empty object
        minio_client.put_object(
            bucket_name,
            folder_name
        )
    except Exception as e:
        st.error(f"Ошибка при создании папки в MinIO: {str(e)}")

# Add candidate to database
def add_candidate(first_name, last_name, email):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        
        # Insert candidate
        cur.execute(
            """
            INSERT INTO hr.candidate (
                candidate_uuid, first_name, last_name, email, 
                status_id, invitation_code, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING hr.candidate_uuid
            """,
            (
                first_name,
                last_name,
                email,
                1, 
            )
        )
        result = cur.execute()
        # Create folder in MinIO
        minio_client = get_minio_client()
        create_candidate_folder(minio_client, )
        
        # Send invitation email
        send_invitation_email(email, invitation_code)
        
        conn.commit()
        return candidate_uuid, invitation_code
        
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

# Streamlit UI
def main():
    st.set_page_config(page_title="Добавление кандидата", layout="wide")
    st.title("Добавление нового кандидата")
    
    with st.form("candidate_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            first_name = st.text_input("Имя*", max_chars=255)
        
        with col2:
            last_name = st.text_input("Фамилия*", max_chars=255)
        
        email = st.text_input("Email*", max_chars=255)
        
        submitted = st.form_submit_button("Добавить кандидата")
        
        if submitted:
            if not all([first_name, last_name, email]):
                st.error("Пожалуйста, заполните все обязательные поля (помечены *)")
            else:
                try:
                    invitation_code = add_candidate(
                        first_name, last_name, email
                    )
                    
                    st.success("Кандидат успешно добавлен!")
                    st.info(f"""
                    Код приглашения: {invitation_code}
                    Код был отправлен на email: {email}
                    """)
                    
                except Exception as e:
                    st.error(f"Ошибка при добавлении кандидата: {str(e)}")

if __name__ == "__main__":
    main()