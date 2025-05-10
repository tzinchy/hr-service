from fastapi import APIRouter, Response, Depends, Body
from depends import auth_service
from schemas.auth import UserLogin, UserResetEmail
from service.jwt_service import UserTokenData, get_user
from schemas.user import PasswordSwitch
router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/login")
async def login_user(user : UserLogin, response : Response) -> dict:
    front_response = await auth_service.login_user(user.login_or_email,user.password, response)
    return {'user' : front_response}
    
    
@router.post("user/change_password")
async def change_password(password_switch : PasswordSwitch, user : UserTokenData = Depends(get_user)):
    result = await auth_service.change_password(user_uuid=user.user_uuid, old_password=password_switch.old_password, new_password=password_switch.new_password)
    return result

@router.post("/reset_password")
async def reset_passwor(user_email: UserResetEmail):
    result = await auth_service.reset_password(user_email.email)
    return result