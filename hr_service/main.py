from candidate.database import get_connection, get_minio_client
from candidate.candidate_service import add_candidate

add_candidate('Никита', 'Куспис', 'margonadikta@gmail.com' ,True)