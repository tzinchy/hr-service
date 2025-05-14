import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from candidate.database import get_connection
from core.config import settings
from aiogram import Bot
import asyncio
import logging
import google.generativeai as genai
from frontend_auth.auth import check_auth, login, logout, admin_required, hr_admin_required, hr_user_required, test_requiered
from candidate.tg_service import save_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


POLLING_INTERVAL = 2  
MESSAGE_PREVIEW_LENGTH = 20  
GEMINI_API_KEY = settings.gemini.GEMINI_TOKEN 

# Инициализация Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash-exp')

# Системный промт для экспертного поведения
EXPERT_PROMPT = """
Ты - HR-эксперт высочайшего уровня с 20-летним опытом в подборе персонала. 
Твои ответы должны быть:
- Максимально профессиональными и точными
- Содержать экспертные инсайты
- Быть дружелюбными, но сохранять дистанцию
- Использовать профессиональную лексику
- Давать четкие и структурированные ответы
- Учитывать контекст предыдущих сообщений

Всегда отвечай как HR-гуру, к мнению которого прислушиваются. 
Твои ответы должны демонстрировать глубочайшее понимание HR-процессов.
Ты должен отвечать от первого лица не объясняя, что и как
"""

# --- Функции работы с данными ---

def generate_expert_response(prompt: str, chat_history: list) -> str:
    """
    Генерирует экспертный ответ на основе истории чата
    """
    try:
        # Формируем контекст из истории сообщений
        context = EXPERT_PROMPT + "\n\nКонтекст беседы:\n"
        for msg in chat_history[-5:]:  # Берем последние 5 сообщений для контекста
            role = "HR" if msg[2] else "Кандидат"
            context += f"{role}: {msg[0]}\n"
        
        full_prompt = f"{context}\nЭкспертный ответ HR на последнее сообщение кандидата:\n{prompt}"
        
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        logger.error(f"Ошибка генерации ответа Gemini: {e}")
        return "Извините, возникла ошибка при генерации ответа."

def get_all_chats_cached():
    """Получает кэшированный список всех чатов"""
    return get_all_chats()

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

def get_chat_history_cached(chat_id: int):
    """Кэшированная версия получения истории чата"""
    return get_chat_history(chat_id)

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

def send_telegram_message(chat_id: int, text: str):
    """Отправляет сообщение через aiogram"""
    async def async_send():
        bot = Bot(token=settings.bot.TELEGRAM_TOKEN)
        try:
            await bot.send_message(chat_id=int(chat_id), text=text)
            logger.info(f"Сообщение отправлено в чат {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения: {e}")
            raise
        finally:
            await bot.session.close()
    
    asyncio.run(async_send())

def check_new_messages(chat_id: int, last_check: datetime):
    """Проверяет наличие новых сообщений через поллинг БД"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM comm.message 
                        WHERE chat_id = %s 
                        AND NOT is_from_admin 
                        AND sent_at > %s
                    )
                """, (chat_id, last_check))
                return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Ошибка при проверке новых сообщений: {e}")
        return False

# --- Интерфейс Streamlit ---

def display_chat_preview(candidate):
    """Отображает превью чата с кандидатом"""
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(f"**{candidate['first_name']} {candidate['last_name']}**")
        if candidate['has_unread']:
            st.markdown("<span style='color: red; font-weight: bold;'>●</span>", unsafe_allow_html=True)
    
    with col2:
        if pd.isna(candidate['last_message']):
            preview = "Нет сообщений"
        else:
            preview = candidate['last_message'][:MESSAGE_PREVIEW_LENGTH] 
            if len(candidate['last_message']) > MESSAGE_PREVIEW_LENGTH:
                preview += "..."
            
            if candidate['is_last_from_admin']:
                preview = f"Вы: {preview}"
            else:
                preview = f"{candidate['first_name']}: {preview}"
        
        st.markdown(preview)

def display_chat_messages(messages, candidate_name):
    """Отображает полную историю сообщений"""
    if not messages:
        st.info("Сообщений пока нет. Начните диалог!")
        return
    
    for msg in messages:
        content, sent_at, is_from_admin = msg
        timestamp = sent_at.strftime('%d.%m %H:%M')
        
        if is_from_admin:
            st.chat_message("human", avatar="👨‍💼").markdown(
                f"**Вы** ({timestamp}):\n{content}"
            )
        else:
            st.chat_message("user", avatar="👤").markdown(
                f"**{candidate_name}** ({timestamp}):\n{content}"
            )

def initialize_session_state():
    """Инициализирует состояние сессии"""
    if 'selected_chat' not in st.session_state:
        st.session_state.selected_chat = None
    if 'candidate_name' not in st.session_state:
        st.session_state.candidate_name = ""
    if 'last_update' not in st.session_state:
        st.session_state.last_update = datetime.now()
    if 'last_message_check' not in st.session_state:
        st.session_state.last_message_check = datetime.now()
    if 'show_ai_assistant' not in st.session_state:
        st.session_state.show_ai_assistant = False

