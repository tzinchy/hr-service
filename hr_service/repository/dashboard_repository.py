# dashboard_repository.py
import pandas as pd 
from repository.database import get_connection

def get_df_locations():
    query = """SELECT 
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
    return pd.read_sql(query, get_connection())

def get_pending_docs():
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
    return pd.read_sql(query, get_connection())

def get_documents_by_type():
    query = """
    SELECT dt.name as document_type, COUNT(cd.document_id) as count
    FROM hr.candidate_document cd
    JOIN hr.document_template dt ON cd.template_id = dt.template_id
    GROUP BY dt.name
    """
    return pd.read_sql(query, get_connection())

def get_documents_by_type_by_status():
    query = """
    SELECT ds.status, COUNT(cd.document_id) as count
    FROM hr.candidate_document cd
    JOIN hr.document_status ds ON cd.status_id = ds.document_status_id
    GROUP BY ds.status
    """
    return pd.read_sql(query, get_connection())

def get_employees_by_department():
    query = """
    SELECT d.department, COUNT(u.user_uuid) as count
    FROM auth.user u
    JOIN auth.position p ON p.position_id = ANY(u.positions_ids)
    JOIN auth.management m ON p.management_id = m.management_id
    JOIN auth.department d ON m.department_id = d.department_id
    GROUP BY d.department
    """
    return pd.read_sql(query, get_connection())

def get_candidates_by_status():
    query = """
    SELECT cs.name as status, COUNT(c.candidate_uuid) as count
    FROM hr.candidate c
    JOIN hr.candidate_status cs ON c.status_id = cs.status_id
    GROUP BY cs.name
    """
    return pd.read_sql(query, get_connection())

def get_document_processing_times():
    query = """
    SELECT dt.name as document_type, 
           AVG(EXTRACT(EPOCH FROM (dh.created_at - cd.submitted_at))/86400) as avg_processing_days
    FROM hr.candidate_document cd
    JOIN hr.document_template dt ON cd.template_id = dt.template_id
    JOIN hr.document_history dh ON cd.document_id = dh.document_uuid
    WHERE cd.submitted_at IS NOT NULL
    GROUP BY dt.name
    """
    return pd.read_sql(query, get_connection())

def get_candidate_status_history(limit=100):
    query = f"""
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
    LIMIT {limit}
    """
    return pd.read_sql(query, get_connection())