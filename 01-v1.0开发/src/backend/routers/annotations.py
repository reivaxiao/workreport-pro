"""管理者批注相关API"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, Annotation, WorkItem, User
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()


class AnnotationCreate(BaseModel):
    manager_id: int
    work_item_id: Optional[int] = None   # 可为空：针对汇总/全员的批注
    week_start: str
    content: str


def identify_target_user(content: str, db: Session) -> Optional[int]:
    """识别批注点名的成员，返回 user_id；没点名返回 None。
    采用文字匹配：批注里出现某成员的名字（全名）即视为点名。"""
    try:
        users = db.query(User).all()
        # 按名字长度降序匹配，避免"李雯"匹配到"李雯"这种部分包含
        for u in sorted(users, key=lambda x: -len(x.name)):
            if u.name and u.name in content:
                return u.id
        return None
    except Exception as e:
        print(f"[批注点名识别] 失败: {e}")
        return None


@router.get("/annotations")
def list_annotations(week_start: Optional[str] = None, user_id: Optional[int] = None, db: Session = Depends(get_db)):
    """获取批注。user_id 用于员工端查询"发给我的批注"。"""
    query = db.query(Annotation)
    if week_start:
        query = query.filter(Annotation.week_start == week_start)
    if user_id:
        # 发给我的：点名是我 或 未点名且我参与了该事项
        query = query.filter(
            (Annotation.target_user_id == user_id) |
            ((Annotation.target_user_id.is_(None)) & (Annotation.work_item_id.is_(None)))
        )
    annotations = query.order_by(Annotation.created_at.desc()).all()
    result = []
    for a in annotations:
        item = db.query(WorkItem).filter(WorkItem.id == a.work_item_id).first() if a.work_item_id else None
        manager = db.query(User).filter(User.id == a.manager_id).first()
        target = db.query(User).filter(User.id == a.target_user_id).first() if a.target_user_id else None
        result.append({
            "id": a.id,
            "manager_name": manager.name if manager else "",
            "work_item_name": item.name if item else "",
            "target_user_name": target.name if target else "",
            "week_start": a.week_start,
            "content": a.content,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        })
    return result


@router.post("/annotations")
def create_annotation(data: AnnotationCreate, db: Session = Depends(get_db)):
    # AI 识别点名
    target_user_id = identify_target_user(data.content, db)
    ann = Annotation(
        manager_id=data.manager_id,
        work_item_id=data.work_item_id,
        week_start=data.week_start,
        content=data.content,
        target_user_id=target_user_id,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    target_name = ""
    if target_user_id:
        u = db.query(User).filter(User.id == target_user_id).first()
        target_name = u.name if u else ""
    return {"id": ann.id, "message": "批注已保存", "target_user_name": target_name}
