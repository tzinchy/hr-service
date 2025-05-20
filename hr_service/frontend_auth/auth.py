import streamlit as st
import requests
import jwt
from datetime import datetime, timedelta
from functools import wraps
from typing import List, Optional
import os

# Настройки из вашего бэкенда
ALGORITHM = os.getenv("ALGORITHM", "HS256")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_API_URL = "http://auth:8001/v1/auth"

class UserTokenData:
    """Модель данных пользователя из токена"""
    def __init__(self, **kwargs):
        self.user_uuid = kwargs.get('user_uuid', '')
        self.roles_ids = kwargs.get('roles_ids', []) or []
        self.groups_ids = kwargs.get('groups_ids', []) or []
        self.positions_ids = kwargs.get('positions_ids', []) or []
        self.district_ids = kwargs.get('district_ids', []) or []
        self.district_group_id = kwargs.get('district_group_id')

def init_auth_session():
    """Инициализация сессии аутентификации"""
    if 'auth' not in st.session_state:
        st.session_state.auth = {
            'token': None,
            'user': None,
            'last_check': None
        }

def decode_token(token: str) -> Optional[UserTokenData]:
    """Декодирование JWT токена"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return UserTokenData(**payload)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

def check_auth() -> bool:
    """Проверка авторизации пользователя (аналог is_authenticated)"""
    init_auth_session()
    
    if not st.session_state.auth.get('token'):
        return False
        
    # Проверяем срок действия токена каждые 5 минут
    if not st.session_state.auth.get('last_check') or \
       (datetime.now() - st.session_state.auth['last_check']) > timedelta(minutes=5):
        user_data = decode_token(st.session_state.auth['token'])
        if not user_data:
            logout()
            return False
        st.session_state.auth['user'] = user_data
        st.session_state.auth['last_check'] = datetime.now()
    
    return True

def login():
    """Форма входа"""
    init_auth_session()
    
    with st.form("auth_form"):
        st.header("Авторизация")
        login_or_email = st.text_input("Логин или email")
        password = st.text_input("Пароль", type="password")
        
        if st.form_submit_button("Войти"):
            try:
                response = requests.post(
                    f"{BASE_API_URL}/login",
                    json={"login_or_email": login_or_email, "password": password},
                    timeout=5
                )
                
                if response.status_code == 200:
                    auth_token = response.cookies.get("AuthToken")
                    if auth_token:
                        st.session_state.auth.update({
                            'token': auth_token,
                            'user': decode_token(auth_token),
                            'last_check': datetime.now()
                        })
                        st.rerun()
                    else:
                        st.error("Токен не получен")
                else:
                    st.error(f"Ошибка авторизации: {response.json().get('detail', 'Неизвестная ошибка')}")
            except requests.exceptions.RequestException as e:
                st.error(f"Ошибка соединения: {str(e)}")

def logout():
    """Выход из системы"""
    init_auth_session()
    st.session_state.auth = {
        'token': None,
        'user': None,
        'last_check': None
    }
    st.rerun()

def auth_required(
    required_roles: Optional[List[int]] = None,
    required_groups: Optional[List[int]] = None,
    required_positions: Optional[List[int]] = None
):
    """Декоратор для проверки авторизации и прав"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not check_auth():
                login()
                st.stop()
            
            user_data = st.session_state.auth.get('user')
            if not user_data:
                logout()
                st.stop()
            
            # Безопасная проверка ролей
            if required_roles:
                user_roles = getattr(user_data, 'roles_ids', [])
                if not any(role in user_roles for role in required_roles):
                    st.error(f"Требуются роли: {required_roles}")
                    st.stop()
            
            # Безопасная проверка групп
            if required_groups:
                user_groups = getattr(user_data, 'groups_ids', [])
                if not any(group in user_groups for group in required_groups):
                    st.error(f"Требуются группы: {required_groups}")
                    st.stop()
            
            # Безопасная проверка позиций
            if required_positions:
                user_positions = getattr(user_data, 'positions_ids', [])
                if not any(pos in user_positions for pos in required_positions):
                    st.error(f"Требуются позиции: {required_positions}")
                    st.stop()
            
            return func(*args, **kwargs)
        return wrapper
    return decorator

# Специализированные декораторы (сохраняем оригинальные названия)
def admin_required(func):
    return auth_required(required_roles=[1])(func)

def hr_admin_required(func):
    return auth_required(required_roles=[2])(func)

def hr_user_required(func):
    return auth_required(required_roles=[3])(func)

def hr_candidate_required(func):
    return auth_required(required_roles=[4])(func)

def test_requiered(func):
    return auth_required(required_groups=[3])(func)

def get_current_user_data() -> Optional[dict]:
    """Получение всех данных из JWT токена"""
    init_auth_session()
    
    if not st.session_state.auth.get('token'):
        return None
    
    try:
        # Декодируем токен без проверки подписи (только для просмотра)
        decoded = jwt.decode(
            st.session_state.auth['token'],
            options={"verify_signature": False}
        )
        return decoded
    except jwt.PyJWTError as e:
        st.error(f"Ошибка декодирования токена: {str(e)}")
        return None
    
# Явно указываем какие функции экспортируем
__all__ = [
    'check_auth',
    'hr_user_required',
    'login',
    'logout',
    'admin_required',
    'hr_admin_required',
    'hr_candidate_required'
]