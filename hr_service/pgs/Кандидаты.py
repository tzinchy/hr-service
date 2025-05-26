import streamlit as st
import pandas as pd
import textwrap
import logging
import google.generativeai as genai
from repository.database import get_connection, get_minio_client
from frontend_auth.auth import check_auth, get_current_user_data, login
from service.email_service import send_email, send_telegram_notification, send_invitation_email
from repository.strml_repository import add_candidate_to_db
from core.config import GEMINI_API_KEY

# --- Конфигурация приложения ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
ADMIN_ROLE_ID = 1 

# --- Константы ---
DOCUMENT_STATUSES = {
    1: ("Не загружен", "❌", "#FF5252"),
    2: ("Заказан", "🛒", "#FFD740"),
    3: ("Ожидает проверки", "⏳", "#64B5F6"),
    4: ("Проверен", "✅", "#4CAF50"),
    5: ("Отправьте заново", "🔄", "#FF9800")
}

CANDIDATE_STATUSES = {
    2: ("Приглашен", "✉️"),
    3: ("Зарегистрирован", "📝"),
    5: ("Документы на проверке", "🔍"),
    7: ("Принят", "✅"),
    8: ("Отклонен", "❌")
}

FINAL_STATUSES = [7, 8]  # Статусы, после которых изменения невозможны

ALLOWED_DOCUMENT_STATUS_CHANGES = {
    3: [4, 5]
}

ALLOWED_CANDIDATE_STATUS_CHANGES = {
    5: [7, 8]  # Из "Документы на проверке" можно перейти в "Принят" или "Отклонен"
}

STATUS_DESCRIPTIONS = {
    7: "Поздравляем! Вы успешно прошли отбор и приняты в нашу команду.",
    8: "К сожалению, по результатам рассмотрения ваших документов мы не можем продолжить сотрудничество."
}

CANDIDATE_ANALYSIS_PROMPT = "Вы - HR-эксперт. Кратко проанализируйте кандидата."

# --- Инициализация AI ---
genai.configure(api_key=GEMINI_API_KEY)
ai_model = genai.GenerativeModel("gemini-1.5-flash")

# --- Функции базы данных ---
def get_candidate_statuses():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT status_id, name FROM hr.candidate_status ORDER BY status_id")
            return cursor.fetchall()

def get_candidates_list(tutor_uuid, is_admin, status_filter=None, search_query=None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            params = []
            
            base_select = """
                SELECT 
                    c.candidate_uuid, c.first_name, c.last_name, c.email,
                    cs.status_id, cs.name as status, c.notes as candidate_notes,
                    COUNT(d.document_id) as total_docs
                FROM hr.candidate c
                JOIN hr.candidate_status cs ON c.status_id = cs.status_id
                LEFT JOIN hr.candidate_document d ON c.candidate_uuid = d.candidate_id
                WHERE 1=1
            """

            if not is_admin:
                base_select += " AND c.tutor_uuid = %s"
                params.append(tutor_uuid)

            if status_filter:
                base_select += " AND cs.status_id = %s"
                params.append(status_filter)

            if search_query:
                base_select += " AND (LOWER(c.first_name) LIKE %s OR LOWER(c.last_name) LIKE %s)"
                params.extend([f"%{search_query.lower()}%", f"%{search_query.lower()}%"])
            
            base_select += """
                GROUP BY c.candidate_uuid, c.first_name, c.last_name, c.email, cs.status_id, cs.name, c.notes
                ORDER BY c.last_name, c.first_name
            """

            cursor.execute(base_select, params)
            return pd.DataFrame(cursor.fetchall(), columns=[desc[0] for desc in cursor.description])

def get_candidate_details(candidate_uuid):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    c.*, 
                    cs.name as status_name,
                    u.first_name as tutor_first_name,
                    u.last_name as tutor_last_name
                FROM hr.candidate c
                JOIN hr.candidate_status cs ON c.status_id = cs.status_id
                LEFT JOIN auth.user u ON c.tutor_uuid = u.user_uuid
                WHERE c.candidate_uuid = %s
            """, (candidate_uuid,))
            
            columns = [desc[0] for desc in cursor.description]
            row = cursor.fetchone()
            
            if row:
                return dict(zip(columns, row))
            return None

def get_candidate_documents(candidate_uuid):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    d.document_id, t.name as document_type, d.s3_bucket, d.s3_key,
                    d.file_size, d.content_type, d.submitted_at, d.status_id, d.notes as document_notes
                FROM hr.candidate_document d
                JOIN hr.document_template t ON d.template_id = t.template_id
                WHERE d.candidate_id = %s
                ORDER BY t.order_position
            """, (candidate_uuid,))
            return pd.DataFrame(cursor.fetchall(), columns=[desc[0] for desc in cursor.description])

