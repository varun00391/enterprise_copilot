import re
import uuid
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User, ChatSession, ChatMessage, Feedback, AuditLog
from app.schemas.schemas import (
    ChatQueryRequest,
    ChatSessionOut,
    ChatMessageOut,
    FeedbackRequest,
    ChatHistoryPageOut,
)
from app.core.config import settings
from app.agents.orchestrator import run_query_pipeline, run_multimodal_stream

from app.services.analytics_refresh import schedule_refresh_dept_analytics

router = APIRouter(prefix="/chat", tags=["chat"])

MAX_CHAT_IMAGE_BYTES = 10 * 1024 * 1024

_URL_ONLY_RE = re.compile(r"^\s*https?://\S+\s*$", re.IGNORECASE)


def _message_is_url_only(text: str) -> bool:
    return bool(_URL_ONLY_RE.match(text or ""))


def _sse_url_crawl_ack(max_pages: int):
    """SSE stream matching reasoning agent shape — crawl queued from chat."""
    import json

    answer = (
        "I've started crawling and indexing this URL into your department knowledge base "
        f"(up to {max_pages} pages — sitemap expansion or same-site links — with robots.txt respected). "
        "After a minute or two, ask your questions here; answers will cite the crawled pages as sources."
    )
    yield f"data: {json.dumps({'type': 'token', 'content': answer})}\n\n"
    meta = {
        "type": "metadata",
        "answer": answer,
        "confidence": 1.0,
        "sources": [],
        "suggested_followups": [],
    }
    yield f"data: {json.dumps(meta)}\n\n"
    yield "data: [DONE]\n\n"


_DEFAULT_MULTIMODAL_PROMPT = (
    "Describe this image and relate your answer to any relevant "
    "information in the department knowledge base."
)


def _parse_session_id_optional(raw: Optional[str]) -> Optional[uuid.UUID]:
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        return uuid.UUID(s)
    except ValueError:
        return None


def _validate_image_magic(data: bytes) -> None:
    if len(data) > MAX_CHAT_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image exceeds 10 MB limit")
    if len(data) < 32:
        raise HTTPException(status_code=400, detail="Image file is too small")
    if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff":
        return
    raise HTTPException(
        status_code=400,
        detail="Unsupported image type — use PNG or JPEG",
    )


