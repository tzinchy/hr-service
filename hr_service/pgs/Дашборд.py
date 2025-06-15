import streamlit as st
import pandas as pd
import plotly.express as px
import pydeck as pdk
from datetime import datetime, timedelta
from repository.dashboard_repository import (
    get_df_locations,
    get_pending_docs,
    get_documents_by_type,
    get_documents_by_type_by_status,
    get_employees_by_department,
    get_candidates_by_status,
    get_document_processing_times
)
from frontend_auth.auth import check_auth, login, admin_required

# Конфигурация кэширования
@st.cache_data(ttl=3600, show_spinner="Загружаем данные о локациях...")
def get_cached_locations():
    df = get_df_locations()
    return df.rename(columns={
        'name': 'ФИО',
        'email': 'Email',
        'type': 'Тип',
        'work_type_display': 'Режим работы'
    })

@st.cache_data(ttl=600, show_spinner="Загружаем документы на рассмотрении...")
def get_cached_pending_docs():
    df = get_pending_docs()
    return df.rename(columns={
        'candidate_employee': 'Кандидат/Сотрудник',
        'doc_type': 'Тип документа',
        'submitted_at': 'Дата подачи',
        'status': 'Статус',
        'last_updated': 'Обновлено'
    })

@st.cache_data(ttl=600, show_spinner="Анализируем документы по типам...")
def get_cached_documents_by_type():
    df = get_documents_by_type()
    return df.rename(columns={
        'doc_type': 'Тип документа',
        'count': 'Количество'
    })

@st.cache_data(ttl=600, show_spinner="Анализируем статусы документов...")
def get_cached_documents_by_status():
    df = get_documents_by_type_by_status()
    return df.rename(columns={
        'status': 'Статус',
        'count': 'Количество'
    })

@st.cache_data(ttl=600, show_spinner="Загружаем данные по департаментам...")
def get_cached_employees_by_dept():
    df = get_employees_by_department()
    return df.rename(columns={
        'department': 'Департамент',
        'count': 'Сотрудников'
    })

@st.cache_data(ttl=600, show_spinner="Анализируем статусы кандидатов...")
def get_cached_candidates_by_status():
    df = get_candidates_by_status()
    return df.rename(columns={
        'status': 'Статус',
        'count': 'Количество'
    })

@st.cache_data(ttl=600, show_spinner="Вычисляем сроки обработки документов...")
def get_cached_doc_processing_times():
    df = get_document_processing_times()
    return df.rename(columns={
        'doc_type': 'Тип документа',
        'avg_days': 'Средний срок (дни)'
    })

def setup_sidebar_filters():
    st.sidebar.title("Фильтры")
    
    date_range = st.sidebar.date_input(
        "Период",
        value=[datetime.now() - timedelta(days=30), datetime.now()],
        max_value=datetime.now()
    )
    
    work_type_filter = st.sidebar.selectbox(
        "Режим работы",
        options=["Все", "Удаленно", "Офис", "Гибрид"],
        index=0
    )

    return date_range, work_type_filter

def create_color_mapping(row):
    """Создаем цветовую схему для карты"""
    if row['Тип'] == 'candidate':
        return [255, 0, 0, 200]  # Красный для кандидатов
    elif row['work_type_id'] in [3, 4]:  # Офис
        return [0, 100, 255, 200]  # Синий для офиса
    elif row['work_type_id'] in [5, 6]:  # Гибрид
        return [50, 200, 100, 200]  # Зеленый для гибрида
    else:  # Удаленка
        return [255, 165, 0, 200]  # Оранжевый

