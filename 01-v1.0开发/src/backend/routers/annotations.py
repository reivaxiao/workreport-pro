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
    work_item_id: int
    week_start: str
    content: str


@router.get("/annotations")
def list_annotations(week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """获取指定周的批注"""
    query = db.query(Annotation)
    if week_start:
        query = query.filter(Annotation.week_start == week_start)
    annotations = query.order_by(Annotation.created_at.desc()).all()
    result = []
    for a in annotations:
        item = db.query(WorkItem).filter(WorkItem.id == a.work_item_id).first()
        manager = db.query(User).filter(User.id == a.manager_id).first()
        result.append({
            "id": a.id,
            "manager_name": manager.name if manager else "",
            "work_item_name": item.name if item else "",
            "week_start": a.week_start,
            "content": a.content,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        })
    return result


@router.post("/annotations")
def create_annotation(data: AnnotationCreate, db: Session = Depends(get_db)):
    ann = Annotation(
        manager_id=data.manager_id,
        work_item_id=data.work_item_id,
        week_start=data.week_start,
        content=data.content,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return {"id": ann.id, "message": "批注已保存"}