def _get_or_create_session(
    session_id: Optional[uuid.UUID], user: User, db: Session
) -> ChatSession:
    if session_id:
        session = db.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        ).first()
        if session:
            return session

    session = ChatSession(
        user_id=user.id,
        dept_id=user.dept_id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _strictly_after_anchor(anchor: ChatMessage):
    """Chronological ordering tie-breaker when created_at matches."""
    return or_(
        ChatMessage.created_at > anchor.created_at,
        and_(ChatMessage.created_at == anchor.created_at, ChatMessage.id > anchor.id),
    )


def _strictly_before_anchor(anchor: ChatMessage):
    return or_(
        ChatMessage.created_at < anchor.created_at,
        and_(ChatMessage.created_at == anchor.created_at, ChatMessage.id < anchor.id),
    )


async def _parse_chat_request(
    request: Request,
) -> Tuple[str, Optional[uuid.UUID], Optional[bytes], Optional[uuid.UUID]]:
    """Returns (query_text, session_id, optional image bytes, optional edit_message_id)."""
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()

    if content_type == "multipart/form-data":
        form = await request.form()
        raw_q = form.get("query")
        if isinstance(raw_q, bytes):
            query_text = raw_q.decode("utf-8", errors="replace")
        elif raw_q is None:
            query_text = ""
        else:
            query_text = str(raw_q)

        raw_sid = form.get("session_id")
        if isinstance(raw_sid, bytes):
            sid_str = raw_sid.decode("utf-8", errors="replace").strip()
        elif raw_sid is None:
            sid_str = ""
        else:
            sid_str = str(raw_sid).strip()
        session_id = _parse_session_id_optional(sid_str)

        raw_edit = form.get("edit_message_id")
        if isinstance(raw_edit, bytes):
            edit_str = raw_edit.decode("utf-8", errors="replace").strip()
        elif raw_edit is None:
            edit_str = ""
        else:
            edit_str = str(raw_edit).strip()
        edit_message_id = _parse_session_id_optional(edit_str)

        upload = form.get("image")
        image_bytes = None
        if upload is not None and hasattr(upload, "read"):
            image_bytes = await upload.read()

        return query_text.strip(), session_id, image_bytes, edit_message_id

    if content_type == "application/json":
        body = await request.json()
        payload = ChatQueryRequest.model_validate(body)
        return (
            payload.query if payload.query is not None else "",
            payload.session_id,
            None,
            payload.edit_message_id,
        )

    raise HTTPException(
        status_code=415,
        detail="Supported Content-Types: application/json, multipart/form-data",
    )


@router.post("/query")
async def query(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.dept_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a department")

    query_input, parsed_session_id, image_bytes_optional, edit_message_uuid = (
        await _parse_chat_request(request)
    )

    if image_bytes_optional is None or len(image_bytes_optional) == 0:
        image_bytes = None
    else:
        image_bytes = image_bytes_optional
        _validate_image_magic(image_bytes)

    q_stripped = (query_input or "").strip()
    if not q_stripped and not image_bytes:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    user_visible_content = (
        q_stripped if q_stripped else "(image attached)"
    )
    llm_query = q_stripped if q_stripped else _DEFAULT_MULTIMODAL_PROMPT

    user_dept_id = str(current_user.dept_id)
    user_id = str(current_user.id)
    user_email = current_user.email

    edited_user_row: Optional[ChatMessage] = None

    if edit_message_uuid is not None:
        if image_bytes is not None:
            raise HTTPException(
                status_code=400,
                detail="Replacing a message together with a new image upload is not supported",
            )
        edited_user_row = (
            db.query(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .filter(
                ChatMessage.id == edit_message_uuid,
                ChatSession.user_id == current_user.id,
            )
            .first()
        )
        if not edited_user_row:
            raise HTTPException(status_code=404, detail="Message not found")
        if edited_user_row.role != "user":
            raise HTTPException(status_code=400, detail="Only user messages can be edited")
        if parsed_session_id and parsed_session_id != edited_user_row.session_id:
            raise HTTPException(
                status_code=400,
                detail="Session ID does not match the message being edited",
            )

        tail = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == edited_user_row.session_id,
                _strictly_after_anchor(edited_user_row),
            )
            .all()
        )
        tail_ids = [m.id for m in tail]
        if tail_ids:
            db.query(Feedback).filter(Feedback.message_id.in_(tail_ids)).delete(
                synchronize_session=False
            )
            db.query(ChatMessage).filter(ChatMessage.id.in_(tail_ids)).delete(
                synchronize_session=False
            )

        edited_user_row.content = user_visible_content
        db.commit()
        db.refresh(edited_user_row)

        session = (
            db.query(ChatSession)
            .filter(ChatSession.id == edited_user_row.session_id)
            .first()
        )
    else:
        session = _get_or_create_session(parsed_session_id, current_user, db)

    history_msgs_query = db.query(ChatMessage).filter(ChatMessage.session_id == session.id)
    if edited_user_row is not None:
        history_msgs_query = history_msgs_query.filter(
            _strictly_before_anchor(edited_user_row)
        )
    history_msgs = (
        history_msgs_query.order_by(ChatMessage.created_at.desc())
        .limit(20)
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in reversed(history_msgs)]

    if edited_user_row is None:
        user_msg = ChatMessage(
            session_id=session.id,
            role="user",
            content=user_visible_content,
        )
        db.add(user_msg)
        db.commit()
        db.refresh(user_msg)
        user_message_id_for_response = user_msg.id
    else:
        user_message_id_for_response = edited_user_row.id

    crawl_scheduled = False
    if not image_bytes and _message_is_url_only(q_stripped):
        from app.api.documents import schedule_web_crawl_job

        try:
            schedule_web_crawl_job(
                background_tasks,
                db,
                current_user,
                [q_stripped.strip()],
                crawl_mode="auto",
                max_depth=settings.CRAWL_CHAT_MAX_DEPTH,
                max_pages_per_seed=settings.CRAWL_CHAT_MAX_PAGES_PER_SEED,
                max_pages_total=settings.CRAWL_CHAT_MAX_PAGES_TOTAL,
            )
            crawl_scheduled = True
        except HTTPException:
            raise
        except Exception:
            crawl_scheduled = False

    def pipe():
        if crawl_scheduled:
            yield from _sse_url_crawl_ack(settings.CRAWL_CHAT_MAX_PAGES_TOTAL)
            return
        if image_bytes:
            yield from run_multimodal_stream(
                query=llm_query,
                image_bytes=image_bytes,
                dept_id=user_dept_id,
                user_id=user_id,
                session_id=str(session.id),
                conversation_history=history,
            )
            return
        yield from run_query_pipeline(
            query=query_input.strip() if query_input else "",
            dept_id=user_dept_id,
            user_id=user_id,
            session_id=str(session.id),
            conversation_history=history,
            database_url=settings.DATABASE_URL,
        )

    stream_source = pipe()

    is_edit = edited_user_row is not None

    def generate():
        import json

        full_answer = ""
        confidence = 0.75
        sources = []
        suggested_followups = []

        for chunk in stream_source:
            if chunk.strip() == "data: [DONE]":
                continue
            if chunk.startswith("data: "):
                try:
                    data = json.loads(chunk[6:].strip())
                    if data.get("type") == "metadata":
                        full_answer = data.get("answer", "")
                        confidence = data.get("confidence", 0.75)
                        sources = data.get("sources", [])
                        suggested_followups = data.get("suggested_followups", [])
                except Exception:
                    pass
            yield chunk

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.config import settings

        engine = create_engine(settings.DATABASE_URL)
        BgSession = sessionmaker(bind=engine)
        bg_db = BgSession()
        try:
            assistant_row = ChatMessage(
                session_id=session.id,
                role="assistant",
                content=full_answer,
                confidence=confidence,
                source_chunks=sources,
                suggested_followups=suggested_followups,
            )
            bg_db.add(assistant_row)
            if image_bytes:
                audit_action = "chat.query_multimodal"
            elif is_edit:
                audit_action = "chat.query_edit"
            else:
                audit_action = "chat.query"
            audit = AuditLog(
                actor_id=uuid.UUID(user_id),
                actor_email=user_email,
                action=audit_action,
                target_type="session",
                target_id=str(session.id),
            )
            bg_db.add(audit)
            bg_db.commit()
            schedule_refresh_dept_analytics(settings.DATABASE_URL, user_dept_id)
            yield f"data: {json.dumps({'type': 'persisted', 'user_message_id': str(user_message_id_for_response), 'assistant_message_id': str(assistant_row.id)})}\n\n"
        finally:
            bg_db.close()
            engine.dispose()

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-Id": str(session.id),
            "X-User-Message-Id": str(user_message_id_for_response),
        },
    )