def update_document_status(document_id, new_status_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE hr.candidate_document SET status_id = %s WHERE document_id = %s
            """, (new_status_id, document_id))
            conn.commit()

def update_candidate_status(candidate_uuid, new_status_id):
    """Обновляем статус кандидата с отправкой уведомлений"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Получаем текущие данные кандидата
            cursor.execute("""
                SELECT first_name, last_name, email, status_id, telegram_chat_id
                FROM hr.candidate 
                WHERE candidate_uuid = %s
            """, (candidate_uuid,))
            candidate_data = cursor.fetchone()
            
            if not candidate_data:
                raise ValueError("Кандидат не найден")
            
            current_status = candidate_data[3]
            if current_status in FINAL_STATUSES:
                raise ValueError("Финальный статус уже установлен")
            
            # Обновляем статус
            cursor.execute("""
                UPDATE hr.candidate SET status_id = %s WHERE candidate_uuid = %s
            """, (new_status_id, candidate_uuid))
            
            # Отправляем уведомления для финальных статусов
            if new_status_id in FINAL_STATUSES:
                send_status_notifications(
                    first_name=candidate_data[0],
                    last_name=candidate_data[1],
                    email=candidate_data[2],
                    telegram_chat_id=candidate_data[4],
                    status_id=new_status_id
                )
            
            conn.commit()

def send_status_notifications(first_name, last_name, email, telegram_chat_id, status_id):
    """Отправляем уведомления на почту и в Telegram"""
    status_name, status_icon = CANDIDATE_STATUSES[status_id]
    status_desc = STATUS_DESCRIPTIONS[status_id]
    
    # Формируем сообщение
    message = f"""
    Уважаемый(ая) {first_name} {last_name},
    
    Ваш статус был изменен на: {status_icon} {status_name}
    
    {status_desc}
    """
    
    # Отправка на почту
    try:
        send_email(
            to_email=email,
            subject=f"Обновление статуса: {status_name}",
            message=message
        )
        logger.info(f"Email уведомление отправлено на {email}")
    except Exception as e:
        logger.error(f"Ошибка отправки email: {str(e)}")
    
    # Отправка в Telegram
    if telegram_chat_id:
        try:
            send_telegram_notification(
                chat_id=telegram_chat_id,
                message=message
            )
            logger.info(f"Telegram уведомление отправлено для chat_id {telegram_chat_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки Telegram: {str(e)}")

def update_candidate_notes(candidate_uuid, notes):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE hr.candidate SET notes = %s WHERE candidate_uuid = %s
            """, (notes, candidate_uuid))
            conn.commit()

def update_document_notes(document_id, notes):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE hr.candidate_document SET notes = %s WHERE document_id = %s
            """, (notes, document_id))
            conn.commit()

def download_from_minio(bucket, key):
    try:
        if not bucket or not key:
            return None
        minio_client = get_minio_client()
        response = minio_client.get_object(bucket, key)
        file_data = response.read()
        response.close()
        return file_data
    except Exception as e:
        st.error(f"Ошибка загрузки: {str(e)}")
        return None

