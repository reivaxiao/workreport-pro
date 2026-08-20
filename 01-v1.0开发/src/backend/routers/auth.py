"""登录认证API"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, User, hash_password
from pydantic import BaseModel

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """账号密码登录"""
    user = db.query(User).filter(User.username == data.username.strip()).first()
    if not user:
        return {"success": False, "message": "账号不存在"}
    if user.password_hash != hash_password(data.password):
        return {"success": False, "message": "密码错误"}
    return {
        "success": True,
        "user": {
            "id": user.id, "name": user.name, "role": user.role,
            "business_line": user.business_line, "is_manager": user.is_manager,
            "avatar_color": user.avatar_color,
        }
    }