@admin_required
def main():
    st.set_page_config(page_title="Чат с кандидатами", layout="wide")
    st.title("💬 Чат с кандидатами")
    
    # Добавляем кнопку выхода в сайдбар
    with st.sidebar:
        if st.button("Выйти из системы"):
            logout()
    
    initialize_session_state()
    
    # Получаем список всех чатов
    with st.spinner("Загрузка списка чатов..."):
        chats_df = get_all_chats_cached()
    
    # Разделяем интерфейс на две колонки
    col1, col2 = st.columns([1, 3])

    with col1:
        st.subheader("Все чаты")
        
        # Поиск по имени
        search_query = st.text_input("Поиск по имени", key="search_input")
        if search_query:
            chats_df = chats_df[
                chats_df['first_name'].str.contains(search_query, case=False) | 
                chats_df['last_name'].str.contains(search_query, case=False)
            ]
        
        # Отображаем список чатов
        if not chats_df.empty:
            for _, candidate in chats_df.iterrows():
                if st.button(
                    f"{candidate['first_name']} {candidate['last_name']}",
                    key=f"chat_{candidate['telegram_chat_id']}",
                    use_container_width=True
                ):
                    st.session_state.selected_chat = candidate['telegram_chat_id']
                    st.session_state.candidate_name = f"{candidate['first_name']} {candidate['last_name']}"
                    st.session_state.last_update = datetime.now()
                    st.rerun()
                
                display_chat_preview(candidate)
                st.divider()
        else:
            st.warning("Нет активных чатов")

    with col2:
        if not st.session_state.selected_chat:
            st.info("Выберите чат слева")
            return
        
        st.subheader(f"Чат с {st.session_state.candidate_name}")
        
        # Кнопка для включения/выключения AI ассистента
        if st.button("🤖 AI Ассистент", help="Включить/выключить помощника на основе Gemini"):
            st.session_state.show_ai_assistant = not st.session_state.show_ai_assistant
        
        # Проверка новых сообщений
        if (datetime.now() - st.session_state.last_message_check).seconds > POLLING_INTERVAL:
            if check_new_messages(st.session_state.selected_chat, st.session_state.last_update):
                st.session_state.last_update = datetime.now()
                st.rerun()
            st.session_state.last_message_check = datetime.now()
        
        # Контейнер для чата
        chat_container = st.container(height=500, border=True)
        
        # Получаем историю сообщений
        with chat_container:
            with st.spinner("Загрузка сообщений..."):
                messages = get_chat_history_cached(st.session_state.selected_chat)
                display_chat_messages(messages, st.session_state.candidate_name.split()[0])
        
        # Блок AI ассистента
        if st.session_state.show_ai_assistant:
            # Получаем последнее сообщение от кандидата
            last_candidate_message = next(
                (msg[0] for msg in reversed(messages) if not msg[2]), 
                None
            )
            
            if last_candidate_message:
                with st.expander("🔍 AI Анализ последнего сообщения"):
                    st.write("**Последнее сообщение кандидата:**")
                    st.info(last_candidate_message)
                    
                    if st.button("🎯 Сгенерировать экспертный ответ", key="generate_response"):
                        with st.spinner("Генерация экспертного ответа..."):
                            expert_response = generate_expert_response(
                                last_candidate_message,
                                messages
                            )
                            st.session_state.generated_response = expert_response
                    
                    if 'generated_response' in st.session_state:
                        st.text_area("Экспертный ответ:", 
                                    value=st.session_state.generated_response,
                                    height=200)
                        
                        if st.button("📤 Отправить этот ответ"):
                            try:
                                with st.spinner("Отправка сообщения..."):
                                    send_telegram_message(st.session_state.selected_chat, st.session_state.generated_response)
                                    save_message(st.session_state.selected_chat, st.session_state.generated_response, True)
                                    st.session_state.last_update = datetime.now()
                                    st.session_state.show_ai_assistant = False
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Ошибка при отправке: {str(e)}")
                                logger.error(f"Ошибка отправки сообщения: {e}")
            else:
                st.warning("Нет сообщений от кандидата для анализа")
        
        # Отправка нового сообщения
        new_message = st.chat_input("Введите сообщение...", key="message_input")
        if new_message:
            try:
                with st.spinner("Отправка сообщения..."):
                    send_telegram_message(st.session_state.selected_chat, new_message)
                    save_message(st.session_state.selected_chat, new_message, True)
                    st.session_state.last_update = datetime.now()
                    st.rerun()
            except Exception as e:
                st.error(f"Ошибка при отправке: {str(e)}")
                logger.error(f"Ошибка отправки сообщения: {e}")

    # Автообновление при долгом бездействии
    if (datetime.now() - st.session_state.last_update).seconds > 1:
        st.session_state.last_update = datetime.now()
        st.rerun()

if __name__ == "__main__":
    # Проверяем аутентификацию перед запуском основного кода
    if not check_auth():
        login()
    else:
        main()