import csv
import io
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, extract
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_super_admin, require_admin, get_current_user
from app.models.models import User, Department, Document, AuditLog, ChatMessage, ChatSession
from app.schemas.schemas import (
    UserOut, UserUpdate, DepartmentCreate, DepartmentOut, AuditLogOut, DocumentOut
)

router = APIRouter(prefix="/admin", tags=["admin"])


# ─── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=List[UserOut])
def list_users(
    skip: int = 0,
    limit: int = 50,
    dept_id: Optional[UUID] = None,
    role: Optional[str] = None,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if dept_id:
        query = query.filter(User.dept_id == dept_id)
    if role:
        query = query.filter(User.role == role)
    return query.order_by(User.created_at.desc()).offset(skip).limit(limit).all()


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.name is not None:
        user.name = payload.name
    if payload.role is not None:
        if payload.role not in ("user", "dept_admin", "super_admin"):
            raise HTTPException(status_code=400, detail="Invalid role")
        user.role = payload.role
    if payload.dept_id is not None:
        dept = db.query(Department).filter(Department.id == payload.dept_id).first()
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        user.dept_id = payload.dept_id
    if payload.is_active is not None:
        user.is_active = payload.is_active

    audit = AuditLog(
        actor_id=current_user.id,
        actor_email=current_user.email,
        action="admin.user_update",
        target_type="user",
        target_id=str(user_id),
        extra_data=payload.model_dump(exclude_none=True),
    )
    db.add(audit)
    db.commit()
    db.refresh(user)
    return user


# ─── Departments ───────────────────────────────────────────────────────────────

@router.get("/departments", response_model=List[DepartmentOut])
def list_departments(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return db.query(Department).order_by(Department.created_at.desc()).all()


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(
    payload: DepartmentCreate,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    existing = db.query(Department).filter(Department.slug == payload.slug).first()
    if existing:
        raise HTTPException(status_code=409, detail="Department slug already exists")

    dept = Department(
        name=payload.name,
        slug=payload.slug,
        storage_quota_mb=payload.storage_quota_mb,
    )
    db.add(dept)

    audit = AuditLog(
        actor_id=current_user.id,
        actor_email=current_user.email,
        action="admin.department_create",
        target_type="department",
        target_id=payload.slug,
    )
    db.add(audit)
    db.commit()
    db.refresh(dept)
    return dept


@router.delete("/departments/{dept_id}", status_code=204)
def delete_department(
    dept_id: UUID,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    db.delete(dept)
    db.commit()


# ─── Documents ─────────────────────────────────────────────────────────────────

@router.get("/documents", response_model=List[DocumentOut])
def list_all_documents(
    skip: int = 0,
    limit: int = 50,
    dept_id: Optional[UUID] = None,
    status: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Document)
    if dept_id:
        query = query.filter(Document.dept_id == dept_id)
    if status:
        query = query.filter(Document.status == status)
    return query.order_by(Document.created_at.desc()).offset(skip).limit(limit).all()


# ─── Audit Log ─────────────────────────────────────────────────────────────────

@router.get("/audit-log", response_model=List[AuditLogOut])
def get_audit_log(
    skip: int = 0,
    limit: int = 50,
    action: Optional[str] = None,
    actor_email: Optional[str] = None,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    if actor_email:
        query = query.filter(AuditLog.actor_email.ilike(f"%{actor_email}%"))
    return query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()


# ─── Phase 2: Admin Analytics Endpoints ────────────────────────────────────────

@router.get("/department-comparison")
def department_comparison(
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Side-by-side comparison of all departments: doc count, query volume, avg confidence, top question."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    departments = db.query(Department).all()
    results = []
    for dept in departments:
        doc_count = db.query(Document).filter(
            Document.dept_id == dept.id, Document.status == "indexed"
        ).count()
        query_count = (
            db.query(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .filter(
                ChatSession.dept_id == dept.id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= thirty_days_ago,
            )
            .count()
        )
        avg_conf = db.query(func.avg(ChatMessage.confidence)).join(
            ChatSession, ChatSession.id == ChatMessage.session_id
        ).filter(
            ChatSession.dept_id == dept.id,
            ChatMessage.role == "assistant",
            ChatMessage.confidence.isnot(None),
            ChatMessage.created_at >= thirty_days_ago,
        ).scalar() or 0

        top_query_msg = (
            db.query(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .filter(ChatSession.dept_id == dept.id, ChatMessage.role == "user")
            .order_by(ChatMessage.created_at.desc())
            .first()
        )
        top_query = top_query_msg.content[:100] if top_query_msg else None

        results.append({
            "dept_id": str(dept.id),
            "dept_name": dept.name,
            "doc_count": doc_count,
            "query_count_30d": query_count,
            "avg_confidence": round(float(avg_conf), 3),
            "top_question": top_query,
        })
    return results


@router.get("/query-volume")
def admin_query_volume(
    days: int = 30,
    dept_id: Optional[str] = None,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Platform-wide or per-department daily query volume time-series."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = (
        db.query(
            func.date(ChatMessage.created_at).label("date"),
            func.count(ChatMessage.id).label("count"),
        )
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(ChatMessage.role == "user", ChatMessage.created_at >= since)
    )
    if dept_id:
        q = q.filter(ChatSession.dept_id == dept_id)
    rows = q.group_by(func.date(ChatMessage.created_at)).order_by(func.date(ChatMessage.created_at)).all()
    return [{"date": str(r.date), "count": r.count} for r in rows]


@router.get("/unanswered-queries")
def unanswered_queries(
    limit: int = 20,
    confidence_threshold: float = 0.4,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Low-confidence queries across all departments — knowledge gap signals."""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    low_conf = (
        db.query(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(
            ChatMessage.role == "assistant",
            ChatMessage.confidence < confidence_threshold,
            ChatMessage.created_at >= thirty_days_ago,
        )
        .order_by(ChatMessage.confidence.asc())
        .limit(limit)
        .all()
    )
    results = []
    for msg in low_conf:
        user_q = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == msg.session_id, ChatMessage.role == "user", ChatMessage.created_at < msg.created_at)
            .order_by(ChatMessage.created_at.desc())
            .first()
        )
        dept = db.query(Department).join(ChatSession, ChatSession.dept_id == Department.id).filter(ChatSession.id == msg.session_id).first()
        results.append({
            "query": user_q.content[:200] if user_q else "(unknown)",
            "confidence": round(msg.confidence or 0, 3),
            "dept_name": dept.name if dept else None,
            "date": msg.created_at.isoformat() if msg.created_at else None,
        })
    return results


@router.get("/active-users-heatmap")
def active_users_heatmap(
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """
    Hour-of-day × day-of-week query density matrix.
    Returns matrix[day_of_week (0=Mon)][hour (0-23)] = query_count.
    """
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    # Initialize 7×24 matrix
    matrix = [[0] * 24 for _ in range(7)]

    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.role == "user", ChatMessage.created_at >= thirty_days_ago)
        .all()
    )
    for msg in rows:
        if msg.created_at:
            ts = msg.created_at
            dow = ts.weekday()   # 0=Monday
            hour = ts.hour
            matrix[dow][hour] += 1

    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return [
        {"day": days[d], "day_index": d, "hours": [{"hour": h, "count": matrix[d][h]} for h in range(24)]}
        for d in range(7)
    ]


@router.get("/export")
def admin_export(
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Platform-wide admin report export (CSV or PDF)."""
    since = datetime.now(timezone.utc) - timedelta(days=30)
    if from_date:
        try:
            since = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    until = datetime.now(timezone.utc)
    if to_date:
        try:
            until = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    departments = db.query(Department).all()

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Department", "Total Docs", "Queries (period)", "Avg Confidence"])
        for dept in departments:
            doc_count = db.query(Document).filter(Document.dept_id == dept.id, Document.status == "indexed").count()
            q_count = (
                db.query(ChatMessage)
                .join(ChatSession, ChatSession.id == ChatMessage.session_id)
                .filter(ChatSession.dept_id == dept.id, ChatMessage.role == "user", ChatMessage.created_at.between(since, until))
                .count()
            )
            avg_c = db.query(func.avg(ChatMessage.confidence)).join(
                ChatSession, ChatSession.id == ChatMessage.session_id
            ).filter(ChatSession.dept_id == dept.id, ChatMessage.role == "assistant", ChatMessage.created_at.between(since, until)).scalar() or 0
            writer.writerow([dept.name, doc_count, q_count, round(float(avg_c), 3)])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=admin_export.csv"},
        )

    # PDF
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("OrgMind Admin Report", styles["Title"]),
        Paragraph(f"Period: {since.date()} to {until.date()}", styles["Normal"]),
        Spacer(1, 12),
    ]
    data = [["Department", "Docs", "Queries", "Avg Confidence"]]
    for dept in departments:
        doc_count = db.query(Document).filter(Document.dept_id == dept.id, Document.status == "indexed").count()
        q_count = (
            db.query(ChatMessage).join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .filter(ChatSession.dept_id == dept.id, ChatMessage.role == "user", ChatMessage.created_at.between(since, until)).count()
        )
        avg_c = db.query(func.avg(ChatMessage.confidence)).join(
            ChatSession, ChatSession.id == ChatMessage.session_id
        ).filter(ChatSession.dept_id == dept.id, ChatMessage.role == "assistant", ChatMessage.created_at.between(since, until)).scalar() or 0
        data.append([dept.name, str(doc_count), str(q_count), f"{float(avg_c):.2f}"])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))
    story.append(tbl)
    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=admin_report.pdf"},
    )
