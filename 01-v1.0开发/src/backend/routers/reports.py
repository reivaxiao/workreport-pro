"""周报相关API"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, WeeklyProgress, WeeklySubmitStatus, WorkItem, User
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()


class ProgressEntry(BaseModel):
    work_item_id: int
    progress: str = ""
    next_plan: str = ""
    blockers: str = ""


class WeekSubmit(BaseModel):
    entries: List[ProgressEntry]


def get_current_week_start() -> str:
    """获取本周一的日期"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y-%m-%d")


@router.get("/reports/week-status")
def week_status(week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """查看某周的提交状态"""
    if not week_start:
        week_start = get_current_week_start()

    users = db.query(User).all()
    result = []
    for user in users:
        status_row = db.query(WeeklySubmitStatus).filter(
            WeeklySubmitStatus.user_id == user.id,
            WeeklySubmitStatus.week_start == week_start
        ).first()
        result.append({
            "user_id": user.id,
            "name": user.name,
            "role": user.role,
            "business_line": user.business_line,
            "status": status_row.status if status_row else "not_started",
            "submitted_at": status_row.submitted_at.isoformat() if status_row and status_row.submitted_at else None,
        })
    return {"week_start": week_start, "members": result}


@router.get("/reports/my-progress")
def my_progress(user_id: int, week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """获取某个用户本周的填写内容（用于填充表单）"""
    if not week_start:
        week_start = get_current_week_start()

    items = db.query(WorkItem).filter(WorkItem.owner_id == user_id).all()
    result = []
    for item in items:
        progress = db.query(WeeklyProgress).filter(
            WeeklyProgress.work_item_id == item.id,
            WeeklyProgress.week_start == week_start
        ).first()
        # 找上周的进展作为参考
        last_week = (datetime.strptime(week_start, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        last_progress = db.query(WeeklyProgress).filter(
            WeeklyProgress.work_item_id == item.id,
            WeeklyProgress.week_start == last_week
        ).first()

        result.append({
            "work_item_id": item.id,
            "work_item_name": item.name,
            "category": item.category,
            "status": item.status,
            "progress": progress.progress if progress else "",
            "next_plan": progress.next_plan if progress else "",
            "blockers": progress.blockers if progress else "",
            "ai_suggestions": progress.ai_suggestions if progress else "",
            "status_before_ai": progress.status_before_ai if progress else "draft",
            "last_week_next_plan": last_progress.next_plan if last_progress else "",
        })
    return result


@router.post("/reports/submit")
def submit_week(user_id: int, data: WeekSubmit, week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """提交本周周报"""
    if not week_start:
        week_start = get_current_week_start()

    for entry in data.entries:
        existing = db.query(WeeklyProgress).filter(
            WeeklyProgress.work_item_id == entry.work_item_id,
            WeeklyProgress.week_start == week_start
        ).first()

        if existing:
            existing.progress = entry.progress
            existing.next_plan = entry.next_plan
            existing.blockers = entry.blockers
            existing.status_before_ai = "submitted"
            existing.submitted_at = datetime.now()
        else:
            new_progress = WeeklyProgress(
                work_item_id=entry.work_item_id,
                week_start=week_start,
                progress=entry.progress,
                next_plan=entry.next_plan,
                blockers=entry.blockers,
                status_before_ai="submitted",
                submitted_at=datetime.now(),
            )
            db.add(new_progress)

    # 更新提交状态
    status_row = db.query(WeeklySubmitStatus).filter(
        WeeklySubmitStatus.user_id == user_id,
        WeeklySubmitStatus.week_start == week_start
    ).first()
    if status_row:
        status_row.status = "submitted"
        status_row.submitted_at = datetime.now()
    else:
        db.add(WeeklySubmitStatus(user_id=user_id, week_start=week_start, status="submitted", submitted_at=datetime.now()))

    db.commit()
    return {"message": "提交成功", "week_start": week_start}


@router.post("/reports/save-draft")
def save_draft(user_id: int, data: WeekSubmit, week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """保存草稿（不触发提交状态）"""
    if not week_start:
        week_start = get_current_week_start()

    for entry in data.entries:
        existing = db.query(WeeklyProgress).filter(
            WeeklyProgress.work_item_id == entry.work_item_id,
            WeeklyProgress.week_start == week_start
        ).first()

        if existing:
            existing.progress = entry.progress
            existing.next_plan = entry.next_plan
            existing.blockers = entry.blockers
        else:
            db.add(WeeklyProgress(
                work_item_id=entry.work_item_id,
                week_start=week_start,
                progress=entry.progress,
                next_plan=entry.next_plan,
                blockers=entry.blockers,
                status_before_ai="draft",
            ))

    db.commit()
    return {"message": "草稿已保存"}