@admin_required
def render_locations_tab(work_type_filter):
    try:
        st.header("📍 Карта сотрудников и кандидатов")
        
        # Загрузка данных
        df_locations = get_cached_locations()
        if df_locations.empty:
            st.warning("Нет данных для отображения")
            return

        # Проверка обязательных колонок
        required_cols = ['Тип', 'Режим работы', 'latitude', 'longitude', 'ФИО']
        if not all(col in df_locations.columns for col in required_cols):
            st.error("Не хватает данных для построения карты")
            return

        # Фильтрация данных
        work_type_groups = {
            "Удаленно": ['Удалённо (8:00-17:00)', 'Удалённо (9:00-18:00)'],
            "Офис": ['В офисе (Москва-Сити)'],
            "Гибрид": ['Гибрид (пн, пт - офис)']
        }
        
        if work_type_filter != "Все":
            df_locations = df_locations[
                (df_locations['Режим работы'].isin(work_type_groups[work_type_filter])) |
                (df_locations['Тип'] == 'candidate')
            ]

        # Разделяем данные: обычные точки и Москва-Сити
        df_city = df_locations[df_locations['Режим работы'] == 'В офисе (Москва-Сити)']
        df_others = df_locations[df_locations['Режим работы'] != 'В офисе (Москва-Сити)']
        
        # Цвета для разных типов
        def get_color(row):
            if row['Тип'] == 'candidate':
                return [255, 0, 0, 180]  # Красный для кандидатов
            elif 'Гибрид' in row['Режим работы']:
                return [50, 200, 100, 180]  # Зеленый для гибрида
            elif 'Удалённо' in row['Режим работы']:
                return [255, 165, 0, 180]  # Оранжевый для удаленки
            return [128, 128, 128, 180]  # Серый по умолчанию
        
        df_others['color'] = df_others.apply(get_color, axis=1)
        df_others = df_others.dropna(subset=['latitude', 'longitude'])
        
        # Подготовка данных для карты
        df_others['tooltip'] = df_others.apply(
            lambda row: f"""
            <div style="padding: 8px; font-family: Arial; max-width: 250px;">
                <h4 style="margin: 0; color: {'#ff0000' if row['Тип'] == 'candidate' else '#0066cc'}">
                    {row['ФИО']}
                </h4>
                <p style="margin: 5px 0;">
                    <b>Тип:</b> {'Кандидат' if row['Тип'] == 'candidate' else 'Сотрудник'}<br>
                    <b>Режим:</b> {row['Режим работы']}<br>
                    <b>Email:</b> {row.get('Email', 'не указан')}
                </p>
            </div>
            """,
            axis=1
        )

        # Настройки карты
        view_state = pdk.ViewState(
            latitude=55.751244,
            longitude=37.618423,
            zoom=12,
            pitch=60,
            bearing=0
        )
        
        # Слои для карты
        layers = [
            # Слой для обычных точек
            pdk.Layer(
                "ScatterplotLayer",
                data=df_others,
                get_position=["longitude", "latitude"],
                get_color="color",
                get_radius=150,
                pickable=True,
                auto_highlight=True,
                highlight_color=[255, 255, 0, 200],
                radius_min_pixels=5,
                radius_max_pixels=20
            ),
            
            # Специальный слой для Москва-Сити (3D башенки)
            pdk.Layer(
                "ColumnLayer",
                data=df_city,
                get_position=["longitude", "latitude"],
                get_elevation=50,
                get_fill_color=[0, 80, 255, 200],
                radius=50,
                pickable=True,
                auto_highlight=True,
                elevation_scale=10,
                extruded=True
            )
        ]
        
        # Отображение карты
        st.pydeck_chart(pdk.Deck(
            map_style="mapbox://styles/mapbox/light-v9",
            initial_view_state=view_state,
            layers=layers,
            tooltip={
                "html": "{tooltip}",
                "style": {
                    "backgroundColor": "#1e1e1e",
                    "color": "white",
                    "borderRadius": "5px",
                    "boxShadow": "0 2px 8px rgba(0,0,0,0.3)"
                }
            }
        ))
        
        # Интерактивная легенда
        with st.expander("Пояснение для карты", expanded=True):
            st.markdown("""
            <style>
                .legend {
                    background: rgba(255,255,255,0.9);
                    padding: 10px;
                    border-radius: 5px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                }
                .legend-item {
                    display: flex;
                    align-items: center;
                    margin: 8px 0;
                }
                .legend-icon {
                    width: 20px;
                    height: 20px;
                    margin-right: 10px;
                    border-radius: 3px;
                }
                .legend-3d {
                    width: 20px;
                    height: 20px;
                    margin-right: 10px;
                    background: linear-gradient(to top, #0050ff, #00a2ff);
                    transform: perspective(20px) rotateX(20deg);
                }
            </style>
            
            <div class="legend">
                <div class="legend-item">
                    <div class="legend-icon" style="background-color: rgb(255, 0, 0);"></div>
                    <span>Кандидаты</span>
                </div>
                <div class="legend-item">
                    <div class="legend-3d"></div>
                    <span>Офис Москва-Сити</span>
                </div>
                <div class="legend-item">
                    <div class="legend-icon" style="background-color: rgb(50, 200, 100);"></div>
                    <span>Гибридный график</span>
                </div>
                <div class="legend-item">
                    <div class="legend-icon" style="background-color: rgb(255, 165, 0);"></div>
                    <span>Удаленные сотрудники</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        # Статистика и таблица данных
        col1, col2, col3 = st.columns(3)
        col1.metric("Всего", len(df_locations))
        col2.metric("На карте", len(df_others) + len(df_city))
        col3.metric("В Москва-Сити", len(df_city))
        
        st.subheader("Детализация данных")
        st.dataframe(
            df_locations[['ФИО', 'Тип', 'Режим работы', 'Email']],
            height=400,
            use_container_width=True,
            hide_index=True
        )
        
    except Exception as e:
        st.error("Ошибка при построении карты")
        st.error(f"Детали: {str(e)}")

@admin_required
def render_analytics_tab():
    try:
        st.header("📊 Аналитика")
        
        col1, col2 = st.columns(2)
        
        with col1:
            df_dept = get_cached_employees_by_dept()
            if not df_dept.empty:
                fig = px.pie(
                    df_dept,
                    values='Сотрудников',
                    names='Департамент',
                    title='Распределение по департаментам',
                    hole=0.3
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Нет данных по департаментам")
        
        with col2:
            df_status = get_cached_candidates_by_status()
            if not df_status.empty:
                fig = px.bar(
                    df_status,
                    x='Статус',
                    y='Количество',
                    title='Кандидаты по статусам',
                    color='Статус',
                    text='Количество'
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Нет данных о кандидатах")
        
        st.divider()
        
        df_doc_times = get_cached_doc_processing_times()
        if not df_doc_times.empty:
            fig = px.bar(
                df_doc_times,
                x='Тип документа',
                y='Средний срок (дни)',
                title='Средние сроки обработки документов',
                color='Тип документа',
                text='Средний срок (дни)'
            )
            fig.update_traces(texttemplate='%{text:.1f} дн.', textposition='outside')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Нет данных о сроках обработки")
    except Exception as e:
        st.error(f"Ошибка при загрузке аналитики: {str(e)}")

@admin_required
def render_documents_tab():
    try:
        st.header("📄 Документооборот")
        
        col1, col2 = st.columns(2)
        
        with col1:
            df_doc_status = get_cached_documents_by_status()
            if not df_doc_status.empty:
                fig = px.pie(
                    df_doc_status,
                    values='Количество',
                    names='Статус',
                    title='Документы по статусам',
                    color='Статус',
                    color_discrete_map={
                        'Принят': '#2ca02c',
                        'Отклонен': '#d62728',
                        'На рассмотрении': '#ff7f0e',
                        'Заказан': '#1f77b4',
                        'Не принят': '#7f7f7f'
                    },
                    hole=0.3
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Нет данных о статусах документов")
        
        with col2:
            df_doc_type = get_cached_documents_by_type()
            if not df_doc_type.empty:
                fig = px.bar(
                    df_doc_type,
                    x='Тип документа',
                    y='Количество',
                    title='Документы по типам',
                    color='Тип документа',
                    text='Количество'
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Нет данных о типах документов")
        
        st.divider()
        
        st.subheader("Документы, требующие внимания")
        df_pending_docs = get_cached_pending_docs()
        if not df_pending_docs.empty:
            st.dataframe(
                df_pending_docs,
                column_config={
                    "Дата подачи": st.column_config.DatetimeColumn(format="DD.MM.YYYY"),
                    "Обновлено": st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm")
                },
                hide_index=True,
                use_container_width=True
            )
        else:
            st.success("Все документы обработаны!")
    except Exception as e:
        st.error(f"Ошибка при загрузке документов: {str(e)}")

def dash():
    if not check_auth():
        login()
        return
    
    st.title("📊 HR Аналитика")
    st.caption("Панель мониторинга кадровых процессов")
    
    date_range, work_type_filter = setup_sidebar_filters()
    
    tab1, tab2, tab3 = st.tabs([
        "📍 Локации", 
        "📊 Аналитика",
        "📄 Документы"
    ])
    
    with tab1:
        render_locations_tab(work_type_filter)
    
    with tab2:
        render_analytics_tab()
    
    with tab3:
        render_documents_tab()

if __name__ == "__main__":
    dash()