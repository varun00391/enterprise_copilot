import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, String, Text, JSON, BigInteger, Date, event
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Department(Base):
    __tablename__ = "departments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    storage_quota_mb = Column(Integer, default=5000)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    users = relationship("User", back_populates="department")
    documents = relationship("Document", back_populates="department")
    chat_sessions = relationship("ChatSession", back_populates="department")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(150), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)  # nullable for OAuth users
    role = Column(
        Enum("user", "dept_admin", "super_admin", name="user_role", native_enum=False),
        default="user",
        nullable=False,
    )
    dept_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    auth_provider = Column(String(20), default="email")
    google_id = Column(String(100), unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    department = relationship("Department", back_populates="users")
    documents = relationship("Document", back_populates="uploader")
    chat_sessions = relationship("ChatSession", back_populates="user")
    feedbacks = relationship("Feedback", back_populates="user")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(500), nullable=False)
    original_name = Column(String(500), nullable=False)
    dept_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    file_type = Column(String(20), nullable=False)
    status = Column(
        Enum(
            "uploaded", "parsing", "chunking", "embedding", "indexed", "failed",
            name="doc_status", native_enum=False,
        ),
        default="uploaded",
    )
    sha256_hash = Column(String(64), nullable=False, index=True)
    minio_path = Column(String(500), nullable=False)
    chunk_count = Column(Integer, default=0)
    file_size_bytes = Column(BigInteger, default=0)
    category = Column(String(100), nullable=True)
    author = Column(String(150), nullable=True)
    expiry_date = Column(Date, nullable=True)
    error_message = Column(Text, nullable=True)
    source_type = Column(String(30), default="upload")   # 'upload' | 'web_crawl' | 'audio_transcription'
    source_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    department = relationship("Department", back_populates="documents")
    uploader = relationship("User", back_populates="documents")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    dept_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    title = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="chat_sessions")
    department = relationship("Department", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", order_by="ChatMessage.created_at")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(Enum("user", "assistant", name="message_role", native_enum=False), nullable=False)
    content = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    source_chunks = Column(JSON, nullable=True)
    suggested_followups = Column(JSON, nullable=True)
    is_voice = Column(Boolean, default=False)
    audio_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    session = relationship("ChatSession", back_populates="messages")
    feedbacks = relationship("Feedback", back_populates="message")


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("chat_messages.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    rating = Column(Enum("up", "down", name="feedback_rating", native_enum=False), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    message = relationship("ChatMessage", back_populates="feedbacks")
    user = relationship("User", back_populates="feedbacks")


class DepartmentAnalytics(Base):
    __tablename__ = "department_analytics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dept_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    health_score = Column(Float, nullable=True)
    avg_confidence = Column(Float, nullable=True)
    coverage_gap_ratio = Column(Float, nullable=True)
    stale_doc_ratio = Column(Float, nullable=True)
    computed_at = Column(DateTime(timezone=True), default=utcnow)

    department = relationship("Department")


class CoverageGap(Base):
    __tablename__ = "coverage_gaps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dept_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    query_topic = Column(Text, nullable=False)
    query_count = Column(Integer, default=1)
    avg_confidence = Column(Float, nullable=True)
    last_seen = Column(DateTime(timezone=True), default=utcnow)

    department = relationship("Department")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id = Column(UUID(as_uuid=True), nullable=True)
    actor_email = Column(String(255), nullable=True)
    action = Column(String(100), nullable=False)
    target_type = Column(String(50), nullable=True)
    target_id = Column(String(100), nullable=True)
    extra_data = Column("metadata", JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
