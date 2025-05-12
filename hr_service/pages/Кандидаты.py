import streamlit as st
import pandas as pd
from candidate.database import get_connection, get_minio_client
from frontend_auth.auth import check_auth, get_current_user_data

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
                    SUM(CASE WHEN d.status_id = 5 THEN 1 ELSE 0 END) as status_5
                FROM hr.candidate c
                JOIN hr.candidate_status cs ON c.status_id = cs.status_id
                LEFT JOIN hr.candidate_document d ON c.candidate_uuid = d.candidate_id
            """
            
            if status_filter:
                base_query += f" WHERE cs.status_id = {status_filter}"
            
            base_query += """
                GROUP BY c.candidate_uuid, c.first_name, c.last_name, c.email, cs.name, cs.status_id
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
                    d.status_id
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
    st.subheader(f"📂 Документы: {candidate['last_name']} {candidate['first_name']}")
    
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
                        new_status_options = [DOCUMENT_STATUSES[status][0] for status in ALLOWED_STATUS_CHANGES[status_id]]
                        new_status_name = st.selectbox(
                            "Изменить статус на:",
                            options=new_status_options,
                            key=f"status_select_{doc['document_id']}"
                        )
                        
                        if st.button("Подтвердить изменение",
                                   key=f"confirm_{doc['document_id']}",
                                   type="primary"):
                            new_status_id = [k for k, v in DOCUMENT_STATUSES.items() if v[0] == new_status_name][0]
                            update_document_status(doc['document_id'], new_status_id)
                            st.rerun()

# --- Главная страница ---
def candidates_page():
    """Страница управления кандидатами"""
    st.title("👥 Кандидаты")
    
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