# --- AI Функции ---
def generate_compact_analysis(candidate, documents):
    """
    Генерирует краткий аналитический отчет о кандидате с использованием AI
    
    Args:
        candidate (dict): Данные кандидата
        documents (DataFrame): Документы кандидата
        
    Returns:
        str: Сформированный анализ кандидата
    """
    try:
        # Получаем статус кандидата
        status_info = CANDIDATE_STATUSES.get(candidate['status_id'], ("Неизвестно", "❓"))
        status_name = status_info[0]
        status_icon = status_info[1]
        
        # Анализируем документы
        docs_summary = {
            "completed": len(documents[documents['status_id'] == 4]),
            "pending_review": len(documents[documents['status_id'] == 3]),
            "needs_resubmit": len(documents[documents['status_id'] == 5]),
            "ordered": len(documents[documents['status_id'] == 2]),
            "missing": len(documents[documents['status_id'] == 1])
        }
        
        # Формируем детальный промпт для AI
        prompt = f"""
        Ты - HR-аналитик в крупной компании. Проанализируй кандидата и предоставь краткий отчет.
        
        ### Основная информация:
        - Кандидат: {candidate['first_name']} {candidate['last_name']}
        - Текущий статус: {status_icon} {status_name}
        - Контакты: {candidate.get('email', 'нет email')} | {candidate.get('phone', 'нет телефона')}
        - Куратор: {candidate.get('tutor_first_name', '')} {candidate.get('tutor_last_name', '')}
        - Заметки: {textwrap.shorten(candidate.get('notes', 'нет заметок'), width=150, placeholder='...')}
        
        ### Статистика документов:
        - ✅ Проверено и одобрено: {docs_summary['completed']}
        - 🔍 Ожидают проверки: {docs_summary['pending_review']}
        - 🔄 Требуют перезагрузки: {docs_summary['needs_resubmit']}
        - 🛒 Заказаны: {docs_summary['ordered']}
        - ❌ Отсутствуют: {docs_summary['missing']}
        - 📋 Всего документов: {len(documents)}
        
        ### Задание:
        1. Оцените текущий прогресс кандидата по документам
        2. Выделите потенциальные проблемы или задержки
        3. Дайте рекомендации по дальнейшим действиям
        4. Будь кратким (3-5 предложений) и конкретным
        5. Используй профессиональный, но дружелюбный тон
        
        Формат вывода:
        [Анализ прогресса] [Проблемы] [Рекомендации]
        """
        
        # Получаем ответ от AI
        response = ai_model.generate_content(prompt)
        return response.text
    
    except Exception as e:
        logger.error(f"Ошибка AI анализа: {str(e)}")
        return "Не удалось сгенерировать анализ. Пожалуйста, проверьте данные кандидата вручную."

# --- Компоненты интерфейса ---
def show_status_badge(status_id):
    status = DOCUMENT_STATUSES.get(status_id, ("Неизвестно", "❓", "#9E9E9E"))
    st.markdown(
        f'<div style="background-color:{status[2]}20; border-radius:6px; padding:4px 8px; '
        f'display:inline-flex; align-items:center; border-left:3px solid {status[2]}; margin:2px;">'
        f'<div style="font-size:14px;">{status[1]} {status[0]}</div></div>',
        unsafe_allow_html=True
    )

