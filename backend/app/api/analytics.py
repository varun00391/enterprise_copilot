import csv
import io
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.models import User, Document, ChatMessage, ChatSession, Department, CoverageGap
from app.services.analytics_refresh import (
    latest_department_analytics,
    refresh_all_for_department,
    count_queries_30d,
    count_docs_and_stale,
)
from app.schemas.schemas import (
    DashboardMetrics, RecentActivity, TopDocument, AdminDashboardMetrics, DepartmentStats
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _today_start():
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _week_start():
    return _today_start() - timedelta(days=7)


@router.get("/dashboard", response_model=DashboardMetrics)
def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dept_id = current_user.dept_id

    total_docs = db.query(Document).filter(
        Document.dept_id == dept_id,
        Document.status == "indexed",
    ).count()

    today_start = _today_start()
    questions_today = (
        db.query(ChatSession)
        .join(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .filter(
            ChatSession.dept_id == dept_id,
            ChatMessage.role == "user",
            ChatMessage.created_at >= today_start,
        )
        .count()
    )

    avg_conf_result = db.query(func.avg(ChatMessage.confidence)).join(
        ChatSession, ChatSession.id == ChatMessage.session_id
    ).filter(
        ChatSession.dept_id == dept_id,
        ChatMessage.role == "assistant",
        ChatMessage.confidence.isnot(None),
    ).scalar()
    avg_confidence = round(float(avg_conf_result or 0), 2)

    week_start = _week_start()
    docs_this_week = db.query(Document).filter(
        Document.dept_id == dept_id,
        Document.created_at >= week_start,
    ).count()

    pending = db.query(Document).filter(
        Document.dept_id == dept_id,
        Document.status.in_(["uploaded", "parsing", "chunking", "embedding"]),
    ).count()

    return DashboardMetrics(
        total_documents=total_docs,
        questions_today=questions_today,
        avg_confidence=avg_confidence,
        documents_this_week=docs_this_week,
        pending_documents=pending,
    )


@router.get("/recent-activity", response_model=List[RecentActivity])
def get_recent_activity(
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(
            ChatSession.user_id == current_user.id,
            ChatMessage.role == "user",
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )

    results = []
    for msg in rows:
        ai_reply = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == msg.session_id,
                ChatMessage.role == "assistant",
                ChatMessage.created_at > msg.created_at,
            )
            .order_by(ChatMessage.created_at)
            .first()
        )
        source_doc = None
        if ai_reply and ai_reply.source_chunks:
            chunks = ai_reply.source_chunks
            if chunks:
                source_doc = chunks[0].get("doc_name")

        results.append(RecentActivity(
            id=msg.id,
            query=msg.content[:150],
            answer_snippet=(ai_reply.content[:200] if ai_reply else "Processing..."),
            confidence=ai_reply.confidence if ai_reply else None,
            source_doc=source_doc,
            created_at=msg.created_at,
        ))
    return results


@router.get("/top-documents", response_model=List[TopDocument])
def get_top_documents(
    limit: int = 5,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    docs = (
        db.query(Document)
        .filter(Document.dept_id == current_user.dept_id, Document.status == "indexed")
        .order_by(Document.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        TopDocument(id=d.id, original_name=d.original_name, query_count=0, file_type=d.file_type)
        for d in docs
    ]


@router.get("/admin", response_model=AdminDashboardMetrics)
def get_admin_analytics(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total_users = db.query(User).filter(User.is_active == True).count()
    total_docs = db.query(Document).filter(Document.status == "indexed").count()

    today_start = _today_start()
    week_start = _week_start()

    queries_today = (
        db.query(ChatMessage)
        .filter(ChatMessage.role == "user", ChatMessage.created_at >= today_start)
        .count()
    )
    queries_week = (
        db.query(ChatMessage)
        .filter(ChatMessage.role == "user", ChatMessage.created_at >= week_start)
        .count()
    )

    avg_conf = db.query(func.avg(ChatMessage.confidence)).filter(
        ChatMessage.role == "assistant",
        ChatMessage.confidence.isnot(None),
    ).scalar()

    storage_bytes = db.query(func.sum(Document.file_size_bytes)).scalar() or 0

    departments = db.query(Department).all()
    dept_stats = []
    for dept in departments:
        u_count = db.query(User).filter(User.dept_id == dept.id).count()
        d_count = db.query(Document).filter(Document.dept_id == dept.id, Document.status == "indexed").count()
        q_count = (
            db.query(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .filter(ChatSession.dept_id == dept.id, ChatMessage.role == "user", ChatMessage.created_at >= today_start)
            .count()
        )
        dept_stats.append(DepartmentStats(
            id=dept.id,
            name=dept.name,
            slug=dept.slug,
            storage_quota_mb=dept.storage_quota_mb,
            created_at=dept.created_at,
            user_count=u_count,
            document_count=d_count,
            query_count_today=q_count,
        ))

    return AdminDashboardMetrics(
        total_users=total_users,
        total_documents=total_docs,
        total_queries_today=queries_today,
        total_queries_week=queries_week,
        avg_confidence=round(float(avg_conf or 0), 2),
        storage_used_mb=round(storage_bytes / (1024 * 1024), 2),
        departments=dept_stats,
    )


# ─── Phase 2: Department Knowledge Health Score ───────────────────────────────

@router.get("/knowledge-health")
def get_knowledge_health(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns Knowledge Health from the precomputed `department_analytics` snapshot
    plus live doc/query counts for display widgets.
    """
    dept_id = current_user.dept_id
    if not dept_id:
        return {
            "health_score": 0,
            "avg_confidence": 0,
            "coverage_gap_ratio": 0,
            "stale_doc_ratio": 0,
            "total_queries_30d": 0,
            "total_docs": 0,
            "stale_docs": 0,
            "snapshot_computed_at": None,
        }

    row = latest_department_analytics(db, dept_id)
    if row is None:
        refresh_all_for_department(db, dept_id)
        row = latest_department_analytics(db, dept_id)

    totals = count_docs_and_stale(db, dept_id)
    assistant_turns = count_queries_30d(db, dept_id)

    if row:
        health_score = round(float(row.health_score or 0), 1)
        avg_confidence = round(float(row.avg_confidence or 0), 3)
        coverage_gap_ratio = round(float(row.coverage_gap_ratio or 0), 3)
        stale_doc_ratio = round(float(row.stale_doc_ratio or 0), 3)
        computed_at = row.computed_at.isoformat() if row.computed_at else None
    else:
        health_score = avg_confidence = coverage_gap_ratio = stale_doc_ratio = 0
        computed_at = None

    return {
        "health_score": health_score,
        "avg_confidence": avg_confidence,
        "coverage_gap_ratio": coverage_gap_ratio,
        "stale_doc_ratio": stale_doc_ratio,
        "total_queries_30d": assistant_turns,
        "total_docs": totals["total_docs"],
        "stale_docs": totals["stale_docs"],
        "snapshot_computed_at": computed_at,
    }


@router.get("/coverage-gaps")
def get_coverage_gaps(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pre-aggregated coverage gaps for the user's department."""
    dept_id = current_user.dept_id
    if not dept_id:
        return []

    from app.services.analytics_refresh import refresh_coverage_gaps

    rows = (
        db.query(CoverageGap)
        .filter(CoverageGap.dept_id == dept_id)
        .order_by(CoverageGap.query_count.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        refresh_coverage_gaps(db, dept_id)
        rows = (
            db.query(CoverageGap)
            .filter(CoverageGap.dept_id == dept_id)
            .order_by(CoverageGap.query_count.desc())
            .limit(limit)
            .all()
        )

    return [
        {
            "query": r.query_topic[:200],
            "confidence": round(float(r.avg_confidence or 0), 3),
            "date": r.last_seen.isoformat() if r.last_seen else None,
            "occurrences": r.query_count,
        }
        for r in rows
    ]


@router.get("/document-freshness")
def get_document_freshness(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Documents older than freshness threshold — flagged with age in days."""
    dept_id = current_user.dept_id
    if not dept_id:
        return []

    threshold = datetime.now(timezone.utc) - timedelta(days=settings.DOCUMENT_FRESHNESS_THRESHOLD_DAYS)
    stale = (
        db.query(Document)
        .filter(
            Document.dept_id == dept_id,
            Document.status == "indexed",
            Document.created_at < threshold,
        )
        .order_by(Document.created_at.asc())
        .limit(50)
        .all()
    )

    now = datetime.now(timezone.utc)
    return [
        {
            "id": str(d.id),
            "name": d.original_name,
            "file_type": d.file_type,
            "age_days": (now - d.created_at.replace(tzinfo=timezone.utc)).days if d.created_at else 0,
            "uploaded_at": d.created_at.isoformat() if d.created_at else None,
            "source_type": d.source_type or "upload",
        }
        for d in stale
    ]


@router.get("/contributors")
def get_contributors(
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Most active document uploaders in the department this month."""
    dept_id = current_user.dept_id
    if not dept_id:
        return []

    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(Document.uploaded_by, func.count(Document.id).label("doc_count"))
        .filter(
            Document.dept_id == dept_id,
            Document.status == "indexed",
            Document.created_at >= month_start,
        )
        .group_by(Document.uploaded_by)
        .order_by(func.count(Document.id).desc())
        .limit(limit)
        .all()
    )

    results = []
    for user_id, count in rows:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            results.append({"user_id": str(user_id), "name": user.name, "email": user.email, "doc_count": count})
    return results


@router.get("/query-trend")
def get_query_trend(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Daily query volume over last N days for the current user's department."""
    dept_id = current_user.dept_id
    if not dept_id:
        return []

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            func.date(ChatMessage.created_at).label("date"),
            func.count(ChatMessage.id).label("count"),
        )
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(
            ChatSession.dept_id == dept_id,
            ChatMessage.role == "user",
            ChatMessage.created_at >= since,
        )
        .group_by(func.date(ChatMessage.created_at))
        .order_by(func.date(ChatMessage.created_at))
        .all()
    )
    return [{"date": str(r.date), "count": r.count} for r in rows]


@router.get("/export")
def export_analytics(
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export analytics data as CSV or PDF."""
    dept_id = current_user.dept_id
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

    # Gather query data
    msgs = (
        db.query(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(
            ChatSession.dept_id == dept_id,
            ChatMessage.role == "user",
            ChatMessage.created_at.between(since, until),
        )
        .order_by(ChatMessage.created_at)
        .all()
    )

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Timestamp", "Query", "Confidence", "Is Voice"])
        for m in msgs:
            ai_reply = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == m.session_id, ChatMessage.role == "assistant", ChatMessage.created_at > m.created_at)
                .order_by(ChatMessage.created_at)
                .first()
            )
            writer.writerow([
                m.created_at.isoformat() if m.created_at else "",
                m.content[:300],
                round(ai_reply.confidence or 0, 3) if ai_reply else "",
                m.is_voice or False,
            ])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=analytics_export.csv"},
        )

    # PDF export via reportlab
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("OrgMind Analytics Report", styles["Title"]),
        Paragraph(f"Department: {current_user.dept_id}", styles["Normal"]),
        Paragraph(f"Period: {since.date()} to {until.date()}", styles["Normal"]),
        Spacer(1, 12),
    ]
    data = [["Timestamp", "Query (truncated)", "Confidence"]]
    for m in msgs[:100]:
        ai_reply = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == m.session_id, ChatMessage.role == "assistant", ChatMessage.created_at > m.created_at)
            .order_by(ChatMessage.created_at)
            .first()
        )
        data.append([
            str(m.created_at.date()) if m.created_at else "",
            m.content[:80],
            str(round(ai_reply.confidence or 0, 2)) if ai_reply else "-",
        ])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))
    story.append(tbl)
    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=analytics_report.pdf"},
    )
