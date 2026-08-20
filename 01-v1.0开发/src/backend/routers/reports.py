"""周报相关API"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, WeeklyProgress, WeeklySubmitStatus, WorkItem, User
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional, List
import json

router = APIRouter()


class ProgressEntry(BaseModel):
    work_item_id: int
    progress: str = ""
    next_plan: str = ""
    blockers: str = ""
    cum_data: str = "{}"  # 本周累计数据(JSON)


class WeekSubmit(BaseModel):
    entries: List[ProgressEntry]


def get_current_week_start() -> str:
    """获取本周一的日期"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y-%m-%d")


def calc_cumulative(db: Session, work_item_id: int, week_start: str) -> dict:
    """计算累计值：自然年累计，把本自然年所有周的 cum_data 按 key 相加"""
    year = week_start[:4]  # "2026"
    # 查询该工作事项在本自然年的所有周进展
    progresses = db.query(WeeklyProgress).filter(
        WeeklyProgress.work_item_id == work_item_id,
        WeeklyProgress.week_start >= f"{year}-01-01",
        WeeklyProgress.week_start <= f"{year}-12-31",
    ).all()

    cum = {}
    for p in progresses:
        try:
            data = json.loads(p.cum_data) if p.cum_data else {}
        except:
            data = {}
        for k, v in data.items():
            if isinstance(v, (int, float)):
                cum[k] = cum.get(k, 0) + v
    return cum


def compute_status(item: WorkItem) -> str:
    """状态机：根据手动状态 + 预计完成时间自动算 进行中/临期/延期"""
    # 已完成 / 暂停 是员工手动锁定，直接返回
    if item.status in ("已完成", "暂停", "终止"):
        return item.status
    if not item.due_date:
        return "进行中"
    today = datetime.now().strftime("%Y-%m-%d")
    if today > item.due_date:
        return "延期"
    # 临期：距截止 ≤ 7 天
    due = datetime.strptime(item.due_date, "%Y-%m-%d")
    if (due - datetime.now()).days <= 7:
        return "临期"
    return "进行中"


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
    """获取某个用户本周的填写内容（含累计数据）"""
    if not week_start:
        week_start = get_current_week_start()

    items = db.query(WorkItem).filter(WorkItem.owner_id == user_id).all()
    result = []
    for item in items:
        progress = db.query(WeeklyProgress).filter(
            WeeklyProgress.work_item_id == item.id,
            WeeklyProgress.week_start == week_start
        ).first()
        last_week = (datetime.strptime(week_start, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        last_progress = db.query(WeeklyProgress).filter(
            WeeklyProgress.work_item_id == item.id,
            WeeklyProgress.week_start == last_week
        ).first()

        # 累计值
        cum_value = calc_cumulative(db, item.id, week_start)

        result.append({
            "work_item_id": item.id,
            "work_item_name": item.name,
            "category": item.category,
            "importance": item.importance,
            "status": compute_status(item),
            "due_date": item.due_date,
            "is_cumulative": item.is_cumulative,
            "cum_metrics": json.loads(item.cum_metrics) if item.cum_metrics else [],
            "target_desc": item.target_desc,
            "goal_id": item.goal_id,
            "goal_name": item.goal.name if item.goal else "",
            "progress": progress.progress if progress else "",
            "next_plan": progress.next_plan if progress else "",
            "blockers": progress.blockers if progress else "",
            "cum_data": json.loads(progress.cum_data) if progress and progress.cum_data else {},
            "cum_value": cum_value,
            "last_week_progress": last_progress.progress if last_progress else "",
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
            existing.cum_data = entry.cum_data
            existing.status_before_ai = "submitted"
            existing.submitted_at = datetime.now()
        else:
            db.add(WeeklyProgress(
                work_item_id=entry.work_item_id,
                week_start=week_start,
                progress=entry.progress,
                next_plan=entry.next_plan,
                blockers=entry.blockers,
                cum_data=entry.cum_data,
                status_before_ai="submitted",
                submitted_at=datetime.now(),
            ))

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
    """保存草稿"""
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
            existing.cum_data = entry.cum_data
        else:
            db.add(WeeklyProgress(
                work_item_id=entry.work_item_id,
                week_start=week_start,
                progress=entry.progress,
                next_plan=entry.next_plan,
                blockers=entry.blockers,
                cum_data=entry.cum_data,
                status_before_ai="draft",
            ))

    db.commit()
    return {"message": "草稿已保存"}