def show_candidate_status_badge(status_id):
    """
    Красиво отображает статус кандидата с иконкой и цветовой индикацией
    
    Args:
        status_id (int): ID статуса кандидата
    """
    # Цветовая схема для разных статусов
    STATUS_COLORS = {
        2: ("#2196F3", "#E3F2FD"),  # Приглашен (синий)
        3: ("#4CAF50", "#E8F5E9"),  # Зарегистрирован (зеленый)
        5: ("#FF9800", "#FFF3E0"),  # Документы на проверке (оранжевый)
        7: ("#2E7D32", "#E8F5E9"),  # Принят (темно-зеленый)
        8: ("#D32F2F", "#FFEBEE")   # Отклонен (красный)
    }
    
    status = CANDIDATE_STATUSES.get(status_id, ("Неизвестно", "❓"))
    color, bg_color = STATUS_COLORS.get(status_id, ("#9E9E9E", "#FAFAFA"))
    
    st.markdown(
        f"""
        <div style="
            background-color: {bg_color};
            color: {color};
            border-radius: 12px;
            padding: 10px 15px;
            border-left: 5px solid {color};
            display: inline-flex;
            align-items: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin: 5px 0;
            font-size: 16px;
            font-weight: 600;
        ">
            <span style="font-size: 20px; margin-right: 10px;">{status[1]}</span>
            <span>{status[0]}</span>
        </div>
        """,
        unsafe_allow_html=True
    )

def show_document_card(doc, is_admin=False):
    with st.container(border=True):
        cols = st.columns([1, 3])
        
        with cols[0]:
            show_status_badge(doc['status_id'])
            
        with cols[1]:
            st.markdown(f"**{doc['document_type']}**")
            st.caption(f"🗓️ {doc.get('submitted_at', 'нет даты')} | 📦 {doc.get('file_size', 'нет данных')}")
            
            # Заметки документа
            doc_notes = st.text_area(
                "Заметки",
                value=doc.get('document_notes', ''),
                height=70,
                key=f"doc_notes_{doc['document_id']}",
                label_visibility="collapsed"
            )
            
            # Действия с документом
            action_cols = st.columns([1, 1, 2])
            
            with action_cols[0]:
                # Скачивание
                if doc['status_id'] not in [1, 2] and doc['s3_key']:
                    if st.button(
                        "⬇️ Скачать",
                        key=f"dl_{doc['document_id']}",
                        use_container_width=True
                    ):
                        file_data = download_from_minio(doc['s3_bucket'], doc['s3_key'])
                        if file_data:
                            st.download_button(
                                "Скачать сейчас",
                                file_data,
                                doc['s3_key'].split('/')[-1],
                                doc['content_type'],
                                key=f"dl_btn_{doc['document_id']}"
                            )
            
            with action_cols[1]:
                # Изменение статуса документа
                if doc['status_id'] in ALLOWED_DOCUMENT_STATUS_CHANGES and is_admin:
                    new_status = st.selectbox(
                        "Изменить статус",
                        [DOCUMENT_STATUSES[s][0] for s in ALLOWED_DOCUMENT_STATUS_CHANGES[doc['status_id']]],
                        key=f"status_{doc['document_id']}",
                        label_visibility="collapsed"
                    )
            
            with action_cols[2]:
                if st.button(
                    "💾 Сохранить",
                    key=f"save_doc_{doc['document_id']}",
                    use_container_width=True
                ):
                    if doc['status_id'] in ALLOWED_DOCUMENT_STATUS_CHANGES and is_admin:
                        new_id = next(k for k, v in DOCUMENT_STATUSES.items() if v[0] == new_status)
                        update_document_status(doc['document_id'], new_id)
                    update_document_notes(doc['document_id'], doc_notes)
                    st.rerun()

