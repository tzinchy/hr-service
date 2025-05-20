import streamlit as st
from typing import List, Optional
from pydantic import BaseModel, Field
from repository.database import get_connection
import urllib.parse

# --- Настройка страницы ---
st.set_page_config(
    page_title="База документов",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Модели ---
class Template(BaseModel):
    template_id: int
    name: str
    description: str = Field(default="")
    markdown_instructions: str = Field(default="")  # Обеспечиваем дефолтное значение
    is_required: bool = True
    order_position: int = 1

    @classmethod
    def from_db_row(cls, row):
        """Создает экземпляр Template из строки БД с обработкой NULL значений"""
        return cls(
            template_id=row[0],
            name=row[1],
            description=row[2] if row[2] is not None else "",
            markdown_instructions=row[3] if row[3] is not None else "",
            is_required=row[4],
            order_position=row[5]
        )

# --- Функции БД ---
def get_all_templates() -> List[Template]:
    """Получает все шаблоны с обработкой NULL значений"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT template_id, name, description, 
                       markdown_instructions, is_required, order_position
                FROM hr.document_template
                ORDER BY order_position
            """)
            return [Template.from_db_row(row) for row in cur.fetchall()]
    finally:
        conn.close()

# --- Интерфейс ---
def show_document(template: Template):
    st.header(template.name)
    st.write(template.description or "Описание отсутствует")
    st.markdown(template.markdown_instructions or "Инструкция не предоставлена")

def get_current_url() -> str:
    """Получает текущий URL без параметров"""
    if 'current_url' not in st.session_state:
        # Для локального запуска
        st.session_state.current_url = "http://localhost:8502"
    return st.session_state.current_url

def update_url(doc_name: str) -> str:
    """Генерирует полную ссылку с параметром doc"""
    base_url = get_current_url().split('?')[0]
    encoded_name = urllib.parse.quote(doc_name.replace(' ', '_'))
    return f"{base_url}?doc={encoded_name}"

def main():
    try:
        templates = get_all_templates()
        
        # Получаем текущий документ из URL
        query_params = st.query_params
        current_doc = query_params.get("doc", [None])[0]
        if current_doc:
            current_doc = current_doc.replace('_', ' ')
        
        # Сайдбар с выбором документа
        st.sidebar.title("📂 Документы")
        selected_doc = st.sidebar.selectbox(
            "Выберите документ",
            options=[t.name for t in templates],
            index=[t.name for t in templates].index(current_doc) 
            if current_doc in [t.name for t in templates] else 0
        )
        
        # Обновляем URL при изменении выбора
        if 'last_selected' not in st.session_state or st.session_state.last_selected != selected_doc:
            st.session_state.last_selected = selected_doc
            st.query_params["doc"] = selected_doc.replace(' ', '_')
            
            # Кнопка копирования
            if st.sidebar.button("📋 Копировать ссылку"):
                st.sidebar.success("Ссылка скопирована в буфер обмена!")
        
        # Отображаем выбранный документ
        selected_template = next(t for t in templates if t.name == selected_doc)
        show_document(selected_template)
        
    except Exception as e:
        st.error(f"Ошибка: {str(e)}")

if __name__ == "__main__":
    main()