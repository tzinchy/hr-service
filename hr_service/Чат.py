import streamlit as st
import pandas as pd
from datetime import datetime
import logging
from frontend_auth.auth import check_auth, login, logout, admin_required
from core.config import MESSAGE_PREVIEW_LENGTH, CHATS_PER_PAGE
from service.gemini_service import generate_expert_response
from repository.strml_repository import get_all_chats, get_chat_history, save_message
from service.bot_service import send_telegram_message
from repository.database import get_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Константы
MESSAGES_PER_LOAD = 20
MESSAGE_PREVIEW_LENGTH = 50

def get_chat_history_with_offset(chat_id: int, offset: int = 0, limit: int = MESSAGES_PER_LOAD):
    """Получает историю чата с поддержкой offset"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        content,
                        sent_at,
                        is_from_admin
                    FROM comm.message
                    WHERE chat_id = %s
                    ORDER BY sent_at DESC
                    LIMIT %s OFFSET %s
                """, (chat_id, limit, offset))
                return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting chat history: {e}")
        return []

# --- Интерфейс Streamlit ---
def display_chat_preview(candidate):
    """Отображает превью чата с кандидатом"""
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(f"**{candidate['first_name']} {candidate['last_name']}**")
        if candidate["has_unread"]:
            st.markdown(
                "<span style='color: red; font-weight: bold;'>●</span>",
                unsafe_allow_html=True,
            )

    with col2:
        if pd.isna(candidate["last_message"]):
            preview = "Нет сообщений"
        else:
            preview = candidate["last_message"][:MESSAGE_PREVIEW_LENGTH]
            if len(candidate["last_message"]) > MESSAGE_PREVIEW_LENGTH:
                preview += "..."

            if candidate["is_last_from_admin"]:
                preview = f"Вы: {preview}"
            else:
                preview = f"{candidate['first_name']}: {preview}"

        st.markdown(preview)

def display_chat_messages(messages, candidate_name):
    """Отображает полную историю сообщений"""
    if not messages:
        st.info("Сообщений пока нет. Начните диалог!")
        return

    # Отображаем сообщения в обратном порядке (новые внизу)
    for msg in reversed(messages):
        content, sent_at, is_from_admin = msg
        timestamp = sent_at.strftime("%d.%m %H:%M")

        if is_from_admin:
            st.chat_message("human", avatar="👨‍💼").markdown(
                f"**Вы** ({timestamp}):\n{content}"
            )
        else:
            st.chat_message("user", avatar="👤").markdown(
                f"**{candidate_name}** ({timestamp}):\n{content}"
            )

    # Кнопка для подгрузки старых сообщений
    if len(messages) >= MESSAGES_PER_LOAD:
        if st.button("Загрузить предыдущие сообщения"):
            st.session_state.messages_offset += MESSAGES_PER_LOAD
            st.session_state.needs_rerun = True

def initialize_session_state():
    """Инициализирует состояние сессии"""
    if "selected_chat" not in st.session_state:
        st.session_state.selected_chat = None
    if "candidate_name" not in st.session_state:
        st.session_state.candidate_name = ""
    if "last_update" not in st.session_state:
        st.session_state.last_update = datetime.now()
    if "show_ai_assistant" not in st.session_state:
        st.session_state.show_ai_assistant = False
    if "messages_offset" not in st.session_state:
        st.session_state.messages_offset = 0
    if "needs_rerun" not in st.session_state:
        st.session_state.needs_rerun = False

