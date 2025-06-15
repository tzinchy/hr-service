# dashboard_repository.py
import pandas as pd 
from repository.database import get_connection

def get_df_locations():
    query = """
    -- Кандидаты (всегда показываем их локации)
    SELECT 
        c.candidate_uuid AS id,
        c.first_name || ' ' || c.last_name AS name,
        c.email as email,
        cl.latitude as latitude,
        cl.longitude as longitude,
        'candidate' AS type,
        'Кандидат' AS work_type_display,
        NULL::integer AS work_type,
        NULL AS work_range,
        NULL AS notes
    FROM hr.candidate c
    JOIN hr.candidate_location cl ON c.candidate_uuid = cl.candidate_uuid
    WHERE c.status_id NOT IN (
        SELECT status_id FROM hr.candidate_status WHERE is_final = true
    )

    UNION ALL

    -- Сотрудники (новая логика отображения)
    SELECT 
        u.user_uuid AS id,
        u.first_name || ' ' || u.last_name AS name,
        u.email as email,
        CASE
            -- Для офисных работников используем офисные координаты
            WHEN wt.work_type_id IN (3, 4) THEN COALESCE(wt.latitude, 55.749473)
            ELSE ul.latitude
        END AS latitude,
        CASE
            WHEN wt.work_type_id IN (3, 4) THEN COALESCE(wt.longtitude, 37.537052)
            ELSE ul.longitude
        END AS longitude,
        'employee' AS type,
        CASE wt.work_type_id
            WHEN 1 THEN 'Удалённо (8:00-17:00)'
            WHEN 2 THEN 'Удалённо (9:00-18:00)'
            WHEN 3 THEN 'В офисе (Москва-Сити)'
            WHEN 4 THEN 'В офисе (Москва-Сити)'
            WHEN 5 THEN 'Гибрид (пн, пт - офис)'
            WHEN 6 THEN 'Гибрид (пн, пт - офис)'
            ELSE 'Не указано'
        END AS work_type_display,
        wt.work_type_id,
        wt.work_range,
        wt.notes
    FROM auth."user" u
    LEFT JOIN auth.work_type wt ON u.work_type_id = wt.work_type_id
    LEFT JOIN auth.user_location ul ON u.user_uuid = ul.user_uuid
    WHERE u.work_type_id IS NOT NULL
    """
    return pd.read_sql(query, get_connection())

def get_pending_docs():
    query = """
    SELECT 
        c.first_name || ' ' || c.last_name as candidate_employee,
        dt.name as doc_type,
        cd.submitted_at as submitted_at,
        CASE 
            WHEN cd.approved_at IS NOT NULL THEN 'Принят'
            WHEN cd.rejection_reason IS NOT NULL THEN 'Отклонен'
            WHEN cd.submitted_at IS NOT NULL THEN 'На рассмотрении'
            WHEN cd.is_ordered THEN 'Заказан'
            ELSE 'Не принят'
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
    SELECT dt.name as doc_type, COUNT(cd.document_id) as count
    FROM hr.candidate_document cd
    JOIN hr.document_template dt ON cd.template_id = dt.template_id
    GROUP BY dt.name
    """
    return pd.read_sql(query, get_connection())

def get_documents_by_type_by_status():
    query = """
    SELECT ds.status as status, COUNT(cd.document_id) as count
    FROM hr.candidate_document cd
    JOIN hr.document_status ds ON cd.status_id = ds.document_status_id
    GROUP BY ds.status
    """
    return pd.read_sql(query, get_connection())

def get_employees_by_department():
    query = """
    SELECT d.department as department, COUNT(u.user_uuid) as count
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
    SELECT dt.name as doc_type, 
           AVG(EXTRACT(EPOCH FROM (dh.created_at - cd.submitted_at))/86400) as avg_days
    FROM hr.candidate_document cd
    JOIN hr.document_template dt ON cd.template_id = dt.template_id
    JOIN hr.document_history dh ON cd.document_id = dh.document_uuid
    WHERE cd.submitted_at IS NOT NULL
    GROUP BY dt.name
    """
    return pd.read_sql(query, get_connection())