"""用户相关API"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, User

router = APIRouter()


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [
        {
            "id": u.id,
            "name": u.name,
            "role": u.role,
            "business_line": u.business_line,
            "is_manager": u.is_manager,
            "avatar_color": u.avatar_color,
        }
        for u in users
    ]


@router.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        return {"error": "用户不存在"}
    return {
        "id": u.id, "name": u.name, "role": u.role,
        "business_line": u.business_line, "is_manager": u.is_manager,
    }
