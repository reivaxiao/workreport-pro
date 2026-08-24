"""AI智能体相关API：审阅、信息提炼（累计）、汇报视图聚合、待办、反馈"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, WeeklyProgress, WeeklySubmitStatus, WorkItem, User, Annotation, Todo, FeedbackRule, Attachment, WeeklySummary
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


def analyze_progress_with_ai(progress, last_week_progress, item, db) -> List[dict]:
    """调用 DeepSeek 审阅单条工作事项，返回结构化建议列表"""
    try:
        from agents.deepseek_client import build_review_messages, chat_json
        # 累计指标
        cum_metrics = json.loads(item.cum_metrics) if item.cum_metrics else []
        # 是否上传了附件
        has_attachment = db.query(Attachment).filter(
            Attachment.work_item_id == item.id).count() > 0
        # 员工板块
        business_line = item.owner.business_line if item.owner else ""

        messages = build_review_messages(
            item_name=item.name,
            category=item.category,
            is_cumulative=item.is_cumulative,
            cum_metrics=cum_metrics,
            business_line=business_line,
            has_attachment=has_attachment,
            progress=progress.progress,
            next_plan=progress.next_plan,
            blockers=progress.blockers,
            last_week_progress=last_week_progress.progress if last_week_progress else "",
            last_week_next_plan=last_week_progress.next_plan if last_week_progress else "",
        )
        result = chat_json(messages)
        if isinstance(result, list):
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
        return analyze_progress_fallback(progress, last_week_progress, item.name)


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
        suggestions = analyze_progress_with_ai(progress, last_progress, item, db)
        for s in suggestions:
            s["work_item_id"] = item.id
            s["work_item_name"] = item.name
        all_suggestions.extend(suggestions)
    return {"user_id": data.user_id, "week_start": data.week_start,
            "total_suggestions": len(all_suggestions), "suggestions": all_suggestions}


# ========== 提炼（润色）接口：员工端辅助 ==========
class PolishRequest(BaseModel):
    work_item_id: int
    text: str


@router.post("/agent/polish")
def agent_polish(data: PolishRequest, db: Session = Depends(get_db)):
    """员工端"AI 提炼"：只润色文字，不追问、不审阅"""
    item = db.query(WorkItem).filter(WorkItem.id == data.work_item_id).first()
    if not item:
        return {"error": "事项不存在"}
    if not data.text.strip():
        return {"refined": ""}
    try:
        from agents.deepseek_client import build_polish_messages, chat
        business_line = item.owner.business_line if item.owner else ""
        messages = build_polish_messages(item.name, business_line, data.text)
        refined = chat(messages, max_tokens=500)
        return {"refined": refined.strip() if refined else ""}
    except Exception as e:
        print(f"[提炼] DeepSeek 调用失败: {e}")
        return {"refined": ""}


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


# ========== 信息提炼 Agent（横向汇总） ==========
@router.get("/agent/summarize")
def agent_summarize(week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """横向汇总：同类累计制工作按板块/人分组汇总。
    例如：三个 BP 都做员工访谈，汇总成「营销访谈X人、产研X人、运营X人」。
    """
    if not week_start:
        week_start = get_current_week_start()
    items = db.query(WorkItem).filter(WorkItem.is_cumulative == 1).all()

    # 按"累计指标 key"归类，如 count=访谈人次, offer=Offer数, onboard=入职数
    metric_groups = {}
    for item in items:
        metrics = json.loads(item.cum_metrics) if item.cum_metrics else []
        cum = calc_cumulative(db, item.id, week_start)
        owner = item.owner
        for m in metrics:
            key = m.get("key")
            if not key:
                continue
            if key not in metric_groups:
                metric_groups[key] = {"label": m.get("label", key), "unit": m.get("unit", ""), "members": [], "total": 0}
            val = cum.get(key, 0)
            metric_groups[key]["members"].append({
                "owner_name": owner.name if owner else "",
                "business_line": owner.business_line if owner else "",
                "work_item_name": item.name,
                "value": val,
            })
            metric_groups[key]["total"] += val

    result = []
    for key, g in metric_groups.items():
        result.append({
            "metric_key": key,
            "label": g["label"],
            "unit": g["unit"],
            "total": g["total"],
            "members": g["members"],
        })
    return result


# ========== 管理者一键审阅 ==========
class ManagerReviewRequest(BaseModel):
    week_start: str


@router.post("/agent/manager-review")
def agent_manager_review(data: ManagerReviewRequest, db: Session = Depends(get_db)):
    """管理者一键审阅：审全员周报，返回结构化审阅意见"""
    week_start = data.week_start
    users = db.query(User).all()
    items = db.query(WorkItem).all()

    # 1. 横向汇总（文本化）
    summarize = agent_summarize(week_start, db)
    summarize_text = ""
    for g in summarize:
        parts = [f"{m['business_line'] or m['owner_name']}{g['label']}{m['value']}{g['unit']}" for m in g['members'] if m['value'] > 0]
        if parts:
            summarize_text += f"- {g['label']}：{'、'.join(parts)}（合计{g['total']}{g['unit']}）\n"

    # 2. 各成员本周工作（文本化）
    members_text = ""
    for u in users:
        u_items = [it for it in items if it.owner_id == u.id]
        member_lines = []
        for it in u_items:
            prog = db.query(WeeklyProgress).filter(
                WeeklyProgress.work_item_id == it.id,
                WeeklyProgress.week_start == week_start).first()
            if prog and prog.progress.strip():
                st = compute_status(it)
                member_lines.append(f"  - {it.name}（{st}）：{prog.progress.strip()[:80]}")
        if member_lines:
            members_text += f"{u.name}（{u.business_line or u.role}）：\n" + "\n".join(member_lines) + "\n"

    if not summarize_text and not members_text:
        return {"week_start": week_start, "total": 0, "suggestions": []}

    try:
        from agents.deepseek_client import build_manager_review_messages, chat_json
        messages = build_manager_review_messages(summarize_text, members_text)
        result = chat_json(messages, max_tokens=3000)

        summary = ""
        suggestions = []
        if isinstance(result, dict):
            # 新格式：{summary, suggestions}
            summary = result.get("summary", "")
            raw_suggestions = result.get("suggestions", [])
            if isinstance(raw_suggestions, list):
                for r in raw_suggestions:
                    if isinstance(r, dict) and r.get("message"):
                        suggestions.append({
                            "type": r.get("type", "进度"),
                            "target": r.get("target", ""),
                            "message": r["message"],
                        })
        elif isinstance(result, list):
            # 兼容旧格式：纯数组
            for r in result:
                if isinstance(r, dict) and r.get("message"):
                    suggestions.append({
                        "type": r.get("type", "进度"),
                        "target": r.get("target", ""),
                        "message": r["message"],
                    })
        return {"week_start": week_start, "summary": summary,
                "total": len(suggestions), "suggestions": suggestions}
    except Exception as e:
        print(f"[管理者审阅] DeepSeek 调用失败: {e}")
        return {"week_start": week_start, "summary": "", "total": 0, "suggestions": []}


# ========== 周汇报稿（保存/读取） ==========
class SummarySaveRequest(BaseModel):
    week_start: str
    content: str


@router.post("/agent/save-summary")
def save_summary(data: SummarySaveRequest, db: Session = Depends(get_db)):
    """保存管理者编辑后的汇报稿"""
    existing = db.query(WeeklySummary).filter(WeeklySummary.week_start == data.week_start).first()
    if existing:
        existing.content = data.content
    else:
        db.add(WeeklySummary(week_start=data.week_start, content=data.content))
    db.commit()
    return {"message": "已保存"}


@router.get("/agent/get-summary")
def get_summary(week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """读取某周的汇报稿"""
    if not week_start:
        week_start = get_current_week_start()
    existing = db.query(WeeklySummary).filter(WeeklySummary.week_start == week_start).first()
    return {"week_start": week_start, "content": existing.content if existing else ""}


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
