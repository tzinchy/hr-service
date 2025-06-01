from repository.database import get_connection
import streamlit as st 
import pandas as pd 

def render_employees_page():
    # Заголовок с иконкой
    st.markdown("""
    <style>
        .header {
            font-size: 24px !important;
            font-weight: bold;
            margin-bottom: 20px;
        }
        .card {
            padding: 15px;
            border-radius: 10px;
            border: 1px solid #e1e4e8;
            margin-bottom: 20px;
        }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="header">📋 Список сотрудников</div>', unsafe_allow_html=True)
    
    # Получаем данные
    conn = get_connection()
    
    # Основная таблица сотрудников
    df = pd.read_sql("""
        SELECT 
            u.user_uuid,
            u.first_name || ' ' || u.last_name AS full_name,
            u.email,
            wt.work_type || ' (' || wt.work_range || ')' AS work_schedule,
            wt.notes
        FROM auth."user" u
        LEFT JOIN auth.work_type wt ON u.work_type_id = wt.work_type_id
        ORDER BY u.last_name, u.first_name
    """, conn)

    if df.empty:
        st.info("Нет сотрудников в базе данных")
        return

    # Разделяем на две колонки
    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Все сотрудники")
        
        # Стилизованная таблица
        st.dataframe(
            df[["full_name", "email", "work_schedule"]],
            column_config={
                "full_name": "ФИО",
                "email": "Email",
                "work_schedule": "График работы"
            },
            hide_index=True,
            use_container_width=True,
            height=600
        )

    with col2:
        st.subheader("Изменение графика работы")
        
        # Выбор сотрудника
        selected_user = st.selectbox(
            "Выберите сотрудника:",
            options=df["email"],
            format_func=lambda x: df[df["email"] == x]["full_name"].values[0],
            key="user_select"
        )
        
        if selected_user:
            user_data = df[df["email"] == selected_user].iloc[0]
            
            # Карточка сотрудника
            st.markdown(f"""
            <div class="card">
                <h3>{user_data['full_name']}</h3>
                <p><strong>Email:</strong> {user_data['email']}</p>
                <p><strong>Текущий график:</strong> {user_data['work_schedule']}</p>
                {f"<p><strong>Примечание:</strong> {user_data['notes']}</p>" if user_data['notes'] else ""}
            </div>
            """, unsafe_allow_html=True)
            
            # Получаем варианты work_type
            work_types = pd.read_sql("""
                SELECT work_type_id, work_type || ' | ' || work_range AS label 
                FROM auth.work_type 
                ORDER BY work_type_id
            """, conn)
            
            # Форма изменения
            with st.form(key='change_work_type'):
                new_schedule = st.selectbox(
                    "Новый график работы:",
                    options=work_types['label'],
                    index=0,
                    key="schedule_select"
                )
                
                submit_button = st.form_submit_button("💾 Сохранить изменения")
                
                if submit_button:
                    new_id = work_types[work_types['label'] == new_schedule]['work_type_id'].values[0]
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE auth.user SET work_type_id = %s WHERE user_uuid = %s", 
                            (new_id, user_data['user_uuid'])
                        )
                        conn.commit()
                    
                    st.success("✅ График работы успешно обновлен")
                    st.rerun()