import streamlit as st
import pandas as pd
from repository.database import get_connection, get_minio_client
from frontend_auth.auth import check_auth, get_current_user_data
from service.email_service import send_invitation_email
from repository.strml_repository import add_candidate_to_db

# Настройки страницы
st.set_page_config(layout="wide")

# Статусы документов
DOCUMENT_STATUSES = {
    1: ("Не загружен", "❌", "#FF5252"),
    2: ("Заказан", "🛒", "#FFD740"),
    3: ("Ожидает проверки", "⏳", "#64B5F6"),
    4: ("Проверен", "✅", "#4CAF50"),
    5: ("Отправьте заново", "🔄", "#FF9800")
}

# Разрешенные изменения статусов (только на эти статусы можно менять)
ALLOWED_STATUS_CHANGES = {
    3: [4, 5],  # "Ожидает проверки" -> "Проверен" или "Отправьте заново"
    5: [3]      # "Отправьте заново" -> "Ожидает проверки"
}

# --- Функции базы данных ---
def get_candidates_list(status_filter=None):
    """Получаем список всех кандидатов со статистикой по документам"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            base_query = """
                SELECT 
                    c.candidate_uuid, 
                    c.first_name, 
                    c.last_name, 
                    c.email,
                    cs.name as status,
                    cs.status_id as status_id,
                    COUNT(d.document_id) as total_docs,
                    SUM(CASE WHEN d.status_id = 1 THEN 1 ELSE 0 END) as status_1,
                    SUM(CASE WHEN d.status_id = 2 THEN 1 ELSE 0 END) as status_2,
                    SUM(CASE WHEN d.status_id = 3 THEN 1 ELSE 0 END) as status_3,
                    SUM(CASE WHEN d.status_id = 4 THEN 1 ELSE 0 END) as status_4,
                    SUM(CASE WHEN d.status_id = 5 THEN 1 ELSE 0 END) as status_5,
                    c.notes as candidate_notes
                FROM hr.candidate c
                JOIN hr.candidate_status cs ON c.status_id = cs.status_id
                LEFT JOIN hr.candidate_document d ON c.candidate_uuid = d.candidate_id
            """
            
            if status_filter:
                base_query += f" WHERE cs.status_id = {status_filter}"
            
            base_query += """
                GROUP BY c.candidate_uuid, c.first_name, c.last_name, c.email, cs.name, cs.status_id, c.notes
                ORDER BY c.last_name, c.first_name
            """
            
            cursor.execute(base_query)
            columns = [desc[0] for desc in cursor.description]
            return pd.DataFrame(cursor.fetchall(), columns=columns)

def get_candidate_documents(candidate_uuid):
    """Получаем документы кандидата со статусами"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    d.document_id,
                    t.name as document_type,
                    d.s3_bucket,
                    d.s3_key,
                    d.file_size,
                    d.content_type,
                    d.submitted_at,
                    d.status_id,
                    d.notes as document_notes
                FROM hr.candidate_document d
                JOIN hr.document_template t ON d.template_id = t.template_id
                WHERE d.candidate_id = %s
                ORDER BY t.order_position
            """, (candidate_uuid,))
            columns = [desc[0] for desc in cursor.description]
            return pd.DataFrame(cursor.fetchall(), columns=columns)

def update_document_status(document_id, new_status_id):
    """Обновляем статус документа"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE hr.candidate_document
                SET status_id = %s
                WHERE document_id = %s
            """, (new_status_id, document_id))
            conn.commit()

def update_candidate_notes(candidate_uuid, notes):
    """Обновляем заметки по кандидату"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE hr.candidate
                SET notes = %s
                WHERE candidate_uuid = %s
            """, (notes, candidate_uuid))
            conn.commit()

def update_document_notes(document_id, notes):
    """Обновляем заметки по документу"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE hr.candidate_document
                SET notes = %s
                WHERE document_id = %s
            """, (notes, document_id))
            conn.commit()

def download_from_minio(bucket, key):
    """Скачиваем файл из MinIO"""
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

# --- Компоненты интерфейса ---
def show_status_badges(status_counts):
    """Отображаем статусы документов в виде бейджей"""
    cols = st.columns(len(DOCUMENT_STATUSES))
    for idx, (status_id, (status_name, icon, color)) in enumerate(DOCUMENT_STATUSES.items()):
        count = status_counts.get(f"status_{status_id}", 0)
        with cols[idx]:
            st.markdown(
                f'<div style="background-color:{color}20; border-radius:6px; padding:8px; text-align:center; border-left:3px solid {color}">'
                f'<div style="font-size:16px; display:flex; justify-content:center; align-items:center; gap:4px;">'
                f'{icon} <span>{count}</span>'
                '</div>'
                f'<div style="font-size:12px;">{status_name}</div>'
                '</div>',
                unsafe_allow_html=True
            )

def show_candidate_documents(candidate):
    """Показываем документы кандидата в правой панели с прокруткой"""
    # Фильтры документов
    col1, col2 = st.columns(2)
    with col1:
        doc_search = st.text_input("🔍 Поиск по названию", key=f"search_{candidate['candidate_uuid']}")
    with col2:
        selected_status = st.selectbox(
            "Фильтр по статусу",
            options=["Все"] + [status[0] for status in DOCUMENT_STATUSES.values()],
            key=f"status_filter_{candidate['candidate_uuid']}"
        )
    
    documents_df = get_candidate_documents(candidate['candidate_uuid'])
    if documents_df.empty:
        st.info("Нет загруженных документов")
        return
    
    # Фильтрация документов
    if doc_search:
        mask = documents_df['document_type'].str.contains(doc_search, case=False)
        documents_df = documents_df[mask]
    
    if selected_status != "Все":
        status_id = [k for k, v in DOCUMENT_STATUSES.items() if v[0] == selected_status][0]
        documents_df = documents_df[documents_df['status_id'] == status_id]
    
    # Статистика по статусам
    status_counts = {f"status_{status_id}": len(documents_df[documents_df['status_id'] == status_id]) 
                    for status_id in DOCUMENT_STATUSES}
    
    # Показываем сводку по статусам
    show_status_badges(status_counts)
    
    # Заметки по кандидату
    with st.expander("📝 Заметки по кандидату"):
        notes = st.text_area(
            "Редактировать заметки",
            value=candidate.get('candidate_notes', ''),
            key=f"candidate_notes_{candidate['candidate_uuid']}",
            height=100  # Изменено с 50 на 100 (минимально допустимое - 68)
        )
        if st.button("Сохранить заметки", key=f"save_candidate_notes_{candidate['candidate_uuid']}"):
            update_candidate_notes(candidate['candidate_uuid'], notes)
            st.success("Заметки сохранены!")
            st.rerun()
    
    # Контейнер с прокруткой для документов
    with st.container(height=500):  # Фиксированная высота с прокруткой
        for _, doc in documents_df.iterrows():
            status_id = doc['status_id']
            status_name, status_icon, status_color = DOCUMENT_STATUSES.get(status_id, ("Неизвестно", "❓", "#9E9E9E"))
            
            with st.container(border=True):
                # Информация о документе
                cols = st.columns([4, 2])
                with cols[0]:
                    date_str = doc['submitted_at'].strftime('%d.%m.%Y') if pd.notna(doc['submitted_at']) else "нет даты"
                    file_size = f"{doc['file_size']/1024:.1f} KB" if pd.notna(doc['file_size']) else "неизвестно"
                    
                    st.markdown(f"**{doc['document_type']}**")
                    st.caption(f"🗓️ {date_str} | 📦 {file_size}")
                    st.markdown(f"{status_icon} **{status_name}**")
                    
                    # Заметки по документу
                    with st.expander("📝 Заметки"):
                        doc_notes = st.text_area(
                            "Редактировать заметки",
                            value=doc.get('document_notes', ''),
                            key=f"doc_notes_{doc['document_id']}",
                            height=70  # Изменено с 50 на 70 (минимально допустимое - 68)
                        )
                        if st.button("Сохранить", key=f"save_doc_notes_{doc['document_id']}"):
                            update_document_notes(doc['document_id'], doc_notes)
                            st.success("Заметки сохранены!")
                            st.rerun()
                
                # Управление документом
                with cols[1]:
                    # Кнопка скачивания (только для загруженных документов)
                    if status_id not in [1, 2] and doc['s3_key']:  # Не показываем для "Не загружен" и "Заказан"
                        if st.button("⬇️ Скачать документ", 
                                   key=f"dl_btn_{doc['document_id']}",
                                   use_container_width=True):
                            file_data = download_from_minio(doc['s3_bucket'], doc['s3_key'])
                            if file_data:
                                file_name = doc['s3_key'].split('/')[-1]
                                st.download_button(
                                    label="Скачать сейчас",
                                    data=file_data,
                                    file_name=file_name,
                                    mime=doc['content_type'],
                                    key=f"dl_{doc['document_id']}"
                                )
                    
                    # Изменение статуса (только для разрешенных статусов)
                    if status_id in ALLOWED_STATUS_CHANGES:
                        # Получаем доступные статусы для изменения
                        allowed_new_statuses = ALLOWED_STATUS_CHANGES[status_id]
                        new_status_options = [DOCUMENT_STATUSES[status][0] for status in allowed_new_statuses]
                        
                        # Выбираем первый доступный статус по умолчанию
                        default_idx = 0
                        if status_id == 5:  # Если текущий статус "Отправьте заново", выбираем "Ожидает проверки"
                            default_idx = new_status_options.index(DOCUMENT_STATUSES[3][0])
                        
                        new_status_name = st.selectbox(
                            "Изменить статус на:",
                            options=new_status_options,
                            index=default_idx,
                            key=f"status_select_{doc['document_id']}"
                        )
                        
                        if st.button("Подтвердить изменение",
                                   key=f"confirm_{doc['document_id']}",
                                   type="primary"):
                            new_status_id = [k for k, v in DOCUMENT_STATUSES.items() if v[0] == new_status_name][0]
                            
                            # Дополнительная проверка разрешенных изменений
                            if new_status_id in ALLOWED_STATUS_CHANGES.get(status_id, []):
                                update_document_status(doc['document_id'], new_status_id)
                                st.success("Статус успешно обновлен!")
                                st.rerun()
                            else:
                                st.error("Недопустимое изменение статуса!")

def show_add_candidate_form():
    """Форма добавления нового кандидата"""
    with st.form("add_candidate_form", clear_on_submit=True):
        st.subheader("Добавить нового кандидата")
        
        col1, col2 = st.columns(2)
        with col1:
            first_name = st.text_input("Имя*", max_chars=50)
        with col2:
            last_name = st.text_input("Фамилия*", max_chars=50)
        
        email = st.text_input("Email*", max_chars=100)
        sex = st.selectbox("Пол", options=["Мужской", "Женский"], index=0)
        notes = st.text_area("Заметки", height=100)
        
        submitted = st.form_submit_button("Добавить кандидата")
        
        if submitted:
            if not first_name or not last_name or not email:
                st.error("Пожалуйста, заполните обязательные поля (помечены *)")
            else:
                try:
                    # Получаем текущего пользователя (куратора)
                    user_data = get_current_user_data()
                    if not user_data or 'user_uuid' not in user_data:
                        st.error("Не удалось получить данные текущего пользователя")
                        return
                    
                    # Преобразуем пол в булево значение
                    sex_bool = sex == "Мужской"
                    
                    # Добавляем кандидата
                    user_uuid, invitation_code = add_candidate_to_db(
                        first_name=first_name,
                        last_name=last_name,
                        email=email,
                        sex=sex_bool,
                        tutor_id=user_data['user_uuid'],  # Доступ к user_uuid как к ключу словаря
                        notes=notes
                    )
                    
                    # Отправляем приглашение
                    send_invitation_email(email, invitation_code)
                    
                    st.success(f"Кандидат успешно добавлен! Приглашение отправлено на {email}")
                    st.session_state['show_add_candidate_form'] = False
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка при добавлении кандидата: {str(e)}")

# --- Главная страница ---
def candidates_page():
    """Страница управления кандидатами"""
    st.title("👥 Кандидаты")
    
    # Кнопка для добавления нового кандидата
    if st.button("➕ Добавить кандидата"):
        st.session_state['show_add_candidate_form'] = True
    
    # Показываем форму добавления кандидата если нужно
    if st.session_state.get('show_add_candidate_form', False):
        show_add_candidate_form()
        if st.button("Отмена"):
            st.session_state['show_add_candidate_form'] = False
            st.rerun()
        return
    
    # Фильтры в одну строку
    filter_col1, filter_col2 = st.columns([3, 2])
    with filter_col1:
        search_query = st.text_input("🔍 Поиск по имени", placeholder="Введите имя или фамилию")
    with filter_col2:
        status_filter = st.selectbox(
            "Фильтр по статусу кандидата",
            options=["Все"] + [status for status in get_candidate_statuses()],
            format_func=lambda x: x[1] if x != "Все" else x,
            key="candidate_status_filter"
        )
    
    # Загрузка кандидатов с учетом фильтра
    status_id_filter = status_filter[0] if status_filter != "Все" else None
    candidates_df = get_candidates_list(status_id_filter)
    
    if candidates_df.empty:
        st.info("Нет данных о кандидатах")
        return
    
    # Дополнительная фильтрация по имени
    if search_query:
        mask = (candidates_df['first_name'].str.contains(search_query, case=False) | 
               candidates_df['last_name'].str.contains(search_query, case=False))
        candidates_df = candidates_df[mask]
    
    # Основные колонки с фиксированными пропорциями
    col_left, col_right = st.columns([2, 1], gap="large")
    
    with col_left:
        st.subheader("Список кандидатов")
        # Контейнер с фиксированной высотой и прокруткой
        with st.container(height=600):  # Фиксированная высота с прокруткой
            # Отображение карточек кандидатов
            for _, candidate in candidates_df.iterrows():
                with st.container(border=True):
                    # Собираем статистику по статусам
                    status_counts = {
                        f"status_{status_id}": candidate.get(f"status_{status_id}", 0)
                        for status_id in DOCUMENT_STATUSES
                    }
                    
                    # Основная информация о кандидате
                    st.markdown(f"### {candidate['last_name']} {candidate['first_name']}")
                    st.write(f"**Статус кандидата:** {candidate['status']}")
                    st.write(f"**Email:** {candidate['email']}")
                    
                    # Краткая сводка по документам
                    if candidate['total_docs'] > 0:
                        st.markdown("---")
                        st.write("**Статусы документов:**")
                        show_status_badges(status_counts)
                    
                    # Кнопка для показа документов
                    if st.button("Показать документы", 
                               key=f"btn_{candidate['candidate_uuid']}",
                               use_container_width=True):
                        st.session_state['selected_candidate'] = candidate
    
    with col_right:
        # Правый сайдбар с документами и скроллом
        if 'selected_candidate' in st.session_state:
            show_candidate_documents(st.session_state['selected_candidate'])
        else:
            st.info("Выберите кандидата для просмотра документов")

# Дополнительные функции
def get_candidate_statuses():
    """Получаем список возможных статусов кандидатов"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT status_id, name FROM hr.candidate_status ORDER BY status_id")
            return cursor.fetchall()

# --- Аутентификация и запуск ---
def main():
    if not check_auth():
        st.warning("Требуется авторизация")
        return
    
    user_data = get_current_user_data()
    if not user_data:
        st.error("Ошибка загрузки данных пользователя")
        return
    
    if not set(user_data.get('roles_ids', [])).intersection({1, 2, 3}):
        st.error("Недостаточно прав доступа")
        return
    
    candidates_page()

if __name__ == "__main__":
    main()