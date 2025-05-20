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
    get_document_processing_times,
    get_candidate_status_history
)

# Page configuration
st.set_page_config(
    page_title="HR Analytics Dashboard",
    page_icon="📊",
    layout="wide"
)

# Cache configuration
@st.cache_data(ttl=3600, show_spinner="Loading location data...")
def get_cached_locations():
    return get_df_locations()

@st.cache_data(ttl=600, show_spinner="Loading pending documents...")
def get_cached_pending_docs():
    return get_pending_docs()

@st.cache_data(ttl=600, show_spinner="Loading documents by type...")
def get_cached_documents_by_type():
    return get_documents_by_type()

@st.cache_data(ttl=600, show_spinner="Loading documents by status...")
def get_cached_documents_by_status():
    return get_documents_by_type_by_status()

@st.cache_data(ttl=600, show_spinner="Loading department data...")
def get_cached_employees_by_dept():
    return get_employees_by_department()

@st.cache_data(ttl=600, show_spinner="Loading candidate status data...")
def get_cached_candidates_by_status():
    return get_candidates_by_status()

@st.cache_data(ttl=600, show_spinner="Loading document processing times...")
def get_cached_doc_processing_times():
    return get_document_processing_times()

@st.cache_data(ttl=300, show_spinner="Loading candidate history...")
def get_cached_candidate_history():
    return get_candidate_status_history()

# Sidebar filters
def setup_sidebar_filters():
    st.sidebar.title("Filters")
    date_range = st.sidebar.date_input(
        "Date range",
        value=[datetime.now() - timedelta(days=30), datetime.now()],
        max_value=datetime.now()
    )
    return date_range

# Tab 1: Employee Locations
def render_locations_tab():
    st.header("Employee & Candidate Locations")
    
    df_locations = get_cached_locations()
    
    if not df_locations.empty:
        # Map visualization
        st.pydeck_chart(pdk.Deck(
            map_style='mapbox://styles/mapbox/light-v9',
            initial_view_state=pdk.ViewState(
                latitude=df_locations['latitude'].mean(),
                longitude=df_locations['longitude'].mean(),
                zoom=10,
                pitch=50,
            ),
            layers=[
                pdk.Layer(
                    'ScatterplotLayer',
                    data=df_locations,
                    get_position='[longitude, latitude]',
                    get_color='[200, 30, 0, 160]',
                    get_radius=200,
                    pickable=True,
                    auto_highlight=True,
                ),
            ],
            tooltip={
                "html": "<b>Name:</b> {name}<br/>"
                        "<b>Type:</b> {type}<br/>"
                        "<b>Email:</b> {email}<br/>"
                        "<b>Position:</b> {position}<br/>"
                        "<b>Department:</b> {department}<br/>"
                        "<b>Division:</b> {division}",
                "style": {
                    "backgroundColor": "steelblue",
                    "color": "white"
                }
            }
        ))
        
        # Data table
        st.dataframe(df_locations)
    else:
        st.warning("No location data available")

# Tab 2: HR Analytics
def render_analytics_tab():
    st.header("HR Analytics")
    
    col1, col2 = st.columns(2)
    
    with col1:
        df_dept = get_cached_employees_by_dept()
        if not df_dept.empty:
            fig = px.pie(df_dept, values='count', names='department', 
                         title='Employees by Department')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No department data available")
    
    with col2:
        df_status = get_cached_candidates_by_status()
        if not df_status.empty:
            fig = px.bar(df_status, x='status', y='count', 
                         title='Candidates by Status', color='status')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No candidate status data available")
    
    df_doc_times = get_cached_doc_processing_times()
    if not df_doc_times.empty:
        fig = px.bar(df_doc_times, x='document_type', y='avg_processing_days',
                     title='Average Document Processing Time (Days)')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No document processing data available")

# Tab 3: Candidates
def render_candidates_tab():
    st.header("Candidate Management")
    
    df_status_history = get_cached_candidate_history(limit=100)
    
    if not df_status_history.empty:
        fig = px.timeline(df_status_history, 
                         x_start="changed_at", 
                         x_end=df_status_history["changed_at"] + pd.Timedelta(hours=1),
                         y="name", 
                         color="status",
                         title="Candidate Status Changes",
                         hover_data=["changed_by"])
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_status_history)
    else:
        st.info("No candidate status history available")

# Tab 4: Documents
def render_documents_tab():
    st.header("Document Processing")
    
    col1, col2 = st.columns(2)
    
    with col1:
        df_doc_status = get_cached_documents_by_status()
        if not df_doc_status.empty:
            fig = px.pie(df_doc_status, values='count', names='status',
                         title='Documents by Status')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No document status data available")
    
    with col2:
        df_doc_type = get_cached_documents_by_type()
        if not df_doc_type.empty:
            fig = px.bar(df_doc_type, x='document_type', y='count',
                         title='Documents by Type', color='document_type')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No document type data available")
    
    df_pending_docs = get_cached_pending_docs()
    if not df_pending_docs.empty:
        st.subheader("Pending Documents")
        st.dataframe(df_pending_docs)
    else:
        st.info("No pending documents")

# Main dashboard
def main():
    st.title("HR Analytics Dashboard")
    date_range = setup_sidebar_filters()
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "📍 Employee Locations", 
        "📊 HR Analytics",
        "👥 Candidates",
        "📄 Documents"
    ])
    
    with tab1:
        render_locations_tab()
    
    with tab2:
        render_analytics_tab()
    
    with tab3:
        render_candidates_tab()
    
    with tab4:
        render_documents_tab()

if __name__ == "__main__":
    main()