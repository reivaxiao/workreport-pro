"""AI智能体相关API - 审阅Agent"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, WeeklyProgress, WeeklySubmitStatus, WorkItem, User, Annotation
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional, List
import json

router = APIRouter()


class ReviewRequest(BaseModel):
    user_id: int
    week_start: str


class ReviewReply(BaseModel):
    progress_id: int
    user_reply: str


class ReviewConversation(BaseModel):
    progress_id: int
    message: str


def analyze_progress(progress: WeeklyProgress, last_week_progress, item_name: str, db: Session) -> List[dict]:
    """AI审阅分析：返回建议列表"""
    suggestions = []
    week_start = progress.week_start

    # 1. 检查是否为空
    if not progress.progress.strip() or len(progress.progress.strip()) < 5:
        suggestions.append({
            "type": "warning",
            "field": "progress",
            "message": f"「{item_name}」的本周进展描述太简短了，建议补充具体做了什么、取得了什么成果。"
        })

    # 2. 检查是否有量化数据
    has_numbers = any(c.isdigit() for c in progress.progress)
    if progress.progress.strip() and not has_numbers:
        suggestions.append({
            "type": "suggestion",
            "field": "progress",
            "message": f"「{item_name}」的进展描述中可以补充一些量化数据，比如完成了多少、达成率多少，这样更有说服力。"
        })

    # 3. 对比上周计划
    if last_week_progress and last_week_progress.next_plan.strip():
        if last_week_progress.next_plan.strip() not in progress.progress:
            suggestions.append({
                "type": "question",
                "field": "progress",
                "message": f"上周你在「{item_name}」中写道计划「{last_week_progress.next_plan[:50]}...」，本周的进展里似乎没有提到，是还未推进还是漏掉了？"
            })

    # 4. 检查下阶段计划
    if not progress.next_plan.strip():
        suggestions.append({
            "type": "reminder",
            "field": "next_plan",
            "message": f"「{item_name}」缺少下阶段工作计划，建议补充下周准备做什么。"
        })

    # 5. 连续多周无进展的提醒
    if last_week_progress and not last_week_progress.progress.strip():
        # 继续往前查
        two_weeks_ago = (datetime.strptime(week_start, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
        older = db.query(WeeklyProgress).filter(
            WeeklyProgress.work_item_id == progress.work_item_id,
            WeeklyProgress.week_start == two_weeks_ago
        ).first()
        if older and not older.progress.strip():
            suggestions.append({
                "type": "warning",
                "field": "progress",
                "message": f"「{item_name}」已连续多周没有实质性进展，是否需要调整计划或标记为暂停？"
            })

    return suggestions


def compress_progress(text: str) -> str:
    """精简提炼内容"""
    if len(text) <= 80:
        return text
    # 简单提炼：取前几行关键信息
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) <= 2:
        return text
    return "\n".join(lines[:2]) + f"\n...（共{len(lines)}条，已自动精简）"


@router.post("/agent/review")
def agent_review(data: ReviewRequest, db: Session = Depends(get_db)):
    """AI审阅Agent：分析指定用户指定周的周报"""
    user_id = data.user_id
    week_start = data.week_start

    # 获取该用户本周所有进展
    user_items = db.query(WorkItem).filter(WorkItem.owner_id == user_id).all()
    last_week = (datetime.strptime(week_start, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")

    all_suggestions = []
    for item in user_items:
        progress = db.query(WeeklyProgress).filter(
            WeeklyProgress.work_item_id == item.id,
            WeeklyProgress.week_start == week_start
        ).first()
        if not progress:
            continue

        last_progress = db.query(WeeklyProgress).filter(
            WeeklyProgress.work_item_id == item.id,
            WeeklyProgress.week_start == last_week
        ).first()

        suggestions = analyze_progress(progress, last_progress, item.name, db)
        for s in suggestions:
            s["work_item_id"] = item.id
            s["work_item_name"] = item.name
            s["progress_id"] = progress.id

        # 自动精简提炼
        if progress.progress.strip():
            compressed = compress_progress(progress.progress)
            if compressed != progress.progress:
                suggestions.append({
                    "type": "compress",
                    "field": "progress",
                    "progress_id": progress.id,
                    "work_item_id": item.id,
                    "work_item_name": item.name,
                    "message": f"帮你精简了「{item.name}」的进展描述：\n---\n{compressed}\n---\n要不要用这个版本？",
                    "compressed_text": compressed,
                })

        all_suggestions.extend(suggestions)

    return {
        "user_id": user_id,
        "week_start": week_start,
        "total_suggestions": len(all_suggestions),
        "suggestions": all_suggestions,
    }


@router.get("/agent/submit-status")
def agent_check_status(week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """催办Agent：检查提交状态"""
    if not week_start:
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())
        week_start = monday.strftime("%Y-%m-%d")

    users = db.query(User).all()
    submitted = []
    not_submitted = []

    for user in users:
        status = db.query(WeeklySubmitStatus).filter(
            WeeklySubmitStatus.user_id == user.id,
            WeeklySubmitStatus.week_start == week_start
        ).first()
        if status and status.status == "submitted":
            submitted.append(user.name)
        else:
            not_submitted.append({
                "name": user.name,
                "role": user.role,
                "business_line": user.business_line,
            })

    all_done = len(not_submitted) == 0
    return {
        "week_start": week_start,
        "all_submitted": all_done,
        "submitted": submitted,
        "not_submitted": not_submitted,
        "total": len(users),
    }
