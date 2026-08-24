"""AI智能体相关API：审阅、信息提炼（累计）、汇报视图聚合、待办、反馈"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, WeeklyProgress, WeeklySubmitStatus, WorkItem, User, Annotation, Todo, FeedbackRule
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional, List
import json

router = APIRouter()


def get_current_week_start() -> str:
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y-%m-%d")


def calc_cumulative(db: Session, work_item_id: int, week_start: str) -> dict:
    """自然年累计"""
    year = week_start[:4]
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
    if item.status in ("已完成", "暂停", "终止"):
        return item.status
    if not item.due_date:
        return "进行中"
    today = datetime.now().strftime("%Y-%m-%d")
    if today > item.due_date:
        return "延期"
    due = datetime.strptime(item.due_date, "%Y-%m-%d")
    if (due - datetime.now()).days <= 7:
        return "临期"
    return "进行中"


# ========== 审阅 Agent（DeepSeek 驱动） ==========
class ReviewRequest(BaseModel):
    user_id: int
    week_start: str


def analyze_progress_with_ai(progress, last_week_progress, item_name) -> List[dict]:
    """调用 DeepSeek 审阅单条工作事项，返回结构化建议列表"""
    try:
        from agents.deepseek_client import build_review_messages, chat_json
        messages = build_review_messages(
            item_name=item_name,
            progress=progress.progress,
            next_plan=progress.next_plan,
            blockers=progress.blockers,
            last_week_progress=last_week_progress.progress if last_week_progress else "",
            last_week_next_plan=last_week_progress.next_plan if last_week_progress else "",
        )
        result = chat_json(messages)
        if isinstance(result, list):
            # 过滤出有效建议
            valid = []
            for r in result:
                if isinstance(r, dict) and r.get("message"):
                    valid.append({
                        "type": r.get("type", "建议"),
                        "field": r.get("field", "progress"),
                        "message": r["message"],
                    })
            return valid
        return []
    except Exception as e:
        # AI 调用失败时，降级到规则检查
        print(f"[审阅Agent] DeepSeek 调用失败，降级到规则检查: {e}")
        return analyze_progress_fallback(progress, last_week_progress, item_name)


def analyze_progress_fallback(progress, last_week_progress, item_name) -> List[dict]:
    """规则版兜底（DeepSeek 不可用时的降级方案）"""
    suggestions = []
    if not progress.progress.strip() or len(progress.progress.strip()) < 5:
        suggestions.append({"type": "warning", "field": "progress",
                            "message": f"「{item_name}」的本周进展描述太简短，建议补充具体做了什么、取得了什么成果。"})
    has_numbers = any(c.isdigit() for c in progress.progress)
    if progress.progress.strip() and not has_numbers:
        suggestions.append({"type": "suggestion", "field": "progress",
                            "message": f"「{item_name}」的进展描述可以补充量化数据，比如完成了多少、达成率多少。"})
    if last_week_progress and last_week_progress.next_plan.strip():
        if last_week_progress.next_plan.strip() not in progress.progress:
            suggestions.append({"type": "question", "field": "progress",
                                "message": f"上周你在「{item_name}」计划「{last_week_progress.next_plan[:50]}...」，本周进展似乎没提到，是未推进还是漏了？"})
    if not progress.next_plan.strip():
        suggestions.append({"type": "reminder", "field": "next_plan",
                            "message": f"「{item_name}」缺少下阶段工作计划，建议补充下周准备做什么。"})
    return suggestions


@router.post("/agent/review")
def agent_review(data: ReviewRequest, db: Session = Depends(get_db)):
    user_items = db.query(WorkItem).filter(WorkItem.owner_id == data.user_id).all()
    last_week = (datetime.strptime(data.week_start, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    all_suggestions = []
    for item in user_items:
        progress = db.query(WeeklyProgress).filter(
            WeeklyProgress.work_item_id == item.id,
            WeeklyProgress.week_start == data.week_start).first()
        if not progress:
            continue
        last_progress = db.query(WeeklyProgress).filter(
            WeeklyProgress.work_item_id == item.id,
            WeeklyProgress.week_start == last_week).first()
        suggestions = analyze_progress_with_ai(progress, last_progress, item.name)
        for s in suggestions:
            s["work_item_id"] = item.id
            s["work_item_name"] = item.name
        all_suggestions.extend(suggestions)
    return {"user_id": data.user_id, "week_start": data.week_start,
            "total_suggestions": len(all_suggestions), "suggestions": all_suggestions}


# ========== 信息提炼 Agent（累计） ==========
@router.get("/agent/extract")
def agent_extract(week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """信息提炼：返回所有累计制工作的 本周值 + 累计值"""
    if not week_start:
        week_start = get_current_week_start()
    items = db.query(WorkItem).filter(WorkItem.is_cumulative == 1).all()
    result = []
    for item in items:
        metrics = json.loads(item.cum_metrics) if item.cum_metrics else []
        cum_value = calc_cumulative(db, item.id, week_start)
        result.append({
            "work_item_id": item.id,
            "work_item_name": item.name,
            "owner_name": item.owner.name if item.owner else "",
            "cum_metrics": metrics,
            "cum_value": cum_value,
        })
    return result


# ========== 汇报视图聚合 ==========
@router.get("/agent/dashboard")
def agent_dashboard(week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """管理者汇报视图：关键数据 + 重点工作 + 日常明细 + 待办决策"""
    if not week_start:
        week_start = get_current_week_start()

    users = db.query(User).all()
    items = db.query(WorkItem).all()

    # 1. 关键数据（各累计指标汇总）
    key_metrics = {"offer": 0, "onboard": 0, "count": 0, "times": 0, "people": 0}
    for item in items:
        if item.is_cumulative:
            cum = calc_cumulative(db, item.id, week_start)
            for k, v in cum.items():
                if k in key_metrics:
                    key_metrics[k] += v

    # 2. 重点工作（按目标分组）
    goals = {}
    for item in items:
        if item.category == "年度重点工作" or item.category == "自主专项工作":
            gid = item.goal_id or 0
            if gid not in goals:
                goal = db.query(WorkItem.goal).first() if False else None
                goals[gid] = []
            cum = calc_cumulative(db, item.id, week_start) if item.is_cumulative else {}
            goals[gid].append({
                "id": item.id, "name": item.name, "category": item.category,
                "importance": item.importance, "owner_name": item.owner.name if item.owner else "",
                "status": compute_status(item), "due_date": item.due_date,
                "is_cumulative": item.is_cumulative,
                "cum_metrics": json.loads(item.cum_metrics) if item.cum_metrics else [],
                "cum_value": cum,
            })

    # 3. 日常工作明细（按人分组）
    members = []
    for u in users:
        u_items = [it for it in items if it.owner_id == u.id]
        member_items = []
        for it in u_items:
            cum = calc_cumulative(db, it.id, week_start) if it.is_cumulative else {}
            member_items.append({
                "id": it.id, "name": it.name, "category": it.category,
                "importance": it.importance, "status": compute_status(it),
                "is_cumulative": it.is_cumulative,
                "cum_metrics": json.loads(it.cum_metrics) if it.cum_metrics else [],
                "cum_value": cum,
            })
        members.append({
            "id": u.id, "name": u.name, "role": u.role,
            "business_line": u.business_line, "avatar_color": u.avatar_color,
            "items": member_items,
        })

    # 4. 待办 + 决策
    todos = db.query(Todo).order_by(Todo.created_at.desc()).all()
    todo_list = [{"id": t.id, "content": t.content, "status": t.status,
                  "due_date": t.due_date, "owner_name": t.owner.name if hasattr(t, 'owner') else ""} for t in todos]

    # 从本周进展中提取"需决策/需支持"
    decisions = []
    progresses = db.query(WeeklyProgress).filter(WeeklyProgress.week_start == week_start).all()
    for p in progresses:
        if p.blockers and ("决策" in p.blockers or "待" in p.blockers or "需" in p.blockers):
            item = db.query(WorkItem).filter(WorkItem.id == p.work_item_id).first()
            decisions.append({
                "work_item_name": item.name if item else "",
                "content": p.blockers,
            })

    return {
        "week_start": week_start,
        "key_metrics": key_metrics,
        "goals": goals,
        "members": members,
        "todos": todo_list,
        "decisions": decisions,
    }


# ========== 提交状态（催办 Agent） ==========
@router.get("/agent/submit-status")
def agent_check_status(week_start: Optional[str] = None, db: Session = Depends(get_db)):
    if not week_start:
        week_start = get_current_week_start()
    users = db.query(User).all()
    submitted, not_submitted = [], []
    for user in users:
        status = db.query(WeeklySubmitStatus).filter(
            WeeklySubmitStatus.user_id == user.id,
            WeeklySubmitStatus.week_start == week_start).first()
        if status and status.status == "submitted":
            submitted.append(user.name)
        else:
            not_submitted.append({"name": user.name, "role": user.role, "business_line": user.business_line})
    return {"week_start": week_start, "all_submitted": len(not_submitted) == 0,
            "submitted": submitted, "not_submitted": not_submitted, "total": len(users)}


# ========== 待办 ==========
class TodoCreate(BaseModel):
    content: str
    owner_id: int
    due_date: str = ""
    week_start: str = ""


@router.get("/agent/todos")
def list_todos(db: Session = Depends(get_db)):
    todos = db.query(Todo).order_by(Todo.created_at.desc()).all()
    return [{"id": t.id, "content": t.content, "owner_id": t.owner_id,
             "due_date": t.due_date, "status": t.status, "week_start": t.week_start} for t in todos]


@router.post("/agent/todos")
def create_todo(data: TodoCreate, db: Session = Depends(get_db)):
    todo = Todo(content=data.content, owner_id=data.owner_id,
                due_date=data.due_date, week_start=data.week_start)
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return {"id": todo.id, "message": "待办已创建"}


@router.put("/agent/todos/{todo_id}/status")
def update_todo_status(todo_id: int, status: str, db: Session = Depends(get_db)):
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        return {"error": "待办不存在"}
    todo.status = status
    db.commit()
    return {"message": "状态已更新"}


# ========== 反馈规则库（Agent进化） ==========
class FeedbackCreate(BaseModel):
    content: str
    source: str = "纠正"
    agent: str = ""


@router.get("/agent/feedback-rules")
def list_feedback_rules(db: Session = Depends(get_db)):
    rules = db.query(FeedbackRule).order_by(FeedbackRule.created_at.desc()).all()
    return [{"id": r.id, "content": r.content, "source": r.source,
             "agent": r.agent, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rules]


@router.post("/agent/feedback-rules")
def create_feedback_rule(data: FeedbackCreate, db: Session = Depends(get_db)):
    rule = FeedbackRule(content=data.content, source=data.source, agent=data.agent)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": rule.id, "message": "规则已沉淀"}
