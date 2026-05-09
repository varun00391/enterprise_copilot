"""
Voice API — HTTP POST transcribe + WebSocket real-time stream.
"""
import json
import uuid

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, decode_token
from app.models.models import User, ChatSession, ChatMessage, AuditLog
from app.agents.voice import run_voice_pipeline, transcribe_audio
from app.services.analytics_refresh import schedule_refresh_dept_analytics

log = structlog.get_logger()

router = APIRouter(prefix="/voice", tags=["voice"])

ALLOWED_AUDIO = {"mp3", "wav", "m4a", "ogg", "webm", "opus"}


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"


@router.post("/transcribe")
async def voice_transcribe(
    file: UploadFile = File(...),
    session_id: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload audio → STT → RAG → TTS → return transcript + answer + audio_url.
    Primary HTTP path for voice Q&A.
    """
    if not current_user.dept_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a department")

    ext = _ext(file.filename or "audio.webm")
    if ext not in ALLOWED_AUDIO:
        raise HTTPException(status_code=400, detail=f"Unsupported audio format: .{ext}")

    audio_bytes = await file.read()
    if len(audio_bytes) > 25 * 1024 * 1024:  # 25 MB audio limit
        raise HTTPException(status_code=400, detail="Audio file exceeds 25 MB limit")

    # Get or create session
    sess = None
    if session_id:
        sess = db.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        ).first()
    if not sess:
        sess = ChatSession(user_id=current_user.id, dept_id=current_user.dept_id)
        db.add(sess)
        db.commit()
        db.refresh(sess)

    # Fetch recent conversation history
    history_msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == sess.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(10)
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in reversed(history_msgs)]

    user_id = str(current_user.id)
    dept_id = str(current_user.dept_id)

    try:
        result = run_voice_pipeline(
            audio_bytes=audio_bytes,
            dept_id=dept_id,
            user_id=user_id,
            session_id=str(sess.id),
            filename=file.filename or f"audio.{ext}",
            conversation_history=history,
            database_url=settings.DATABASE_URL,
        )
    except Exception as e:
        log.error("voice.transcribe_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Voice pipeline error: {str(e)}")

    # Persist messages
    user_msg = ChatMessage(
        session_id=sess.id,
        role="user",
        content=result["transcript"],
        is_voice=True,
    )
    ai_msg = ChatMessage(
        session_id=sess.id,
        role="assistant",
        content=result["answer_text"],
        confidence=result["confidence"],
        source_chunks=result["sources"],
        is_voice=True,
        audio_url=result["audio_url"],
    )
    db.add_all([user_msg, ai_msg])
    db.add(AuditLog(
        actor_id=current_user.id,
        actor_email=current_user.email,
        action="voice.transcribe",
        target_type="session",
        target_id=str(sess.id),
    ))
    db.commit()

    schedule_refresh_dept_analytics(settings.DATABASE_URL, dept_id)

    return {
        "session_id": str(sess.id),
        "transcript": result["transcript"],
        "answer_text": result["answer_text"],
        "audio_url": result["audio_url"],
        "confidence": result["confidence"],
        "sources": result["sources"],
    }


@router.websocket("/stream")
async def voice_stream(websocket: WebSocket):
    """
    WebSocket endpoint for real-time voice streaming.
    Protocol:
      Client → binary (audio chunks)
      Server → JSON {type: "transcript", text: ...}
      Server → JSON {type: "answer", text: ...}
      Server → binary (MP3 audio response)
    """
    await websocket.accept()

    # Authenticate via token in first message
    try:
        auth_msg = await websocket.receive_text()
        auth_data = json.loads(auth_msg)
        token = auth_data.get("token", "")
        payload = decode_token(token)
        user_id = payload.get("sub")
        dept_id = payload.get("dept_id")
        if not user_id or not dept_id:
            await websocket.send_json({"type": "error", "message": "Invalid token"})
            await websocket.close(code=4001)
            return
    except Exception as e:
        await websocket.send_json({"type": "error", "message": "Authentication failed"})
        await websocket.close(code=4001)
        return

    await websocket.send_json({"type": "connected", "message": "Ready for audio"})

    try:
        while True:
            try:
                data = await websocket.receive_bytes()
            except WebSocketDisconnect:
                break

            # Transcribe the received audio chunk
            try:
                transcript = transcribe_audio(data, filename="stream.webm")
                await websocket.send_json({"type": "transcript", "text": transcript})

                if transcript.strip():
                    # Run RAG pipeline
                    from app.agents.orchestrator import run_query_pipeline
                    full_answer = ""
                    for chunk in run_query_pipeline(
                        query=transcript,
                        dept_id=dept_id,
                        user_id=user_id,
                        session_id="ws-stream",
                        database_url=settings.DATABASE_URL,
                    ):
                        if chunk.startswith("data: "):
                            try:
                                evt = json.loads(chunk[6:].strip())
                                if evt.get("type") == "metadata":
                                    full_answer = evt.get("answer", "")
                            except Exception:
                                pass

                    await websocket.send_json({"type": "answer", "text": full_answer})

                    # Synthesize TTS
                    from app.agents.voice import synthesize_speech
                    try:
                        audio_mp3 = synthesize_speech(full_answer)
                        await websocket.send_bytes(audio_mp3)
                    except Exception as tts_err:
                        log.warning("voice.ws_tts_failed", error=str(tts_err))

            except Exception as e:
                await websocket.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        log.info("voice.ws_disconnected", user_id=user_id)
