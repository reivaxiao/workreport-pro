"""工作事项相关API"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, WorkItem, User, AnnualGoal
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class WorkItemCreate(BaseModel):
    name: str
    category: str
    owner_id: int
    goal_id: Optional[int] = None
    target_desc: str = ""


class WorkItemUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    goal_id: Optional[int] = None
    target_desc: Optional[str] = None
    status: Optional[str] = None


@router.get("/items")
def list_items(user_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(WorkItem)
    if user_id:
        query = query.filter(WorkItem.owner_id == user_id)
    items = query.order_by(WorkItem.updated_at.desc()).all()
    result = []
    for item in items:
        owner = db.query(User).filter(User.id == item.owner_id).first()
        goal = db.query(AnnualGoal).filter(AnnualGoal.id == item.goal_id).first() if item.goal_id else None
        result.append({
            "id": item.id, "name": item.name, "category": item.category,
            "owner_id": item.owner_id, "owner_name": owner.name if owner else "",
            "goal_id": item.goal_id, "goal_name": goal.name if goal else "",
            "target_desc": item.target_desc, "status": item.status,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })
    return result


@router.post("/items")
def create_item(data: WorkItemCreate, db: Session = Depends(get_db)):
    item = WorkItem(
        name=data.name, category=data.category,
        owner_id=data.owner_id, goal_id=data.goal_id,
        target_desc=data.target_desc,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "message": "创建成功"}


@router.put("/items/{item_id}")
def update_item(item_id: int, data: WorkItemUpdate, db: Session = Depends(get_db)):
    item = db.query(WorkItem).filter(WorkItem.id == item_id).first()
    if not item:
        return {"error": "事项不存在"}
    if data.name is not None:
        item.name = data.name
    if data.category is not None:
        item.category = data.category
    if data.goal_id is not None:
        item.goal_id = data.goal_id
    if data.target_desc is not None:
        item.target_desc = data.target_desc
    if data.status is not None:
        item.status = data.status
    db.commit()
    return {"message": "更新成功"}


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(WorkItem).filter(WorkItem.id == item_id).first()
    if not item:
        return {"error": "事项不存在"}
    db.delete(item)
    db.commit()
    return {"message": "已删除"}
