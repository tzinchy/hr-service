from frontend_auth.auth import get_current_user_data
import streamlit as st 

# Где-то в вашем коде:
user_data = get_current_user_data()
if user_data:
    st.write("Полные данные JWT:")
    st.json(user_data)  # Красивое отображение JSON
    
    # Доступ к конкретным полям:
    st.write(f"User UUID: {user_data.get('user_uuid')}")
    st.write(f"Роли: {user_data.get('roles_ids', [])}")
    st.write(f"Группы: {user_data.get('groups_ids', [])}")