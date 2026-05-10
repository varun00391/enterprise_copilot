from __future__ import annotations
from datetime import datetime, date
from typing import Optional, List, Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator, model_validator


# ─── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    dept_id: Optional[UUID] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UpdateMeRequest(BaseModel):
    name: Optional[str] = None
    dept_id: Optional[UUID] = None


class UserOut(BaseModel):
    id: UUID
    name: str
    email: str
    role: str
    dept_id: Optional[UUID]
    dept_name: Optional[str] = None
    is_active: bool
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _populate_dept_name(cls, data: Any) -> Any:
        if hasattr(data, "department") and data.department is not None:
            try:
                data.__dict__["dept_name"] = data.department.name
            except Exception:
                pass
        return data

    class Config:
        from_attributes = True


# ─── Department ────────────────────────────────────────────────────────────────

class DepartmentCreate(BaseModel):
    name: str
    slug: str
    storage_quota_mb: int = 5000


class DepartmentOut(BaseModel):
    id: UUID
    name: str
    slug: str
    storage_quota_mb: int
    created_at: datetime

    class Config:
        from_attributes = True


class DepartmentStats(DepartmentOut):
    user_count: int = 0
    document_count: int = 0
    query_count_today: int = 0


# ─── Document ──────────────────────────────────────────────────────────────────

class DocumentOut(BaseModel):
    id: UUID
    filename: str
    original_name: str
    dept_id: UUID
    file_type: str
    status: str
    chunk_count: int
    file_size_bytes: int
    category: Optional[str]
    author: Optional[str]
    created_at: datetime
    error_message: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DocumentStatusOut(BaseModel):
    id: UUID
    status: str
    chunk_count: int
    error_message: Optional[str]
    updated_at: datetime

    class Config:
        from_attributes = True


# ─── Chat ──────────────────────────────────────────────────────────────────────

class ChatQueryRequest(BaseModel):
    query: str
    session_id: Optional[UUID] = None
    edit_message_id: Optional[UUID] = None


class SourceChunk(BaseModel):
    doc_id: str
    doc_name: str
    chunk_index: int
    content: str
    score: float
    page: Optional[int] = None


class ChatMessageOut(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    confidence: Optional[float]
    source_chunks: Optional[List[SourceChunk]]
    created_at: datetime

    class Config:
        from_attributes = True


class ChatSessionOut(BaseModel):
    id: UUID
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    class Config:
        from_attributes = True


class ChatHistoryPageOut(BaseModel):
    items: List[ChatSessionOut]
    page: int
    page_size: int
    total: int
    has_more: bool


class FeedbackRequest(BaseModel):
    message_id: UUID
    rating: str

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v: str) -> str:
        if v not in ("up", "down"):
            raise ValueError("Rating must be 'up' or 'down'")
        return v


# ─── Analytics ─────────────────────────────────────────────────────────────────

class DashboardMetrics(BaseModel):
    total_documents: int
    questions_today: int
    avg_confidence: float
    documents_this_week: int
    pending_documents: int


class RecentActivity(BaseModel):
    id: UUID
    query: str
    answer_snippet: str
    confidence: Optional[float]
    source_doc: Optional[str]
    created_at: datetime


class TopDocument(BaseModel):
    id: UUID
    original_name: str
    query_count: int
    file_type: str


class AdminDashboardMetrics(BaseModel):
    total_users: int
    total_documents: int
    total_queries_today: int
    total_queries_week: int
    avg_confidence: float
    storage_used_mb: float
    departments: List[DepartmentStats]


# ─── Admin ─────────────────────────────────────────────────────────────────────

class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    dept_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class AuditLogOut(BaseModel):
    id: UUID
    actor_email: Optional[str]
    action: str
    target_type: Optional[str]
    target_id: Optional[str]
    extra_data: Optional[Any]
    ip_address: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class AnswerEvaluationOut(BaseModel):
    id: UUID
    message_id: UUID
    dept_id: Optional[UUID]
    faithfulness: Optional[float]
    answer_relevancy: Optional[float]
    flagged: bool
    error_message: Optional[str]
    langfuse_trace_id: Optional[str]
    created_at: datetime
    answer_preview: Optional[str] = None

    class Config:
        from_attributes = True


class EvaluationMetaOut(BaseModel):
    """Non-secret hints for linking Admin UI to Langfuse."""

    langfuse_ui_origin: Optional[str] = None
    langfuse_project_id: Optional[str] = None


# ─── Health ────────────────────────────────────────────────────────────────────

class HealthStatus(BaseModel):
    status: str
    version: str = "1.0.0"
    services: dict
