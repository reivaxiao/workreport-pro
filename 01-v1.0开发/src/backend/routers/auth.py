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
            "is_sysadmin": user.is_sysadmin,
            "avatar_color": user.avatar_color,
        }
    }


class ChangePasswordRequest(BaseModel):
    user_id: int
    old_password: str
    new_password: str


@router.post("/auth/change-password")
def change_password(data: ChangePasswordRequest, db: Session = Depends(get_db)):
    """员工自助修改自己的密码（需验证旧密码）"""
    user = db.query(User).filter(User.id == data.user_id).first()
    if not user:
        return {"success": False, "message": "用户不存在"}
    if user.password_hash != hash_password(data.old_password):
        return {"success": False, "message": "旧密码不正确"}
    new_pwd = data.new_password.strip()
    if len(new_pwd) < 6:
        return {"success": False, "message": "新密码至少 6 位"}
    user.password_hash = hash_password(new_pwd)
    db.commit()
    return {"success": True, "message": "密码修改成功"}


class ResetPasswordRequest(BaseModel):
    admin_id: int          # 操作的管理员
    target_user_id: int    # 被重置的用户
    new_password: str = "123456"


@router.post("/auth/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """系统管理员重置某用户的密码（默认重置回 123456）"""
    admin = db.query(User).filter(User.id == data.admin_id).first()
    if not admin or not admin.is_sysadmin:
        return {"success": False, "message": "仅系统管理员可重置密码"}
    target = db.query(User).filter(User.id == data.target_user_id).first()
    if not target:
        return {"success": False, "message": "用户不存在"}
    target.password_hash = hash_password(data.new_password)
    db.commit()
    return {"success": True, "message": f"已重置 {target.name} 的密码"}
