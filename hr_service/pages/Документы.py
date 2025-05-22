import streamlit as st
from typing import List, Optional
from pydantic import BaseModel, Field
from repository.database import get_connection

# --- Pydantic модели ---
class Template(BaseModel):
    template_id: int
    name: str
    description: str = Field(default="")
    markdown_instructions: str = Field(default="")
    is_required: bool = True
    processing_days: int = 1
    order_position: int = 1

# --- Операции с БД ---
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

def get_template_by_id(template_id: int) -> Optional[Template]:
    """Получить шаблон по ID"""
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
                WHERE template_id = %s
            """, (template_id,))
            if row := cur.fetchone():
                return Template.model_validate(dict(zip(
                    ['template_id', 'name', 'description', 'markdown_instructions',
                     'is_required', 'processing_days', 'order_position'], row)))
            return None
    finally:
        conn.close()

def add_template(template: Template) -> int:
    """Добавить новый шаблон"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO hr.document_template 
                (name, description, markdown_instructions, is_required, 
                 processing_days, order_position) 
                VALUES (%s, %s, %s, %s, %s, %s) 
                RETURNING template_id
            """, (
                template.name,
                template.description if template.description else None,
                template.markdown_instructions if template.markdown_instructions else None,
                template.is_required,
                template.processing_days,
                template.order_position
            ))
            return cur.fetchone()[0]
    finally:
        conn.commit()
        conn.close()

def update_template(template: Template) -> bool:
    """Обновить существующий шаблон"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE hr.document_template 
                SET 
                    name = %s,
                    description = %s,
                    markdown_instructions = %s,
                    is_required = %s,
                    processing_days = %s,
                    order_position = %s
                WHERE template_id = %s
            """, (
                template.name,
                template.description if template.description else None,
                template.markdown_instructions if template.markdown_instructions else None,
                template.is_required,
                template.processing_days,
                template.order_position,
                template.template_id
            ))
            return cur.rowcount > 0
    finally:
        conn.commit()
        conn.close()

# --- Компоненты интерфейса ---
def render_template_view(template: Template, edit_mode: bool = False):
    """Отображение/редактирование шаблона"""
    if edit_mode:
        with st.form(f"edit_form_{template.template_id}"):
            cols = st.columns(2)
            name = cols[0].text_input("Название*", value=template.name)
            order_pos = cols[1].number_input(
                "Позиция", 
                min_value=1, 
                value=template.order_position
            )
            
            description = st.text_area(
                "Описание", 
                value=template.description,
                height=100
            )
            
            markdown = st.text_area(
                "Инструкция*", 
                value=template.markdown_instructions,
                height=300
            )
            
            cols = st.columns(3)
            is_required = cols[0].checkbox(
                "Обязательный", 
                value=template.is_required
            )
            processing_days = cols[1].number_input(
                "Срок (дни)", 
                min_value=1, 
                value=template.processing_days
            )
            
            submitted = st.form_submit_button("Сохранить изменения")
            if submitted:
                if not name or not markdown:
                    st.error("Заполните обязательные поля (помечены *)")
                else:
                    updated = Template(
                        template_id=template.template_id,
                        name=name,
                        description=description,
                        markdown_instructions=markdown,
                        is_required=is_required,
                        processing_days=processing_days,
                        order_position=order_pos
                    )
                    if update_template(updated):
                        st.success("Шаблон успешно обновлен!")
                        st.rerun()
                    else:
                        st.error("Ошибка при обновлении шаблона")
    else:
        st.header(template.name)
        
        with st.container():
            st.subheader("Описание документа")
            if template.description:
                st.write(template.description)
            else:
                st.info("Описание отсутствует")
            
            st.divider()
            
            st.subheader("Инструкция по заполнению")
            if template.markdown_instructions:
                st.markdown(template.markdown_instructions)
            else:
                st.warning("Инструкция не предоставлена")
            
            st.divider()
            
            cols = st.columns(3)
            cols[0].metric("Обязательный", "✅ Да" if template.is_required else "❌ Нет")
            cols[1].metric("Срок обработки", f"📅 {template.processing_days} дн.")
            cols[2].metric("Позиция", f"🔢 {template.order_position}")

def render_add_template_form():
    """Форма добавления нового шаблона"""
    with st.sidebar.expander("➕ Добавить шаблон", expanded=False):
        with st.form("add_template_form", clear_on_submit=True):
            name = st.text_input("Название документа*", placeholder="Приказ о приеме на работу")
            description = st.text_area("Описание", placeholder="Краткое описание назначения документа")
            markdown_content = st.text_area(
                "Инструкция по заполнению*", 
                placeholder="## Заголовок\n\n* Пункт 1\n* Пункт 2",
                height=200
            )
            
            col1, col2 = st.columns(2)
            with col1:
                is_required = st.checkbox("Обязательный", value=True)
            with col2:
                processing_days = st.number_input("Срок (дни)", min_value=1, value=3)
            
            submitted = st.form_submit_button("Сохранить шаблон")
            
            if submitted:
                if not name or not markdown_content:
                    st.error("Заполните обязательные поля (помечены *)")
                else:
                    try:
                        new_template = Template(
                            template_id=0,
                            name=name,
                            description=description,
                            markdown_instructions=markdown_content,
                            is_required=is_required,
                            processing_days=processing_days,
                            order_position=len(get_all_templates()) + 1
                        )
                        template_id = add_template(new_template)
                        st.success(f"Шаблон '{name}' успешно сохранён (ID: {template_id})")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка при сохранении: {str(e)}")

# --- Основной интерфейс ---
def main():
    st.set_page_config(
        page_title="База шаблонов документов HR",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            'About': "Система управления шаблонами документов v2.0"
        }
    )
    
    st.sidebar.title("📂 Управление шаблонами")
    
    try:
        templates = get_all_templates()
        
        # Get the document from query parameters
        query_params = st.experimental_get_query_params()
        doc_param = query_params.get("doc", [None])[0]
        
        # Set default selected template
        default_index = 0
        
        # If doc parameter is provided, try to find matching template
        if doc_param and templates:
            for i, template in enumerate(templates):
                if template.name == doc_param:
                    default_index = i
                    break
        
        # Выбор документа
        selected_template_name = st.sidebar.selectbox(
            "Выберите документ",
            options=[t.name for t in templates],
            index=default_index if templates else None,
            help="Выберите документ для просмотра"
        )
        
        selected_template = next((t for t in templates if t.name == selected_template_name), None)
        
        # Update URL when selection changes
        if selected_template:
            st.experimental_set_query_params(doc=selected_template.name)
        
        # Rest of your code remains the same...
        col1, col2 = st.sidebar.columns(2)
        if col1.button("🔄 Обновить список"):
            st.rerun()
            
        edit_mode = col2.checkbox("Редактировать", False)
        
        render_add_template_form()
        
        if not templates:
            st.info("В системе пока нет шаблонов документов. Добавьте первый шаблон.")
        elif selected_template:
            render_template_view(selected_template, edit_mode)
            
    except Exception as e:
        st.error(f"Ошибка при загрузке данных: {str(e)}")
        st.stop()

if __name__ == "__main__":
    main()