"""
Resolves spreadsheet bytes and chart descriptions from retrieval chunks for the Analytics Agent.
Uses a short-lived DB session — never rely on FastAPI request-scoped sessions inside SSE generators.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.models import Document
from app.services.storage import download_file

log = structlog.get_logger()

SPREADSHEET_TYPES = frozenset({"csv", "xlsx", "xls", "xlsm"})
IMAGE_TYPES = frozenset({"png", "jpg", "jpeg"})

ANALYTICS_QUERY_TERMS = frozenset(
    (
        "spreadsheet",
        "csv",
        "excel",
        "xlsx",
        "column",
        "row",
        "pivot",
        "median",
        "average",
        "mean",
        "sum",
        "total",
        "variance",
        "std dev",
        "correlation",
        "dataset",
        "table ",
        "tabular",
        "dataframe",
        "aggregate",
        "statistic",
    )
)

CHART_QUERY_TERMS = frozenset(
    (
        "chart",
        "graph",
        "plot",
        "trend line",
        "bar chart",
        "line chart",
        "pie chart",
        "visualization",
        "axis",
        "legend",
        "diagram",
    )
)

MAX_TABULAR_BYTES = 15 * 1024 * 1024


def _norm_ft(ft: Optional[str]) -> str:
    if not ft:
        return ""
    return ft.lower().strip().lstrip(".")


def query_suggests_analytics(query_lower: str) -> bool:
    return any(term in query_lower for term in ANALYTICS_QUERY_TERMS)


def query_suggests_chart(query_lower: str) -> bool:
    return any(term in query_lower for term in CHART_QUERY_TERMS)


def should_use_analytics_path(
    query: str,
    chunks: List[Dict[str, Any]],
    spreadsheet: Optional[Tuple[bytes, str]],
    chart_insight: Optional[str],
) -> bool:
    if spreadsheet is not None or chart_insight:
        return True
    if not chunks:
        return False
    q = query.lower()
    if query_suggests_analytics(q):
        return True
    if query_suggests_chart(q):
        for c in chunks[:8]:
            if _norm_ft(c.get("file_type")) in IMAGE_TYPES:
                return True
    for c in chunks[:8]:
        if _norm_ft(c.get("file_type")) in SPREADSHEET_TYPES:
            return True
    return False


def _open_db_session(database_url: str):
    engine = create_engine(database_url)
    return engine, sessionmaker(bind=engine)()


def _doc_uuid(doc_id: Any) -> Optional[UUID]:
    if doc_id is None:
        return None
    try:
        return UUID(str(doc_id))
    except (ValueError, TypeError):
        return None


def load_spreadsheet_from_chunks(
    database_url: str,
    dept_id: str,
    chunks: List[Dict[str, Any]],
) -> Optional[Tuple[bytes, str]]:
    """Fetch the first spreadsheet (by retrieval order) under size limit."""
    engine = None
    db = None
    dept_uuid = UUID(dept_id)
    seen = set()

    try:
        engine, db = _open_db_session(database_url)
        for ch in chunks:
            doc_id = _doc_uuid(ch.get("doc_id"))
            ft = _norm_ft(ch.get("file_type"))
            if doc_id is None or ft not in SPREADSHEET_TYPES or doc_id in seen:
                continue
            seen.add(doc_id)
            doc = (
                db.query(Document)
                .filter(
                    Document.id == doc_id,
                    Document.dept_id == dept_uuid,
                    Document.status == "indexed",
                )
                .first()
            )
            if not doc:
                continue
            if doc.file_size_bytes and doc.file_size_bytes > MAX_TABULAR_BYTES:
                log.info("analytics_context.spreadsheet_skipped_size", doc_id=str(doc_id))
                continue
            try:
                data = download_file(doc.minio_path)
                if len(data) > MAX_TABULAR_BYTES:
                    continue
                return data, ft
            except Exception as e:
                log.warning("analytics_context.spreadsheet_download_failed", error=str(e))
        return None
    finally:
        if db:
            db.close()
        if engine:
            engine.dispose()


def load_chart_insight_from_chunks(
    database_url: str,
    dept_id: str,
    chunks: List[Dict[str, Any]],
    query: str,
) -> Optional[str]:
    if not query_suggests_chart(query.lower()):
        return None
    engine = None
    db = None
    dept_uuid = UUID(dept_id)
    seen = set()

    try:
        engine, db = _open_db_session(database_url)
        for ch in chunks[:8]:
            doc_id = _doc_uuid(ch.get("doc_id"))
            ft = _norm_ft(ch.get("file_type"))
            if doc_id is None or ft not in IMAGE_TYPES or doc_id in seen:
                continue
            seen.add(doc_id)
            doc = (
                db.query(Document)
                .filter(
                    Document.id == doc_id,
                    Document.dept_id == dept_uuid,
                    Document.status == "indexed",
                )
                .first()
            )
            if not doc:
                continue
            if doc.file_size_bytes and doc.file_size_bytes > MAX_TABULAR_BYTES:
                continue
            try:
                data = download_file(doc.minio_path)
                from app.agents.analytics_agent import detect_chart_in_image

                return detect_chart_in_image(data)
            except Exception as e:
                log.warning("analytics_context.chart_insight_failed", error=str(e))
        return None
    finally:
        if db:
            db.close()
        if engine:
            engine.dispose()
