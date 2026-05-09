"""
Security Agent — enforces department namespace isolation, detects PII,
and validates RBAC on document and query operations.
"""
import re
from typing import Optional

import structlog

log = structlog.get_logger()

PII_PATTERNS = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "SSN"),
    (r"\b4[0-9]{12}(?:[0-9]{3})?\b", "Visa Card"),
    (r"\b5[1-5][0-9]{14}\b", "MasterCard"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "Email"),
    (r"\b\d{10}\b", "Phone Number"),
]


def validate_namespace_access(query_dept_id: str, user_dept_id: str, user_role: str) -> bool:
    """Ensure a user can only access their own department's data (unless super_admin)."""
    if user_role == "super_admin":
        return True
    if query_dept_id != user_dept_id:
        log.warning(
            "security.namespace_violation",
            query_dept_id=query_dept_id,
            user_dept_id=user_dept_id,
        )
        return False
    return True


def scan_for_pii(text: str) -> list[dict]:
    """Scan text for PII patterns. Returns list of findings."""
    findings = []
    for pattern, pii_type in PII_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            findings.append({"type": pii_type, "count": len(matches)})
    return findings


def sanitize_query(query: str) -> str:
    """Basic query sanitization — strip control characters."""
    query = query.strip()
    query = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", query)
    if len(query) > 2000:
        query = query[:2000]
    return query


def assert_document_access(doc_dept_id: str, user_dept_id: str, user_role: str) -> None:
    from fastapi import HTTPException
    if not validate_namespace_access(doc_dept_id, user_dept_id, user_role):
        raise HTTPException(status_code=403, detail="Access denied: cross-department access is not allowed")
