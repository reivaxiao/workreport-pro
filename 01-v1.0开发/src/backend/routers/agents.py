"""AI智能体相关API：审阅、信息提炼（累计）、汇报视图聚合、待办、反馈"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, WeeklyProgress, WeeklySubmitStatus, WorkItem, User, Annotation, Todo, FeedbackRule, Attachment, WeeklySummary, AnnualGoal, KeyWorkText
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
    try:
        due = datetime.strptime(item.due_date, "%Y-%m-%d")
    except ValueError:
        return "进行中"
    if (due - datetime.now()).days <= 7:
        return "临期"
    return "进行中"


_STATUS_RANK = {"延期": 3, "临期": 2, "进行中": 1, "已完成": 0, "暂停": 0, "终止": 0}


def worst_status(a: str, b: str) -> str:
    """返回两个状态中较严重的一个"""
    return a if _STATUS_RANK.get(a, 0) >= _STATUS_RANK.get(b, 0) else b


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
        # max_tokens 需足够大：推理型模型会先占用大量 token 思考，3000 会导致正式答案被截断
        result = chat_json(messages, max_tokens=8000)

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
        # 自动保存汇报稿（供汇报视图横幅直接读取）
        if summary:
            existing = db.query(WeeklySummary).filter(WeeklySummary.week_start == week_start).first()
            if existing:
                existing.content = summary
            else:
                db.add(WeeklySummary(week_start=week_start, content=summary))
            db.commit()
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


# ========== 重点工作汇报文字（管理者修改） ==========
class KeyWorkTextSave(BaseModel):
    work_item_id: int
    week_start: str
    content: str


@router.post("/agent/key-work-text")
def save_key_work_text(data: KeyWorkTextSave, db: Session = Depends(get_db)):
    """保存管理者对某个重点工作项的汇报文字（不影响员工原始周报）"""
    existing = db.query(KeyWorkText).filter(
        KeyWorkText.work_item_id == data.work_item_id,
        KeyWorkText.week_start == data.week_start).first()
    if existing:
        existing.content = data.content
    else:
        db.add(KeyWorkText(work_item_id=data.work_item_id,
                           week_start=data.week_start, content=data.content))
    db.commit()
    return {"message": "已保存"}


@router.get("/agent/key-work-texts")
def list_key_work_texts(week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """读取某周所有重点工作项的管理者修改文字"""
    if not week_start:
        week_start = get_current_week_start()
    rows = db.query(KeyWorkText).filter(KeyWorkText.week_start == week_start).all()
    return {r.work_item_id: r.content for r in rows}


@router.get("/agent/auto-summary")
def auto_summary(week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """汇报视图打开时调用：若全员已提交且汇报稿未生成，则自动生成。
    返回 {generated: bool, content: str, all_submitted: bool, not_submitted: [...]}
    """
    if not week_start:
        week_start = get_current_week_start()

    # 检查提交状态
    status = agent_check_status(week_start, db)
    all_submitted = status["all_submitted"]
    not_submitted = status["not_submitted"]

    # 已生成则直接返回
    existing = db.query(WeeklySummary).filter(WeeklySummary.week_start == week_start).first()
    if existing and existing.content.strip():
        return {"generated": False, "content": existing.content,
                "all_submitted": all_submitted, "not_submitted": not_submitted}

    # 未全员提交则等待
    if not all_submitted:
        return {"generated": False, "content": "",
                "all_submitted": False, "not_submitted": not_submitted}

    # 全员已提交但未生成 → 自动生成
    req = ManagerReviewRequest(week_start=week_start)
    result = agent_manager_review(req, db)
    return {"generated": True, "content": result.get("summary", ""),
            "all_submitted": True, "not_submitted": []}


# ========== 汇报视图聚合 ==========
@router.get("/agent/dashboard")
def agent_dashboard(week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """管理者汇报视图：关键数据 + 重点工作 + 日常明细 + 待办决策"""
    if not week_start:
        week_start = get_current_week_start()

    users = db.query(User).all()
    items = db.query(WorkItem).all()
    # 活跃事项（未办结）：用于关键数据、重点工作、日常明细
    # 已完成的事项只体现在目标考核（永久保留），不再出现在周报/汇报视图的工作明细里
    active_items = [it for it in items if it.status != "已完成"]

    # 1. 关键数据（各累计指标汇总）
    key_metrics = {"offer": 0, "onboard": 0, "count": 0, "times": 0, "people": 0}
    for item in active_items:
        if item.is_cumulative:
            cum = calc_cumulative(db, item.id, week_start)
            for k, v in cum.items():
                if k in key_metrics:
                    key_metrics[k] += v

    # 2. 重点工作（不绑定组织目标，按二级模块合并成一条整体）
    key_works = []
    key_groups = {}
    for item in items:
        if item.category in ("年度重点工作", "年度专项工作", "自主专项工作"):
            m2 = item.module2 or item.name
            cum = calc_cumulative(db, item.id, week_start) if item.is_cumulative else {}
            if m2 not in key_groups:
                key_groups[m2] = {
                    "id": item.id, "name": m2, "category": item.category,
                    "importance": item.importance,
                    "status": compute_status(item), "due_date": item.due_date,
                    "is_cumulative": item.is_cumulative,
                    "cum_metrics": json.loads(item.cum_metrics) if item.cum_metrics else [],
                    "cum_value": dict(cum),
                    "owners": [item.owner.name] if item.owner else [],
                    "members": [{
                        "id": item.id, "owner_name": item.owner.name if item.owner else "",
                        "business_line": item.owner.business_line if item.owner else "",
                        "status": compute_status(item),
                        "cum_value": cum,
                        "progress": "",
                    }],
                }
            else:
                g = key_groups[m2]
                for k, v in cum.items():
                    g["cum_value"][k] = g["cum_value"].get(k, 0) + v
                if item.owner and item.owner.name not in g["owners"]:
                    g["owners"].append(item.owner.name)
                g["members"].append({
                    "id": item.id, "owner_name": item.owner.name if item.owner else "",
                    "business_line": item.owner.business_line if item.owner else "",
                    "status": compute_status(item),
                    "cum_value": cum,
                    "progress": "",
                })
                g["status"] = worst_status(g["status"], compute_status(item))
    # 补本周进展
    progresses = db.query(WeeklyProgress).filter(WeeklyProgress.week_start == week_start).all()
    prog_map = {}
    for p in progresses:
        prog_map[p.work_item_id] = p
    # 查询管理者修改文字 + 附件
    custom_texts = {r.work_item_id: r.content for r in db.query(KeyWorkText).filter(KeyWorkText.week_start == week_start).all()}
    all_atts = db.query(Attachment).all()
    att_map = {}
    for a in all_atts:
        att_map.setdefault(a.work_item_id, []).append({
            "id": a.id, "filename": a.filename,
            "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None,
        })

    for m2, g in key_groups.items():
        for mem in g["members"]:
            p = prog_map.get(mem["id"])
            if p:
                mem["progress"] = p.progress or ""
        # 该重点工作下所有成员 id（合并后可能多个 work_item）
        member_ids = [mem["id"] for mem in g["members"]]
        # 管理者修改文字：取第一个有记录的成员
        custom_text = ""
        for mid in member_ids:
            if mid in custom_texts:
                custom_text = custom_texts[mid]
                break
        # 附件：汇总所有成员的附件
        attachments = []
        for mid in member_ids:
            for a in att_map.get(mid, []):
                attachments.append(a)
        key_works.append({
            "id": g["id"], "name": g["name"], "category": g["category"],
            "importance": g["importance"], "owners": g["owners"],
            "owner_names": "、".join(g["owners"]),
            "status": g["status"], "due_date": g["due_date"],
            "is_cumulative": g["is_cumulative"],
            "cum_metrics": g["cum_metrics"], "cum_value": g["cum_value"],
            "members": g["members"],
            "custom_text": custom_text,
            "attachments": attachments,
            "member_ids": member_ids,
        })

    # 2.5 目标考核（按年度目标分组，汇总所有关联该目标的工作，累计汇总）
    goal_review = []
    all_goals = db.query(AnnualGoal).order_by(AnnualGoal.weight.desc()).all()
    for goal in all_goals:
        goal_items = [it for it in items if it.goal_id == goal.id]
        if not goal_items:
            continue
        # 聚合该目标下所有工作的累计数据
        agg_cum = {}
        work_list = []
        for it in goal_items:
            cum = calc_cumulative(db, it.id, week_start) if it.is_cumulative else {}
            for k, v in cum.items():
                agg_cum[k] = agg_cum.get(k, 0) + v
            p = prog_map.get(it.id)
            work_list.append({
                "id": it.id, "name": it.name,
                "owner_name": it.owner.name if it.owner else "",
                "status": compute_status(it),
                "is_cumulative": it.is_cumulative,
                "cum_value": cum,
                "progress": p.progress if p else "",
            })
        goal_review.append({
            "goal_id": goal.id, "goal_name": goal.name, "weight": goal.weight,
            "kpis": goal.kpis,
            "agg_cum": agg_cum,
            "works": work_list,
        })

    # 3. 日常工作明细（按 职能 → 一级模块 → 二级模块 → 人 组织）
    # 先收集本周进展，用于补全字段
    progresses_all = db.query(WeeklyProgress).filter(WeeklyProgress.week_start == week_start).all()
    prog_map = {p.work_item_id: p for p in progresses_all}

    members = []
    for u in users:
        # 日常明细：用全部事项（含已完成），办结后不消失，只是状态变为已完成（可反悔改回）
        u_items = [it for it in items if it.owner_id == u.id]
        member_items = []
        for it in u_items:
            cum = calc_cumulative(db, it.id, week_start) if it.is_cumulative else {}
            p = prog_map.get(it.id)
            member_items.append({
                "id": it.id, "name": it.name, "category": it.category,
                "importance": it.importance, "status": compute_status(it),
                "is_cumulative": it.is_cumulative,
                "cum_metrics": json.loads(it.cum_metrics) if it.cum_metrics else [],
                "cum_value": cum,
                "function": it.function, "module1": it.module1, "module2": it.module2,
                "target_desc": it.target_desc, "due_date": it.due_date,
                "progress": p.progress if p else "",
                "next_plan": p.next_plan if p else "",
                "blockers": p.blockers if p else "",
            })
        members.append({
            "id": u.id, "name": u.name, "role": u.role,
            "business_line": u.business_line, "avatar_color": u.avatar_color,
            "items": member_items,
        })

    # 3.5 日常明细按 职能→一级模块→二级模块 重排（供前端分组渲染）
    daily_grouped = group_daily_by_module(members)

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
        "key_works": key_works,
        "goal_review": goal_review,
        "members": members,
        "daily_grouped": daily_grouped,
        "todos": todo_list,
        "decisions": decisions,
        "trend": calc_trend(db, week_start),
    }


def group_daily_by_module(members):
    """把日常明细按 职能 → 一级模块 → 二级模块 → 人 重排。
    返回 [{function, modules:[{module1, items:[{module2, work_item_name, owner_name, status, ...}]}]}]
    """
    # 结构：{职能: {一级模块: {二级模块: [工作项...]}}}
    tree = {}
    for m in members:
        for it in m["items"]:
            # 日常工作明细显示全部工作（重点/专项也在此展示，同时也在重点工作项目区汇总展示）
            func = it.get("function") or "未分类"
            m1 = it.get("module1") or "未分类"
            m2 = it.get("module2") or it["name"]
            tree.setdefault(func, {}).setdefault(m1, {}).setdefault(m2, []).append({
                "id": it["id"], "work_item_name": it["name"],
                "owner_name": m["name"], "avatar_color": m["avatar_color"],
                "status": it["status"], "importance": it["importance"],
                "category": it.get("category", ""),
                "cum_value": it["cum_value"], "is_cumulative": it["is_cumulative"],
                "target_desc": it.get("target_desc", ""),
                "due_date": it.get("due_date", ""),
                "progress": it.get("progress", ""),
                "next_plan": it.get("next_plan", ""),
                "blockers": it.get("blockers", ""),
            })
    result = []
    for func, modules in tree.items():
        mod_list = []
        for m1, m2s in modules.items():
            item_list = []
            for m2, works in m2s.items():
                item_list.append({"module2": m2, "works": works})
            mod_list.append({"module1": m1, "items": item_list})
        result.append({"function": func, "modules": mod_list})
    # 职能排序：招聘COE 在前，KA-HRBP 在后，其余按字母序
    func_order = {"招聘COE": 0, "KA-HRBP": 1}
    result.sort(key=lambda x: func_order.get(x["function"], 99))
    return result


def calc_trend(db: Session, week_start: str, weeks: int = 6) -> list:
    """计算近 N 周的累计指标走势，供趋势图使用。
    返回 [{week_label, offer, onboard, count, times, people}, ...] 按时间升序。
    """
    trend = []
    for i in range(weeks - 1, -1, -1):
        ws = (datetime.strptime(week_start, "%Y-%m-%d") - timedelta(days=7 * i)).strftime("%Y-%m-%d")
        monday = datetime.strptime(ws, "%Y-%m-%d")
        label = f"{monday.month}/{monday.day}"
        metrics = {"offer": 0, "onboard": 0, "count": 0, "times": 0, "people": 0}
        items = db.query(WorkItem).filter(WorkItem.is_cumulative == 1).all()
        for item in items:
            cum = calc_cumulative(db, item.id, ws)
            for k, v in cum.items():
                if k in metrics:
                    metrics[k] += v
        trend.append({"week_label": label, **metrics})
    return trend


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


# ========== 例会办结（管理者确认已完成） ==========
class CompleteRequest(BaseModel):
    manager_id: int
    week_start: Optional[str] = None


@router.post("/agent/items/{item_id}/complete")
def complete_item(item_id: int, data: CompleteRequest, db: Session = Depends(get_db)):
    """管理者在例会上确认某工作事项已完成，办结归档。
    办结后：status=已完成，记录完成周，周报不再出现，目标考核永久保留。"""
    manager = db.query(User).filter(User.id == data.manager_id).first()
    if not manager or not manager.is_manager:
        return {"success": False, "message": "仅业务管理者可办结"}
    item = db.query(WorkItem).filter(WorkItem.id == item_id).first()
    if not item:
        return {"success": False, "message": "事项不存在"}
    week_start = data.week_start or get_current_week_start()
    item.status = "已完成"
    item.completed_week = week_start
    db.commit()
    return {"success": True, "message": f"「{item.name}」已办结"}


@router.post("/agent/items/{item_id}/follow")
def follow_item(item_id: int, data: CompleteRequest, db: Session = Depends(get_db)):
    """管理者在例会上将已办结的工作改回"继续跟进"（进行中），反悔操作。"""
    manager = db.query(User).filter(User.id == data.manager_id).first()
    if not manager or not manager.is_manager:
        return {"success": False, "message": "仅业务管理者可操作"}
    item = db.query(WorkItem).filter(WorkItem.id == item_id).first()
    if not item:
        return {"success": False, "message": "事项不存在"}
    item.status = "进行中"
    item.completed_week = ""
    db.commit()
    return {"success": True, "message": f"「{item.name}」已改回继续跟进"}


# ========== 待办 ==========
class TodoCreate(BaseModel):
    content: str
    owner_id: int
    due_date: str = ""
    week_start: str = ""


@router.get("/agent/todos")
def list_todos(week_start: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    """列出待办，可按周、按状态过滤"""
    query = db.query(Todo)
    if week_start:
        query = query.filter(Todo.week_start == week_start)
    if status:
        query = query.filter(Todo.status == status)
    todos = query.order_by(Todo.created_at.asc()).all()
    result = []
    for t in todos:
        owner = db.query(User).filter(User.id == t.owner_id).first()
        result.append({
            "id": t.id, "content": t.content, "owner_id": t.owner_id,
            "owner_name": owner.name if owner else "",
            "work_item_name": t.work_item_name or "",
            "due_date": t.due_date, "status": t.status, "week_start": t.week_start,
        })
    return result


@router.post("/agent/todos")
def create_todo(data: TodoCreate, db: Session = Depends(get_db)):
    todo = Todo(content=data.content, owner_id=data.owner_id,
                due_date=data.due_date, week_start=data.week_start)
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return {"id": todo.id, "message": "待办已创建"}


# ========== 待办 Agent：AI 提取 + 回溯确认 ==========
class TodoExtractRequest(BaseModel):
    week_start: str


@router.post("/agent/extract-todos")
def extract_todos(data: TodoExtractRequest, db: Session = Depends(get_db)):
    """AI 从全员本周周报的「下阶段计划」提取待办，存入待办池。
    仅提取本周、当前没有待办的人员（幂等：已提取过的不重复提取）。"""
    week_start = data.week_start
    users = db.query(User).all()
    items = db.query(WorkItem).all()

    from agents.deepseek_client import build_todo_extract_messages, chat_json

    created_count = 0
    for u in users:
        # 该员工本周已提取过则跳过
        existing = db.query(Todo).filter(Todo.week_start == week_start, Todo.owner_id == u.id).first()
        if existing:
            continue
        # 收集该员工本周所有事项的「下阶段计划」
        u_items = [it for it in items if it.owner_id == u.id]
        next_plans = []
        for it in u_items:
            prog = db.query(WeeklyProgress).filter(
                WeeklyProgress.work_item_id == it.id,
                WeeklyProgress.week_start == week_start).first()
            plan = prog.next_plan if prog else ""
            if plan and plan.strip():
                next_plans.append({"item_name": it.name, "next_plan": plan})
        if not next_plans:
            continue

        try:
            messages = build_todo_extract_messages(u.name, next_plans)
            result = chat_json(messages, max_tokens=2000)
        except Exception:
            result = None

        if isinstance(result, list):
            for r in result:
                if isinstance(r, dict) and r.get("content"):
                    db.add(Todo(content=r["content"].strip(), owner_id=u.id,
                                work_item_name=r.get("work_item_name", "") or "",
                                due_date=r.get("due_date", "") or "",
                                week_start=week_start, status="进行中"))
                    created_count += 1
    db.commit()
    return {"message": f"已提取 {created_count} 条待办", "created": created_count}


class TodoReviewAction(BaseModel):
    action: str  # done=已完成 cancel=已取消 postpone=未完成顺延


@router.post("/agent/todos/{todo_id}/review")
def review_todo(todo_id: int, data: TodoReviewAction, week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """管理者在周会回溯时对上周待办做处理：
    - done：标记已完成
    - cancel：标记已取消
    - postpone：未完成，自动顺延到本周（复制一条到本周，原条目标记已完成）"""
    if not week_start:
        week_start = get_current_week_start()
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        return {"error": "待办不存在"}

    if data.action == "done":
        todo.status = "已完成"
    elif data.action == "cancel":
        todo.status = "已取消"
    elif data.action == "postpone":
        # 顺延：原条目标记已完成，复制一条到本周
        todo.status = "已完成"
        db.add(Todo(content=todo.content, owner_id=todo.owner_id,
                    due_date=todo.due_date, week_start=week_start, status="进行中"))
    db.commit()
    return {"message": "已处理"}


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
