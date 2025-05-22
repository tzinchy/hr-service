import streamlit as st
from typing import List, Optional
from pydantic import BaseModel, Field
from urllib.parse import quote, unquote
from repository.database import get_connection
import warnings

# Подавляем предупреждения
warnings.filterwarnings("ignore", category=DeprecationWarning)

class Template(BaseModel):
    template_id: int
    name: str
    description: str = Field(default="")
    markdown_instructions: str = Field(default="")
    is_required: bool = True
    processing_days: int = 1
    order_position: int = 1

def get_all_templates() -> List[Template]:
    """Получить все шаблоны документов"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    template_id, 
                    name, 
                    COALESCE(description, '') as description,
                    COALESCE(markdown_instructions, '') as markdown_instructions,
                    is_required, 
                    processing_days, 
                    order_position 
                FROM hr.document_template 
                ORDER BY order_position
            """)
            return [Template.model_validate(dict(zip(
                ['template_id', 'name', 'description', 'markdown_instructions',
                 'is_required', 'processing_days', 'order_position'], row)))
                for row in cur.fetchall()]
    finally:
        conn.close()

def show_template(template: Template):
    """Отображает шаблон в Streamlit"""
    st.header(template.name)
    st.subheader("Описание")
    st.write(template.description if template.description else "Нет описания")
    st.subheader("Инструкция по заполнению")
    st.markdown(template.markdown_instructions if template.markdown_instructions else "Инструкция не указана")
    st.divider()
    cols = st.columns(3)
    cols[0].metric("Обязательный", "✅ Да" if template.is_required else "❌ Нет")
    cols[1].metric("Срок обработки", f"{template.processing_days} дней")
    cols[2].metric("Позиция в списке", template.order_position)

def main():
    st.set_page_config(
        page_title="База шаблонов документов HR",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.sidebar.title("📂 Управление шаблонами")
    
    try:
        templates = get_all_templates()
        
        # Получаем параметр из URL
        requested_doc = unquote(st.query_params.get("doc", "")) if "doc" in st.query_params else None
        
        # Находим шаблон по названию из URL
        selected_template = next((t for t in templates if t.name == requested_doc), None) if requested_doc else None
        
        # Выбор документа в сайдбаре
        selected_name = st.sidebar.selectbox(
            "Выберите документ",
            options=[t.name for t in templates],
            index=0 if not selected_template else [t.name for t in templates].index(selected_template.name)
        )
        
        # Обновляем URL при выборе
        if selected_name:
            st.query_params["doc"] = quote(selected_name)
            selected_template = next((t for t in templates if t.name == selected_name), None)
        
        # Показываем шаблон
        if not templates:
            st.info("Нет доступных шаблонов.")
        elif selected_template:
            show_template(selected_template)
            
    except Exception as e:
        st.error(f"Ошибка: {str(e)}")

if __name__ == "__main__":
    main()