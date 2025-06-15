import streamlit as st
from frontend_auth.auth import check_auth, login, ADMIN_ROLE, HR_ROLE, logout
from pgs.Дашборд import dash
from pgs.Документы import docs 
from pgs.Кандидаты import candidates 
from pgs.Чат import chat
from pgs.Архив import render_archived_candidates_page
from pgs.Сотрудники import render_employees_page
# Должно быть ПЕРВОЙ и ЕДИНСТВЕННОЙ командой set_page_config во всем приложении
st.set_page_config(
    layout="wide",
    page_title="HR Portal",
    page_icon="👔",
    initial_sidebar_state="expanded"
)

# 1. Проверка авторизации
if not check_auth():
    login()
    st.stop()

# 2. Создаем навигационное меню
def get_available_pages():
    """Возвращает список доступных страниц"""
    pages = ["👥 Кандидаты", "📄 Чат"]  # Базовая страница для всех
    
    user_data = st.session_state.auth.get('user')
    if user_data:
        if ADMIN_ROLE in user_data.roles_ids:
            pages.insert(0, "📊 Дашборд")
            pages.insert(3, "📄 Документы")
            pages.insert(4, '📁Архив')
            pages.insert(5, '📋Сотрудники')

    
    return pages

# 3. Отображаем только доступные страницы
available_pages = get_available_pages()
if not available_pages:
    st.error("У вас нет доступа ни к одной странице")
    st.stop()

page = st.sidebar.selectbox("Меню", available_pages)
with st.sidebar:
    if st.button("Выйти из системы"):
        logout()
# 4. Динамическая загрузка страниц (без импорта в начале файла!)
if page == "📊 Дашборд":
    dash()
elif page == "📄 Документы":
    docs()
elif page == '📄 Чат':
    chat()
elif page == 'Архив':
    render_archived_candidates_page()
elif page == 'Сотрудники':
    render_employees_page()
else:
    candidates()