def show_candidate_details_view(candidate_uuid):
    candidate = get_candidate_details(candidate_uuid)
    documents = get_candidate_documents(candidate_uuid)
    
    user_data = get_current_user_data()
    is_admin = user_data and 1 in user_data.get('roles_ids', [])
    
    # Хлебные крошки для навигации
    if st.button("← Назад к списку кандидатов"):
        if 'selected_candidate' in st.session_state:
            del st.session_state['selected_candidate']
        st.rerun()
    
    st.markdown(f"# {candidate['first_name']} {candidate['last_name']}")
    
    # Основная информация о кандидате
    with st.container(border=True):
        cols = st.columns([1, 1, 2])
        
        with cols[0]:
            st.markdown("### Основная информация")
            st.markdown(f"📧 **Email:** {candidate['email']}")
            st.markdown(f"📞 **Телефон:** {candidate.get('phone', 'не указан')}")
            st.markdown(f"👤 **Куратор:** {candidate.get('tutor_first_name', '')} {candidate.get('tutor_last_name', '')}")
        
        with cols[1]:
            st.markdown("### Статус")
            show_candidate_status_badge(candidate['status_id'])
            
            # Изменение статуса кандидата (для админов)
            if is_admin and candidate['status_id'] in ALLOWED_CANDIDATE_STATUS_CHANGES:
                new_status_name = st.selectbox(
                    "Изменить статус кандидата",
                    [CANDIDATE_STATUSES[s][0] for s in ALLOWED_CANDIDATE_STATUS_CHANGES[candidate['status_id']]],
                    key=f"candidate_status_{candidate['candidate_uuid']}"
                )
                
                if st.button("Применить статус", key=f"apply_status_{candidate['candidate_uuid']}"):
                    try:
                        new_status_id = [k for k, v in CANDIDATE_STATUSES.items() if v[0] == new_status_name][0]
                        update_candidate_status(candidate['candidate_uuid'], new_status_id)
                        st.success("Статус обновлен! Уведомления отправлены.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка: {str(e)}")
        
        with cols[2]:
            st.markdown("### Заметки")
            notes = st.text_area(
                "Редактировать заметки о кандидате",
                value=candidate.get('notes', ''),
                height=100,
                key=f"candidate_notes_{candidate['candidate_uuid']}"
            )
            
            if st.button("Сохранить заметки", key=f"save_notes_{candidate['candidate_uuid']}"):
                update_candidate_notes(candidate['candidate_uuid'], notes)
                st.rerun()
    
    # AI анализ кандидата
    with st.expander("🔍 AI Анализ кандидата", expanded=False):
        with st.spinner("Анализируем данные кандидата..."):
            analysis = generate_compact_analysis(candidate, documents)
            st.markdown(analysis)
    
    # Документы кандидата
    st.markdown("## 📄 Документы кандидата")
    
    # Фильтры документов
    with st.expander("🔍 Фильтры документов", expanded=False):
        cols = st.columns(2)
        with cols[0]:
            search_query = st.text_input("Поиск по названию документа")
        with cols[1]:
            status_filter = st.selectbox(
                "Статус документа", 
                ["Все"] + [s[0] for s in DOCUMENT_STATUSES.values()]
            )
    
    # Применяем фильтры
    if search_query:
        documents = documents[documents['document_type'].str.contains(search_query, case=False)]
    if status_filter != "Все":
        status_id = next(k for k, v in DOCUMENT_STATUSES.items() if v[0] == status_filter)
        documents = documents[documents['status_id'] == status_id]
    
    # Статистика документов
    st.markdown("### Статистика документов")
    cols = st.columns(len(DOCUMENT_STATUSES))
    for idx, (status_id, (name, icon, color)) in enumerate(DOCUMENT_STATUSES.items()):
        with cols[idx]:
            count = len(documents[documents['status_id'] == status_id])
            st.markdown(
                f'<div style="background-color:{color}20; border-radius:6px; padding:6px; '
                f'text-align:center; border-left:3px solid {color}; margin:2px;">'
                f'<div style="font-size:14px;">{icon} {count}</div>'
                f'<div style="font-size:11px;">{name}</div></div>',
                unsafe_allow_html=True
            )
    
    # Список документов
    st.markdown("### Список документов")
    for _, doc in documents.iterrows():
        show_document_card(doc, is_admin)

