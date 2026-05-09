"""
Voice Agent — handles STT (speech-to-text) and TTS (text-to-speech) for voice Q&A.

Primary path (HTTP POST /api/voice/transcribe):
  1. Receive audio bytes (WebM / MP3 / WAV)
  2. STT: Deepgram Nova-3 if DEEPGRAM_API_KEY is set, else OpenAI Whisper
  3. Pass transcript → Orchestrator (same Phase 1 RAG pipeline)
  4. TTS: Deepgram Aura if DEEPGRAM_API_KEY is set, else OpenAI TTS
  5. Save MP3 to MinIO voice_responses/ prefix
  6. Return { transcript, answer_text, audio_url }

Audio file ingestion (batch MP3/WAV upload):
  - Uses Groq Whisper (whisper-large-v3-turbo) if GROQ_API_KEY set, else OpenAI Whisper

Video / batch paths can request timestamped segments via `transcribe_audio_with_segments`.
"""
import io
import json
import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.core.config import settings
from app.services.storage import upload_file, get_presigned_url

log = structlog.get_logger()


# ─── STT helpers ─────────────────────────────────────────────────────────────

def transcribe_with_deepgram(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """Transcribe audio using Deepgram Nova-3."""
    from deepgram import DeepgramClient, PrerecordedOptions
    client = DeepgramClient(settings.DEEPGRAM_API_KEY)
    options = PrerecordedOptions(
        model=settings.DEEPGRAM_STT_MODEL,
        smart_format=True,
        punctuate=True,
        language="en-US",
    )
    response = client.listen.prerecorded.v("1").transcribe_file(
        {"buffer": audio_bytes, "mimetype": mime_type},
        options,
    )
    try:
        transcript = response.results.channels[0].alternatives[0].transcript
        return transcript or ""
    except (AttributeError, IndexError, TypeError) as e:
        log.warning("voice.deepgram_parse_failed", error=str(e))
        return ""


def transcribe_with_openai(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """Transcribe audio using OpenAI Whisper API."""
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    file_tuple = (filename, io.BytesIO(audio_bytes), "audio/webm")
    response = client.audio.transcriptions.create(
        model="whisper-1",
        file=file_tuple,
        response_format="text",
    )
    return str(response).strip()


def transcribe_with_groq(audio_bytes: bytes, filename: str = "audio.mp3") -> str:
    """Transcribe audio using Groq Whisper (batch file ingestion)."""
    from groq import Groq
    client = Groq(api_key=settings.GROQ_API_KEY)
    response = client.audio.transcriptions.create(
        file=(filename, io.BytesIO(audio_bytes)),
        model=settings.GROQ_STT_MODEL,
        response_format="text",
        language="en",
    )
    return str(response).strip()


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm", use_groq: bool = False) -> str:
    """
    Route to the best available STT provider.
    Priority: Groq (forced) → Deepgram → Groq (fallback) → OpenAI Whisper.
    use_groq=True forces Groq (for batch file ingestion).
    OpenAI Whisper is only attempted when OPENAI_BASE_URL is the real OpenAI
    endpoint, not a chat-only compatible proxy that lacks audio endpoints.
    """
    if use_groq and settings.GROQ_API_KEY:
        try:
            return transcribe_with_groq(audio_bytes, filename)
        except Exception as e:
            log.warning("voice.groq_stt_failed", error=str(e))

    if settings.DEEPGRAM_API_KEY and not use_groq:
        try:
            mime = "audio/mp3" if filename.endswith(".mp3") else "audio/webm"
            return transcribe_with_deepgram(audio_bytes, mime)
        except Exception as e:
            log.warning("voice.deepgram_stt_failed", error=str(e))
            # Deepgram failed — try Groq before falling back to OpenAI
            if settings.GROQ_API_KEY:
                try:
                    return transcribe_with_groq(audio_bytes, filename)
                except Exception as groq_err:
                    log.warning("voice.groq_stt_fallback_failed", error=str(groq_err))

    # Only call OpenAI Whisper when the base URL is the real OpenAI API,
    # not a chat-only proxy (e.g. EuriAI) that lacks the /audio/transcriptions endpoint.
    openai_base = (settings.OPENAI_BASE_URL or "").rstrip("/")
    is_real_openai = openai_base in ("", "https://api.openai.com/v1")
    if is_real_openai:
        return transcribe_with_openai(audio_bytes, filename)

    raise RuntimeError(
        "No STT provider available. Ensure DEEPGRAM_API_KEY or GROQ_API_KEY is set, "
        "or point OPENAI_BASE_URL at the real OpenAI API."
    )


def _coerce_stt_segments(segments: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for seg in segments or []:
        row = seg if isinstance(seg, dict) else None
        if row is None and hasattr(seg, "model_dump"):
            try:
                row = seg.model_dump()
            except Exception:
                row = None
        if row is None:
            try:
                tx = (getattr(seg, "text", "") or "").strip()
                if not tx:
                    continue
                st = float(getattr(seg, "start", 0))
                en = float(getattr(seg, "end", st))
                out.append({"start": st, "end": en, "text": tx})
            except (TypeError, ValueError):
                continue
            continue
        try:
            st = float(row.get("start", 0))
            en = float(row.get("end", st))
            tx = (row.get("text") or "").strip()
            if tx:
                out.append({"start": st, "end": en, "text": tx})
        except (TypeError, ValueError):
            continue
    return out


def transcribe_with_openai_verbose(audio_bytes: bytes, filename: str = "audio.wav") -> List[Dict[str, Any]]:
    """Whisper with per-segment timestamps (seconds)."""
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL or None)
    file_tuple = (filename, io.BytesIO(audio_bytes))
    response = client.audio.transcriptions.create(
        model="whisper-1",
        file=file_tuple,
        response_format="verbose_json",
        timestamp_granularities=["segment"],
    )
    segments: List[Any] = []
    if hasattr(response, "segments") and response.segments is not None:
        segments = list(response.segments)
    elif isinstance(response, dict) and response.get("segments"):
        segments = response["segments"]
    else:
        raw = response.model_dump() if hasattr(response, "model_dump") else {}
        if isinstance(raw, dict):
            segments = raw.get("segments") or []
    return _coerce_stt_segments(segments)


def transcribe_with_groq_verbose(audio_bytes: bytes, filename: str = "audio.wav") -> List[Dict[str, Any]]:
    from groq import Groq
    client = Groq(api_key=settings.GROQ_API_KEY)
    resp = client.audio.transcriptions.create(
        file=(filename, io.BytesIO(audio_bytes)),
        model=settings.GROQ_STT_MODEL,
        response_format="verbose_json",
        timestamp_granularities=["segment"],
    )
    segments: List[Any] = []
    if hasattr(resp, "segments") and resp.segments is not None:
        segments = list(resp.segments)
    else:
        raw = resp.model_dump() if hasattr(resp, "model_dump") else {}
        segments = (raw.get("segments") or []) if isinstance(raw, dict) else []
    return _coerce_stt_segments(segments)


def transcribe_audio_with_segments(
    audio_bytes: bytes,
    filename: str = "audio.wav",
    duration_sec: Optional[float] = None,
    use_groq: bool = False,
) -> List[Dict[str, Any]]:
    """
    Return [{start, end, text}, ...] for transcript chunking with timecodes.
    Prefers timestamped APIs; falls back to one segment spanning the whole track.
    """
    if use_groq and settings.GROQ_API_KEY:
        try:
            segs = transcribe_with_groq_verbose(audio_bytes, filename)
            if segs:
                return segs
        except Exception as e:
            log.warning("voice.groq_verbose_failed", error=str(e))

    openai_base = (settings.OPENAI_BASE_URL or "").rstrip("/")
    is_real_openai = openai_base in ("", "https://api.openai.com/v1")
    if is_real_openai:
        try:
            segs = transcribe_with_openai_verbose(audio_bytes, filename)
            if segs:
                return segs
        except Exception as e:
            log.warning("voice.openai_verbose_failed", error=str(e))

    text = transcribe_audio(audio_bytes, filename=filename, use_groq=use_groq)
    end_t = float(duration_sec) if duration_sec and duration_sec > 0 else 0.0
    if text.strip():
        return [{"start": 0.0, "end": end_t, "text": text.strip()}]
    return []


# ─── TTS helpers ─────────────────────────────────────────────────────────────

def synthesize_with_deepgram(text: str) -> bytes:
    """
    Synthesize speech using Deepgram Aura (SDK v3 compatible).
    SDK v3.x uses speak.v("1").stream() — save_to_buffer() was added in later versions.
    """
    from deepgram import DeepgramClient, SpeakOptions
    client = DeepgramClient(settings.DEEPGRAM_API_KEY)
    options = SpeakOptions(
        model=settings.DEEPGRAM_TTS_VOICE,
        encoding="mp3",
    )
    response = client.speak.v("1").stream({"text": text}, options)
    # SDK v3: response.stream is a BytesIO; read all bytes
    audio_bytes = response.stream.read()
    if not audio_bytes:
        raise ValueError("Deepgram TTS returned empty audio")
    return audio_bytes


def synthesize_speech(text: str) -> bytes:
    """
    Route to the best available TTS provider.
    Only Deepgram is supported when OPENAI_BASE_URL points to a chat-only
    provider (e.g. EuriAI) that does not implement the audio/speech endpoint.
    """
    if settings.DEEPGRAM_API_KEY:
        try:
            return synthesize_with_deepgram(text)
        except Exception as e:
            log.warning("voice.deepgram_tts_failed", error=str(e))

    # Only attempt OpenAI TTS when the base URL is the real OpenAI endpoint,
    # not a chat-only compatible proxy that lacks audio synthesis.
    openai_base = (settings.OPENAI_BASE_URL or "").rstrip("/")
    is_real_openai = openai_base in ("", "https://api.openai.com/v1")
    if is_real_openai:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL or None)
        response = client.audio.speech.create(
            model="tts-1",
            voice="nova",
            input=text[:4096],
        )
        return response.content

    raise RuntimeError(
        "No TTS provider available. Set DEEPGRAM_API_KEY for Deepgram Aura TTS, "
        "or point OPENAI_BASE_URL at the real OpenAI API."
    )


# ─── Main voice pipeline ─────────────────────────────────────────────────────

def run_voice_pipeline(
    audio_bytes: bytes,
    dept_id: str,
    user_id: str,
    session_id: str,
    filename: str = "audio.webm",
    conversation_history: list = None,
    database_url: str | None = None,
) -> dict:
    """
    Full voice Q&A pipeline:
      audio → STT → RAG (same Phase 1 pipeline) → TTS → MinIO
    Returns dict with transcript, answer_text, audio_url.
    """
    log.info("voice.pipeline_start", dept_id=dept_id, user_id=user_id, audio_size=len(audio_bytes))

    # Guard: reject audio that is clearly too small to contain speech
    if len(audio_bytes) < 1000:
        raise ValueError(
            f"Audio too short ({len(audio_bytes)} bytes). "
            "Please hold the mic button for at least 1 second while speaking."
        )

    # 1. STT
    transcript = transcribe_audio(audio_bytes, filename)
    if not transcript or not transcript.strip():
        raise ValueError(
            "Transcription returned empty text. "
            "Please speak clearly and ensure your microphone is working."
        )
    log.info("voice.transcript", text=transcript[:100])

    # 2. RAG — collect full answer from the orchestrator SSE generator
    from app.agents.orchestrator import run_query_pipeline
    full_answer = ""
    confidence = 0.75
    sources = []

    for chunk in run_query_pipeline(
        query=transcript,
        dept_id=dept_id,
        user_id=user_id,
        session_id=session_id,
        conversation_history=conversation_history or [],
        database_url=database_url,
    ):
        if chunk.startswith("data: "):
            try:
                data = json.loads(chunk[6:].strip())
                if data.get("type") == "metadata":
                    full_answer = data.get("answer", "")
                    confidence = data.get("confidence", 0.75)
                    sources = data.get("sources", [])
            except Exception:
                pass

    if not full_answer:
        full_answer = "I could not find a relevant answer in the knowledge base."

    # 3. TTS — synthesize answer to MP3 (best-effort; pipeline succeeds even if TTS fails)
    audio_url = None
    try:
        audio_bytes_response = synthesize_speech(full_answer)
        # 4. Store in MinIO
        audio_key = f"voice_responses/{dept_id}/{uuid.uuid4()}.mp3"
        upload_file(audio_key, audio_bytes_response, "audio/mpeg")
        audio_url = get_presigned_url(audio_key, expires_seconds=3600)
        log.info("voice.pipeline_complete", confidence=confidence, audio_key=audio_key)
    except Exception as tts_err:
        log.warning("voice.tts_skipped", error=str(tts_err))

    return {
        "transcript": transcript,
        "answer_text": full_answer,
        "audio_url": audio_url,
        "confidence": confidence,
        "sources": sources,
    }
