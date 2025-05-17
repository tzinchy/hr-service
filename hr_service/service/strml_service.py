from service.email_service import send_invitation_email
from repository.strml_repository import add_candidate_to_db


def add_candidate(first_name: str, last_name: str, email: str, sex: bool):
    user_uuid, invitation_code = add_candidate_to_db(first_name, last_name, email, sex)
    send_invitation_email(email, invitation_code)
    return user_uuid, invitation_code