# --- Главная страница (список кандидатов) ---
def show_candidates_list():
    st.title("👥 Список кандидатов")
    
    # Добавление нового кандидата
    if st.button("➕ Добавить кандидата", use_container_width=True):
        st.session_state['show_add_form'] = True
    
    if st.session_state.get('show_add_form', False):
        with st.form("add_form"):
            st.subheader("Новый кандидат")
            
            cols = st.columns(2)
            with cols[0]:
                first_name = st.text_input("Имя*")
            with cols[1]:
                last_name = st.text_input("Фамилия*")
            
            email = st.text_input("Email*")
            sex = st.selectbox("Пол", ["Мужской", "Женский"])
            notes = st.text_area("Заметки")
            
            cols = st.columns(2)
            with cols[0]:
                if st.form_submit_button("Добавить", type="primary"):
                    if not first_name or not last_name or not email:
                        st.error("Заполните обязательные поля")
                    else:
                        try:
                            user_data = get_current_user_data()
                            candidate_uuid, code = add_candidate_to_db(
                                first_name=first_name,
                                last_name=last_name,
                                email=email,
                                sex=sex == "Мужской",
                                tutor_id=user_data['user_uuid'],
                                notes=notes
                            )
                            send_invitation_email(email, code)
                            st.success("Кандидат добавлен!")
                            st.session_state['show_add_form'] = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка: {str(e)}")
            
            with cols[1]:
                if st.form_submit_button("Отмена"):
                    st.session_state['show_add_form'] = False
                    st.rerun()
        return
    
    # Фильтры
    with st.expander("🔍 Фильтры", expanded=True):
        cols = st.columns(2)
        with cols[0]:
            search = st.text_input("Поиск по имени")
        with cols[1]:
            status = st.selectbox(
                "Статус кандидата", 
                ["Все"] + [s for s in get_candidate_statuses()],
                format_func=lambda x: x[1] if x != "Все" else x
            )
    
    user_data = get_current_user_data()
    is_admin = ADMIN_ROLE_ID in user_data.get('roles_ids', [])
    tutor_uuid = user_data.get('user_uuid') if not is_admin else None
    
    # Список кандидатов
    candidates = get_candidates_list(
        tutor_uuid=tutor_uuid,
        is_admin=is_admin,
        status_filter=status[0] if status != "Все" else None,
        search_query=search if search else None
    )

    if candidates.empty:
        st.info("Кандидаты не найдены")
        return
    
    # Отображение списка кандидатов
    for _, candidate in candidates.iterrows():
        with st.container(border=True):
            cols = st.columns([1, 3, 1])
            
            with cols[0]:
                status_name, status_icon = CANDIDATE_STATUSES.get(candidate['status_id'], ("Неизвестно", "❓"))
                st.markdown(f"### {status_icon}")
            
            with cols[1]:
                st.markdown(f"**{candidate['last_name']} {candidate['first_name']}**")
                st.caption(f"📧 {candidate['email']}")
                
                # Статистика документов
                if candidate['total_docs'] > 0:
                    doc_cols = st.columns(len(DOCUMENT_STATUSES))
                    for idx, (status_id, (_, icon, color)) in enumerate(DOCUMENT_STATUSES.items()):
                        with doc_cols[idx]:
                            count = candidate.get(f"status_{status_id}", 0)
                            if count > 0:
                                st.markdown(
                                    f'<div style="color:{color}; text-align:center;">{icon} {count}</div>',
                                    unsafe_allow_html=True
                                )
            
            with cols[2]:
                if st.button(
                    "Открыть профиль",
                    key=f"open_{candidate['candidate_uuid']}",
                    use_container_width=True
                ):
                    st.session_state['selected_candidate'] = candidate['candidate_uuid']
                    st.rerun()

# --- Точка входа ---
def candidates():
    if not check_auth():
        login()
        return
    
    user_data = get_current_user_data()
    if not user_data:
        st.error("Ошибка загрузки данных")
        return
    
    if not set(user_data.get('roles_ids', [])).intersection({1, 2, 3}):
        st.error("Недостаточно прав")
        return
    
    if 'selected_candidate' in st.session_state:
        show_candidate_details_view(st.session_state['selected_candidate'])
    else:
        show_candidates_list()

