"""Pre-compute department analytics rows for fast dashboard reads."""
from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import (
    ChatSession,
    ChatMessage,
    Document,
    DepartmentAnalytics,
    CoverageGap,
)

log = structlog.get_logger()

THRESH = settings.COVERAGE_GAP_CONFIDENCE_THRESHOLD
FRESH_DAYS = settings.DOCUMENT_FRESHNESS_THRESHOLD_DAYS


def _topic_key(text: str) -> str:
    t = " ".join((text or "").strip().split())
    return (t.lower()[:200]) if t else ""


def refresh_department_analytics(db: Session, dept_id: UUID) -> DepartmentAnalytics:
    """Recompute Knowledge Health snapshot for one department."""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    freshness_threshold = datetime.now(timezone.utc) - timedelta(days=FRESH_DAYS)

    avg_conf = (
        db.query(func.avg(ChatMessage.confidence))
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(
            ChatSession.dept_id == dept_id,
            ChatMessage.role == "assistant",
            ChatMessage.confidence.isnot(None),
            ChatMessage.created_at >= thirty_days_ago,
        ).scalar()
        or 0
    )

    total_queries = (
        db.query(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(
            ChatSession.dept_id == dept_id,
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= thirty_days_ago,
        )
        .count()
    )

    low_conf_queries = (
        db.query(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(
            ChatSession.dept_id == dept_id,
            ChatMessage.role == "assistant",
            ChatMessage.confidence < THRESH,
            ChatMessage.created_at >= thirty_days_ago,
        )
        .count()
    )

    coverage_gap_ratio = (
        (low_conf_queries / total_queries) if total_queries > 0 else 0
    )

    total_docs = (
        db.query(Document)
        .filter(Document.dept_id == dept_id, Document.status == "indexed")
        .count()
    )

    stale_docs = (
        db.query(Document)
        .filter(
            Document.dept_id == dept_id,
            Document.status == "indexed",
            Document.created_at < freshness_threshold,
        )
        .count()
    )

    stale_doc_ratio = (stale_docs / total_docs) if total_docs > 0 else 0

    health_score = (
        0.4 * float(avg_conf)
        + 0.3 * (1 - coverage_gap_ratio)
        + 0.3 * (1 - stale_doc_ratio)
    ) * 100

    db.query(DepartmentAnalytics).filter(DepartmentAnalytics.dept_id == dept_id).delete(
        synchronize_session=False
    )

    row = DepartmentAnalytics(
        dept_id=dept_id,
        health_score=round(float(health_score), 4),
        avg_confidence=round(float(avg_conf), 6),
        coverage_gap_ratio=round(float(coverage_gap_ratio), 6),
        stale_doc_ratio=round(float(stale_doc_ratio), 6),
        computed_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log.info("analytics_refresh.health_row", dept_id=str(dept_id), health_score=health_score)
    return row


def refresh_coverage_gaps(db: Session, dept_id: UUID, limit_topics: int = 100) -> int:
    """
    Aggregate low-confidence Q&A pairs from the last 30 days into coverage_gaps.
    Deletes existing gaps for this department then inserts aggregated rows.
    """
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    low_conf_msgs = (
        db.query(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(
            ChatSession.dept_id == dept_id,
            ChatMessage.role == "assistant",
            ChatMessage.confidence < THRESH,
            ChatMessage.created_at >= thirty_days_ago,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(800)
        .all()
    )

    agg: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "conf_sum": 0.0, "last_seen": None}
    )

    for ai_msg in low_conf_msgs:
        user_row = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == ai_msg.session_id,
                ChatMessage.role == "user",
                ChatMessage.created_at < ai_msg.created_at,
            )
            .order_by(ChatMessage.created_at.desc())
            .first()
        )
        if not user_row:
            continue
        key = _topic_key(user_row.content)
        if not key:
            continue
        bucket = agg[key]
        bucket["count"] += 1
        bucket["conf_sum"] += float(ai_msg.confidence or 0)
        ts = ai_msg.created_at
        if bucket["last_seen"] is None or ts > bucket["last_seen"]:
            bucket["last_seen"] = ts

    db.query(CoverageGap).filter(CoverageGap.dept_id == dept_id).delete(synchronize_session=False)

    inserted = 0
    sorted_topics = sorted(agg.items(), key=lambda kv: kv[1]["count"], reverse=True)[:limit_topics]
    for topic, data in sorted_topics:
        cg = CoverageGap(
            dept_id=dept_id,
            query_topic=topic[:2000],
            query_count=data["count"],
            avg_confidence=(
                round(data["conf_sum"] / data["count"], 6) if data["count"] else 0
            ),
            last_seen=data["last_seen"] or datetime.now(timezone.utc),
        )
        db.add(cg)
        inserted += 1

    db.commit()
    log.info("analytics_refresh.coverage_gaps", dept_id=str(dept_id), rows=inserted)
    return inserted


def refresh_all_for_department(db: Session, dept_id: UUID) -> None:
    refresh_department_analytics(db, dept_id)
    refresh_coverage_gaps(db, dept_id)


def schedule_refresh_dept_analytics(database_url: str, dept_id: str) -> None:
    """Non-blocking snapshot refresh after chat turns."""

    def _worker():
        uid = UUID(dept_id)
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(database_url)
        S = sessionmaker(bind=engine)
        s = S()
        try:
            refresh_all_for_department(s, uid)
        except Exception as e:
            log.warning("analytics_refresh.async_failed", dept_id=dept_id, error=str(e))
        finally:
            s.close()
            engine.dispose()

    threading.Thread(target=_worker, name=f"analytics-refresh-{dept_id}", daemon=True).start()


def latest_department_analytics(db: Session, dept_id: UUID) -> Optional[DepartmentAnalytics]:
    return (
        db.query(DepartmentAnalytics)
        .filter(DepartmentAnalytics.dept_id == dept_id)
        .order_by(DepartmentAnalytics.computed_at.desc())
        .first()
    )


def count_queries_30d(db: Session, dept_id: UUID) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    return (
        db.query(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .filter(
            ChatSession.dept_id == dept_id,
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= since,
        )
        .count()
    )


def count_docs_and_stale(db: Session, dept_id: UUID) -> Dict[str, int]:
    thresh = datetime.now(timezone.utc) - timedelta(days=FRESH_DAYS)
    total_docs = (
        db.query(Document)
        .filter(Document.dept_id == dept_id, Document.status == "indexed")
        .count()
    )
    stale_docs = (
        db.query(Document)
        .filter(
            Document.dept_id == dept_id,
            Document.status == "indexed",
            Document.created_at < thresh,
        )
        .count()
    )
    return {"total_docs": total_docs, "stale_docs": stale_docs}
