"""个人待办 API：私人便利贴，仅本人可见，完成即消失"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, PersonalTodo
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class PersonalTodoCreate(BaseModel):
    owner_id: int
    content: str


class PersonalTodoDone(BaseModel):
    done: int  # 1=完成（消失）


@router.get("/personal-todos")
def list_todos(owner_id: int, db: Session = Depends(get_db)):
    """列出某人的未完成待办（完成的已消失，不返回）"""
    rows = db.query(PersonalTodo).filter(
        PersonalTodo.owner_id == owner_id,
        PersonalTodo.done == 0,
    ).order_by(PersonalTodo.created_at.desc()).all()
    return [{"id": r.id, "content": r.content,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


@router.post("/personal-todos")
def create_todo(data: PersonalTodoCreate, db: Session = Depends(get_db)):
    content = data.content.strip()
    if not content:
        return {"error": "内容不能为空"}
    t = PersonalTodo(owner_id=data.owner_id, content=content, done=0)
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "content": t.content, "message": "已记录"}


@router.put("/personal-todos/{todo_id}")
def complete_todo(todo_id: int, data: PersonalTodoDone, db: Session = Depends(get_db)):
    """勾选完成，标记 done=1（前端不再展示，即"消失"）"""
    t = db.query(PersonalTodo).filter(PersonalTodo.id == todo_id).first()
    if not t:
        return {"error": "待办不存在"}
    t.done = data.done
    db.commit()
    return {"message": "已完成"}


@router.delete("/personal-todos/{todo_id}")
def delete_todo(todo_id: int, db: Session = Depends(get_db)):
    t = db.query(PersonalTodo).filter(PersonalTodo.id == todo_id).first()
    if t:
        db.delete(t)
        db.commit()
    return {"message": "已删除"}
