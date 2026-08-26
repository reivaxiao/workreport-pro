"""工作分类字典相关API：职能 / 一级模块 / 二级模块"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, WorkCategory
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    """返回完整的三级分类树：职能 → 一级模块 → 二级模块"""
    funcs = db.query(WorkCategory).filter(WorkCategory.level == 1).order_by(WorkCategory.sort_order, WorkCategory.id).all()
    result = []
    for f in funcs:
        m1s = db.query(WorkCategory).filter(WorkCategory.level == 2, WorkCategory.parent_id == f.id).order_by(WorkCategory.sort_order, WorkCategory.id).all()
        modules = []
        for m1 in m1s:
            m2s = db.query(WorkCategory).filter(WorkCategory.level == 3, WorkCategory.parent_id == m1.id).order_by(WorkCategory.sort_order, WorkCategory.id).all()
            modules.append({
                "id": m1.id,
                "name": m1.name,
                "children": [{"id": m2.id, "name": m2.name} for m2 in m2s],
            })
        result.append({"id": f.id, "name": f.name, "modules": modules})
    return result


class CategoryCreate(BaseModel):
    level: int            # 1=职能 2=一级模块 3=二级模块
    name: str
    parent_id: Optional[int] = None


@router.post("/categories")
def create_category(data: CategoryCreate, db: Session = Depends(get_db)):
    """新增分类（管理者用）。员工新增二级模块时也走这里。"""
    cat = WorkCategory(level=data.level, name=data.name, parent_id=data.parent_id)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "message": "已添加"}


class CategoryDelete(BaseModel):
    id: int


@router.delete("/categories/{cat_id}")
def delete_category(cat_id: int, db: Session = Depends(get_db)):
    """删除分类（连同其子级一起删除）"""
    cat = db.query(WorkCategory).filter(WorkCategory.id == cat_id).first()
    if not cat:
        return {"error": "分类不存在"}
    # 删除子级
    children = db.query(WorkCategory).filter(WorkCategory.parent_id == cat_id).all()
    for c in children:
        db.query(WorkCategory).filter(WorkCategory.parent_id == c.id).delete()
        db.delete(c)
    db.delete(cat)
    db.commit()
    return {"message": "已删除"}
