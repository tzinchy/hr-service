import streamlit as st
import pandas as pd
from datetime import datetime
import logging
from frontend_auth.auth import check_auth, login, logout, get_current_user_data
from core.config import MESSAGE_PREVIEW_LENGTH
from service.gemini_service import generate_expert_response
from repository.strml_repository import get_all_chats, save_message
from service.bot_service import send_telegram_message
from typing import Optional
from repository.database import get_connection
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Константы
MESSAGES_PER_LOAD = 20
ADMIN_ROLE_ID = 1
HR_ROLE_ID = 3

def get_chat_history_with_offset(chat_id: int, offset: int = 0, limit: int = MESSAGES_PER_LOAD):
    """Получает историю чата с поддержкой пагинации"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT content, sent_at, is_from_admin
                    FROM comm.message
                    WHERE chat_id = %s
                    ORDER BY sent_at DESC
                    LIMIT %s OFFSET %s
                """, (chat_id, limit, offset))
                return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting chat history: {e}")
        return []

def display_chat_preview(candidate):
    """Отображает превью чата с кандидатом"""
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(f"**{candidate['first_name']} {candidate['last_name']}**")
        if candidate["has_unread"]:
            st.markdown("<span style='color: red; font-weight: bold;'>●</span>", unsafe_allow_html=True)

    with col2:
        preview = "Нет сообщений" if pd.isna(candidate["last_message"]) else \
                  f"{'Вы' if candidate['is_last_from_admin'] else candidate['first_name']}: " \
                  f"{candidate['last_message'][:MESSAGE_PREVIEW_LENGTH]}{'...' if len(candidate['last_message']) > MESSAGE_PREVIEW_LENGTH else ''}"
        st.markdown(preview)

def display_chat_messages(messages, candidate_name):
    """Отображает полную историю сообщений"""
    if not messages:
        st.info("Сообщений пока нет. Начните диалог!")
        return

    for msg in reversed(messages):
        content, sent_at, is_from_admin = msg
        avatar = "👨‍💼" if is_from_admin else "👤"
        author = "Вы" if is_from_admin else candidate_name
        timestamp = sent_at.strftime("%d.%m %H:%M")
        
        with st.chat_message("human" if is_from_admin else "user", avatar=avatar):
            st.markdown(f"**{author}** ({timestamp}):\n{content}")

    if len(messages) >= MESSAGES_PER_LOAD:
        if st.button("Загрузить предыдущие сообщения"):
            st.session_state.messages_offset += MESSAGES_PER_LOAD
            st.rerun()

def initialize_session_state():
    """Инициализирует состояние сессии"""
    defaults = {
        'selected_chat': None,
        'candidate_name': "",
        'last_update': datetime.now(),
        'show_ai_assistant': False,
        'messages_offset': 0,
        'needs_rerun': False
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def main():
    st.set_page_config(page_title="Чат с кандидатами", layout="wide")
    st.title("💬 Чат с кандидатами")

    # Получаем данные пользователя
    # Получаем данные пользователя через вашу функцию
    user_data = get_current_user_data()
    if not user_data:
        logout()
        st.stop()

    # Проверяем роли
    is_admin = ADMIN_ROLE_ID in user_data.get('roles_ids')
    print(user_data)
    print(user_data.get('roles_ids'))
    tutor_id = user_data.get('user_uuid') if not is_admin else None
    print(is_admin)
    print(tutor_id)
    print(st.session_state)

    with st.sidebar:
        if st.button("Выйти из системы"):
            logout()

    initialize_session_state()

    # Загрузка данных
    with st.spinner("Загрузка списка чатов..."):
        chats_df = get_all_chats(tutor_id=tutor_id, role=ADMIN_ROLE_ID if is_admin else HR_ROLE_ID)

    # Разделение интерфейса
    col1, col2 = st.columns([1, 3])

    with col1:
        st.subheader("Все чаты")
        search_query = st.text_input("Поиск по имени", key="search_input")
        
        if search_query:
            chats_df = chats_df[chats_df.apply(lambda x: 
                search_query.lower() in f"{x['first_name']} {x['last_name']}".lower(), axis=1)]

        if not chats_df.empty:
            for _, candidate in chats_df.iterrows():
                btn_key = f"chat_{candidate['telegram_chat_id']}"
                if st.button(f"{candidate['first_name']} {candidate['last_name']}", key=btn_key, use_container_width=True):
                    st.session_state.update({
                        'selected_chat': candidate["telegram_chat_id"],
                        'candidate_name': f"{candidate['first_name']} {candidate['last_name']}",
                        'messages_offset': 0,
                        'last_update': datetime.now(),
                        'needs_rerun': True
                    })
                display_chat_preview(candidate)
                st.divider()
        else:
            st.warning("Нет активных чатов")

    with col2:
        if not st.session_state.selected_chat:
            st.info("Выберите чат слева")
            return

        st.subheader(f"Чат с {st.session_state.candidate_name}")
        
        # Панель управления чатом
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("🔄 Обновить чат"):
                st.session_state.last_update = datetime.now()
                st.rerun()
        with col_btn2:
            if st.button("🤖 AI Ассистент", help="Включить/выключить помощника"):
                st.session_state.show_ai_assistant = not st.session_state.show_ai_assistant
                st.rerun()

        # История сообщений
        with st.container(height=500, border=True):
            with st.spinner("Загрузка сообщений..."):
                messages = get_chat_history_with_offset(
                    st.session_state.selected_chat,
                    offset=st.session_state.messages_offset
                )
                display_chat_messages(messages, st.session_state.candidate_name.split()[0])

        # Блок AI ассистента
        if st.session_state.show_ai_assistant:
            last_candidate_message = next((msg[0] for msg in reversed(messages) if not msg[2]), None)
            
            if last_candidate_message:
                with st.expander("🔍 AI Анализ последнего сообщения", expanded=True):
                    st.write("**Последнее сообщение кандидата:**")
                    st.info(last_candidate_message)
                    
                    if st.button("🎯 Сгенерировать ответ"):
                        with st.spinner("Генерация ответа..."):
                            expert_response = generate_expert_response(last_candidate_message, messages)
                            st.session_state.generated_response = expert_response
                    
                    if "generated_response" in st.session_state:
                        response = st.text_area("Ответ:", value=st.session_state.generated_response, height=200)
                        if st.button("📤 Отправить"):
                            try:
                                send_telegram_message(st.session_state.selected_chat, response)
                                save_message(st.session_state.selected_chat, response, True)
                                st.session_state.update({
                                    'last_update': datetime.now(),
                                    'show_ai_assistant': False
                                })
                                st.rerun()
                            except Exception as e:
                                st.error(f"Ошибка: {str(e)}")
                                logger.error(f"Ошибка отправки: {e}")

        # Отправка новых сообщений
        if new_message := st.chat_input("Введите сообщение..."):
            try:
                send_telegram_message(st.session_state.selected_chat, new_message)
                save_message(st.session_state.selected_chat, new_message, True)
                st.session_state.last_update = datetime.now()
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка: {str(e)}")
                logger.error(f"Ошибка отправки: {e}")

if __name__ == "__main__":
    if not check_auth():
        check_auth()
        login()
    else:
        main()