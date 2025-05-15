import streamlit as st
import pandas as pd
import psycopg2
import plotly.express as px
import pydeck as pdk
from datetime import datetime, timedelta
from configparser import ConfigParser
from candidate.database import get_connection

# Page configuration must be FIRST
st.set_page_config(
    page_title="HR Analytics Dashboard",
    page_icon="📊",
    layout="wide"
)

# Database connection
@st.cache_resource
def get_db_connection():
    return get_connection()

conn = get_db_connection()

# Sidebar filters
st.sidebar.title("Filters")
date_range = st.sidebar.date_input(
    "Date range",
    value=[datetime.now() - timedelta(days=30), datetime.now()],
    max_value=datetime.now()
)

# Main dashboard
st.title("HR Analytics Dashboard")

# Tab layout
tab1, tab2, tab3, tab4 = st.tabs([
    "📍 Employee Locations", 
    "📊 HR Analytics",
    "👥 Candidates",
    "📄 Documents"
])

with tab1:
    st.header("Employee & Candidate Locations")
    
    # Query for employee locations
    query = """
    SELECT 
        u.user_uuid,
        u.first_name || ' ' || u.last_name as name,
        u.email,
        cl.latitude,
        cl.longitude,
        'employee' as type,
        pl.position as position,
        d.department,
        m.management,
        dv.division
    FROM auth.user u
    JOIN hr.candidate_location cl ON u.user_uuid = cl.candidate_uuid
    LEFT JOIN auth.position p ON p.position_id = ANY(u.positions_ids)
    LEFT JOIN auth.position_list pl ON p.position_list_id = pl.position_list_id
    LEFT JOIN auth.division dv ON p.division_id = dv.division_id
    LEFT JOIN auth.management m ON p.management_id = m.management_id
    LEFT JOIN auth.department d ON m.department_id = d.department_id
    
    UNION ALL
    
    SELECT 
        c.candidate_uuid,
        c.first_name || ' ' || c.last_name as name,
        c.email,
        cl.latitude,
        cl.longitude,
        'candidate' as type,
        NULL as position,
        NULL as department,
        NULL as management,
        NULL as division
    FROM hr.candidate c
    JOIN hr.candidate_location cl ON c.candidate_uuid = cl.candidate_uuid
    WHERE c.status_id NOT IN (SELECT status_id FROM hr.candidate_status WHERE is_final = true)
    """
    
    df_locations = pd.read_sql(query, conn)
    
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

with tab2:
    st.header("HR Analytics")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Employees by department
        query = """
        SELECT d.department, COUNT(u.user_uuid) as count
        FROM auth.user u
        JOIN auth.position p ON p.position_id = ANY(u.positions_ids)
        JOIN auth.management m ON p.management_id = m.management_id
        JOIN auth.department d ON m.department_id = d.department_id
        GROUP BY d.department
        """
        df_dept = pd.read_sql(query, conn)
        
        if not df_dept.empty:
            fig = px.pie(df_dept, values='count', names='department', 
                         title='Employees by Department')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No department data available")
    
    with col2:
        # Candidates by status
        query = """
        SELECT cs.name as status, COUNT(c.candidate_uuid) as count
        FROM hr.candidate c
        JOIN hr.candidate_status cs ON c.status_id = cs.status_id
        GROUP BY cs.name
        """
        df_status = pd.read_sql(query, conn)
        
        if not df_status.empty:
            fig = px.bar(df_status, x='status', y='count', 
                         title='Candidates by Status', color='status')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No candidate status data available")
    
    # Document processing times
    query = """
    SELECT dt.name as document_type, 
           AVG(EXTRACT(EPOCH FROM (dh.created_at - cd.submitted_at))/86400) as avg_processing_days
    FROM hr.candidate_document cd
    JOIN hr.document_template dt ON cd.template_id = dt.template_id
    JOIN hr.document_history dh ON cd.document_id = dh.document_uuid
    WHERE cd.submitted_at IS NOT NULL
    GROUP BY dt.name
    """
    df_doc_times = pd.read_sql(query, conn)
    
    if not df_doc_times.empty:
        fig = px.bar(df_doc_times, x='document_type', y='avg_processing_days',
                     title='Average Document Processing Time (Days)')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No document processing data available")

with tab3:
    st.header("Candidate Management")
    
    # Candidate status timeline
    query = """
    SELECT 
        c.candidate_uuid,
        c.first_name || ' ' || c.last_name as name,
        cs.name as status,
        csh.changed_at,
        u.first_name || ' ' || u.last_name as changed_by
    FROM hr.candidate_status_history csh
    JOIN hr.candidate c ON csh.candidate_id = c.candidate_uuid
    JOIN hr.candidate_status cs ON csh.status_id = cs.status_id
    JOIN auth.user u ON csh.changed_by = u.user_uuid
    ORDER BY csh.changed_at DESC
    LIMIT 100
    """
    df_status_history = pd.read_sql(query, conn)
    
    if not df_status_history.empty:
        fig = px.timeline(df_status_history, 
                         x_start="changed_at", 
                         x_end=df_status_history["changed_at"] + pd.Timedelta(hours=1),
                         y="name", 
                         color="status",
                         title="Candidate Status Changes",
                         hover_data=["changed_by"])
        st.plotly_chart(fig, use_container_width=True)
        
        # Detailed view
        st.dataframe(df_status_history)
    else:
        st.info("No candidate status history available")

with tab4:
    st.header("Document Processing")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Documents by status
        query = """
        SELECT ds.status, COUNT(cd.document_id) as count
        FROM hr.candidate_document cd
        JOIN hr.document_status ds ON cd.status_id = ds.document_status_id
        GROUP BY ds.status
        """
        df_doc_status = pd.read_sql(query, conn)
        
        if not df_doc_status.empty:
            fig = px.pie(df_doc_status, values='count', names='status',
                         title='Documents by Status')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No document status data available")
    
    with col2:
        # Documents by type
        query = """
        SELECT dt.name as document_type, COUNT(cd.document_id) as count
        FROM hr.candidate_document cd
        JOIN hr.document_template dt ON cd.template_id = dt.template_id
        GROUP BY dt.name
        """
        df_doc_type = pd.read_sql(query, conn)
        
        if not df_doc_type.empty:
            fig = px.bar(df_doc_type, x='document_type', y='count',
                         title='Documents by Type', color='document_type')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No document type data available")
    
    # Pending documents
    query = """
    SELECT 
        c.first_name || ' ' || c.last_name as candidate,
        dt.name as document_type,
        cd.submitted_at,
        cd.status_id,
        CASE 
            WHEN cd.approved_at IS NOT NULL THEN 'Approved'
            WHEN cd.rejection_reason IS NOT NULL THEN 'Rejected'
            WHEN cd.submitted_at IS NOT NULL THEN 'Pending Review'
            WHEN cd.is_ordered THEN 'Ordered'
            ELSE 'Not Submitted'
        END as status,
        cd.updated_at as last_updated
    FROM hr.candidate_document cd
    JOIN hr.document_template dt ON cd.template_id = dt.template_id
    JOIN hr.candidate c ON cd.candidate_id = c.candidate_uuid
    WHERE cd.approved_at IS NULL
    ORDER BY cd.updated_at DESC
    LIMIT 50
    """
    df_pending_docs = pd.read_sql(query, conn)
    
    if not df_pending_docs.empty:
        st.subheader("Pending Documents")
        st.dataframe(df_pending_docs)
    else:
        st.info("No pending documents")

# Close connection
conn.close()