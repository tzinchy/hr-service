from repository.database import get_connection
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def update_candidate(telegram_chat_id, code):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"""UPDATE hr.candiadte set telegram_chat_id = {telegram_chat_id}' \
            where invitation_code = {code}""")
            connection.commit()