@admin_required
def main():
    st.set_page_config(page_title="Чат с кандидатами", layout="wide")
    st.title("💬 Чат с кандидатами")

    with st.sidebar:
        if st.button("Выйти из системы"):
            logout()

    initialize_session_state()

    # Получаем список всех чатов
    with st.spinner("Загрузка списка чатов..."):
        chats_df = get_all_chats()

    # Разделяем интерфейс на две колонки
    col1, col2 = st.columns([1, 3])

    with col1:
        st.subheader("Все чаты")

        # Поиск по имени
        search_query = st.text_input("Поиск по имени", key="search_input")
        if search_query:
            chats_df = chats_df[
                chats_df["first_name"].str.contains(search_query, case=False)
                | chats_df["last_name"].str.contains(search_query, case=False)
            ]

        # Отображаем список чатов
        if not chats_df.empty:
            for _, candidate in chats_df.iterrows():
                if st.button(
                    f"{candidate['first_name']} {candidate['last_name']}",
                    key=f"chat_{candidate['telegram_chat_id']}",
                    use_container_width=True,
                ):
                    st.session_state.selected_chat = candidate["telegram_chat_id"]
                    st.session_state.candidate_name = (
                        f"{candidate['first_name']} {candidate['last_name']}"
                    )
                    st.session_state.messages_offset = 0
                    st.session_state.last_update = datetime.now()
                    st.session_state.needs_rerun = True

                display_chat_preview(candidate)
                st.divider()
        else:
            st.warning("Нет активных чатов")

    with col2:
        if not st.session_state.selected_chat:
            st.info("Выберите чат слева")
            return

        st.subheader(f"Чат с {st.session_state.candidate_name}")

        # Кнопки управления
        if st.button("🔄 Обновить чат"):
            st.session_state.last_update = datetime.now()
            st.session_state.needs_rerun = True

        if st.button(
            "🤖 AI Ассистент", help="Включить/выключить помощника на основе Gemini"
        ):
            st.session_state.show_ai_assistant = not st.session_state.show_ai_assistant
            st.session_state.needs_rerun = True

        # Контейнер для чата
        chat_container = st.container(height=500, border=True)

        # Получаем историю сообщений
        with chat_container:
            with st.spinner("Загрузка сообщений..."):
                messages = get_chat_history_with_offset(
                    st.session_state.selected_chat,
                    offset=st.session_state.messages_offset
                )
                display_chat_messages(
                    messages, st.session_state.candidate_name.split()[0]
                )

        # Блок AI ассистента
        if st.session_state.show_ai_assistant:
            # Получаем последнее сообщение от кандидата
            last_candidate_message = next(
                (msg[0] for msg in reversed(messages) if not msg[2]), None
            )

            if last_candidate_message:
                with st.expander("🔍 AI Анализ последнего сообщения", expanded=True):
                    st.write("**Последнее сообщение кандидата:**")
                    st.info(last_candidate_message)

                    if st.button(
                        "🎯 Сгенерировать экспертный ответ", key="generate_response"
                    ):
                        with st.spinner("Генерация экспертного ответа..."):
                            expert_response = generate_expert_response(
                                last_candidate_message, messages
                            )
                            st.session_state.generated_response = expert_response

                    if "generated_response" in st.session_state:
                        response = st.text_area(
                            "Экспертный ответ:",
                            value=st.session_state.generated_response,
                            height=200,
                        )

                        if st.button("📤 Отправить этот ответ"):
                            try:
                                with st.spinner("Отправка сообщения..."):
                                    send_telegram_message(
                                        st.session_state.selected_chat,
                                        st.session_state.generated_response,
                                    )
                                    save_message(
                                        st.session_state.selected_chat,
                                        st.session_state.generated_response,
                                        True,
                                    )
                                    st.session_state.last_update = datetime.now()
                                    st.session_state.show_ai_assistant = False
                                    st.session_state.needs_rerun = True
                            except Exception as e:
                                st.error(f"Ошибка при отправке: {str(e)}")
                                logger.error(f"Ошибка отправки сообщения: {e}")
            else:
                st.warning("Нет сообщений от кандидата для анализа")

        # Отправка нового сообщения
        if new_message := st.chat_input("Введите сообщение...", key="message_input"):
            try:
                with st.spinner("Отправка сообщения..."):
                    send_telegram_message(st.session_state.selected_chat, new_message)
                    save_message(st.session_state.selected_chat, new_message, True)
                    st.session_state.last_update = datetime.now()
                    st.session_state.needs_rerun = True
            except Exception as e:
                st.error(f"Ошибка при отправке: {str(e)}")
                logger.error(f"Ошибка отправки сообщения: {e}")

    if st.session_state.needs_rerun:
        st.session_state.needs_rerun = False
        st.rerun()

if __name__ == "__main__":
    #if not check_auth():
        #login()
    #else:
    main()