@router.delete("/session/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.delete(session)
    db.commit()


@router.get("/history", response_model=ChatHistoryPageOut)
def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skip = (page - 1) * page_size
    base_query = db.query(ChatSession).filter(ChatSession.user_id == current_user.id)
    total = base_query.count()

    sessions = (
        base_query.order_by(ChatSession.updated_at.desc())
        .offset(skip)
        .limit(page_size)
        .all()
    )
    items = []
    for s in sessions:
        count = db.query(ChatMessage).filter(ChatMessage.session_id == s.id).count()
        items.append(
            ChatSessionOut(
                id=s.id,
                title=s.title,
                created_at=s.created_at,
                updated_at=s.updated_at,
                message_count=count,
            )
        )

    has_more = skip + len(sessions) < total
    return ChatHistoryPageOut(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        has_more=has_more,
    )


@router.get("/session/{session_id}/messages", response_model=List[ChatMessageOut])
def get_session_messages(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
        .all()
    )
    return messages


@router.post("/feedback", status_code=201)
def submit_feedback(
    payload: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    msg = db.query(ChatMessage).filter(ChatMessage.id == payload.message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    feedback = Feedback(
        message_id=payload.message_id,
        user_id=current_user.id,
        rating=payload.rating,
    )
    db.add(feedback)
    db.commit()
    return {"status": "ok"}