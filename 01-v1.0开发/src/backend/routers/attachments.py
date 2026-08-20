"""附件相关API：上传、列表、下载"""
from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from models import get_db, Attachment, WorkItem
from typing import Optional
import os, shutil, uuid
from datetime import datetime

router = APIRouter()

# 附件存储目录（backend 同级 uploads）
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "uploads")
UPLOAD_DIR = os.path.abspath(UPLOAD_DIR)
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/attachments")
async def upload_attachment(
    file: UploadFile = File(...),
    work_item_id: int = Form(...),
    week_start: str = Form(""),
    uploaded_by: int = Form(...),
    db: Session = Depends(get_db),
):
    """上传附件，关联到工作事项和周"""
    # 生成唯一文件名，保留原始扩展名
    ext = os.path.splitext(file.filename or "")[1]
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = os.path.join(UPLOAD_DIR, stored_name)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    att = Attachment(
        work_item_id=work_item_id,
        filename=file.filename or stored_name,
        stored_name=stored_name,
        week_start=week_start,
        uploaded_by=uploaded_by,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return {"id": att.id, "filename": att.filename, "message": "上传成功"}


@router.get("/attachments")
def list_attachments(work_item_id: Optional[int] = None, week_start: Optional[str] = None, db: Session = Depends(get_db)):
    """列出附件（可按工作事项、周过滤）"""
    query = db.query(Attachment)
    if work_item_id:
        query = query.filter(Attachment.work_item_id == work_item_id)
    if week_start:
        query = query.filter(Attachment.week_start == week_start)
    atts = query.order_by(Attachment.uploaded_at.desc()).all()
    return [{"id": a.id, "filename": a.filename, "work_item_id": a.work_item_id,
             "week_start": a.week_start, "uploaded_by": a.uploaded_by,
             "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None} for a in atts]


@router.get("/attachments/{att_id}/download")
def download_attachment(att_id: int, db: Session = Depends(get_db)):
    att = db.query(Attachment).filter(Attachment.id == att_id).first()
    if not att:
        return {"error": "附件不存在"}
    path = os.path.join(UPLOAD_DIR, att.stored_name)
    if not os.path.exists(path):
        return {"error": "文件已丢失"}
    return FileResponse(path, filename=att.filename)
