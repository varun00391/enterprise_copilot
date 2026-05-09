"""
Reasoning Agent — constructs prompts from retrieved context + conversation
history, calls the LLM with chain-of-thought, and returns a streamed answer
with citations and confidence estimation.
"""
from typing import List, Dict, Any, Generator, AsyncGenerator, Optional
import json

import structlog
from openai import OpenAI

from app.core.config import settings

log = structlog.get_logger()

SYSTEM_PROMPT = """You are OrgMind, an expert AI knowledge assistant for enterprise departments.
Your role is to answer questions accurately using ONLY the provided document context.

Guidelines:
- Base your answer exclusively on the provided context chunks
- Context may include an [Attached Image] or "Attached Image" source with a vision-derived description — treat it as the user's uploaded image and cite it as [Source 1] when that source is listed first and documents the image analysis
- Context may cite **videos** — lines often include transcript spans (`Video transcript`) or sampled frames (`Video frame`). When a source exposes timecodes in the excerpt, mention those times in your answer (for example cite the approximate minute:second span and document filename).
- Context may include **[Knowledge graph]** lines listing entities and relations extracted from documents — use as structured hints; still cite [Source N] chunks when answering factual detail
- Other sources are numbered [Source 2], [Source 3], etc., in order
- Always cite which document/chunk you used (reference by [Source N])
- If the context does not contain enough information, say "I don't have enough information in the knowledge base to answer this accurately"
- Provide clear, structured answers with bullet points where appropriate
- Include a brief chain-of-thought reasoning before your final answer
- Estimate your confidence (0.0 to 1.0) based on how well the context supports the answer

Response format:
<reasoning>Your step-by-step thinking here</reasoning>
<answer>Your final answer here with [Source N] citations</answer>
<confidence>0.85</confidence>
"""


def _fmt_sec(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    if h:
        return f"{h}:{m:02d}:{s:05.2f}"
    if m:
        return f"{m}:{s:05.2f}"
    return f"{s:.1f}s"


def _sources_from_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in chunks:
        src = {
            "doc_id": c.get("doc_id"),
            "doc_name": c.get("doc_name"),
            "chunk_index": c.get("chunk_index"),
            "content": c.get("content", "")[:300],
            "score": c.get("score", 0),
            "page": c.get("page"),
            "source_url": c.get("source_url"),
        }
        if c.get("t_start_sec") is not None:
            src["t_start_sec"] = c.get("t_start_sec")
        if c.get("t_end_sec") is not None:
            src["t_end_sec"] = c.get("t_end_sec")
        if c.get("modality"):
            src["modality"] = c.get("modality")
        out.append(src)
    return out


def _build_context_block(chunks: List[Dict[str, Any]]) -> str:
    if not chunks:
        return "No relevant documents found in the knowledge base."

    lines = []
    for i, chunk in enumerate(chunks, 1):
        t0 = chunk.get("t_start_sec")
        mod = chunk.get("modality")
        extra_bits = []
        if t0 is not None:
            try:
                t1 = chunk.get("t_end_sec")
                extra_bits.append(f"t≈{_fmt_sec(float(t0))}–{_fmt_sec(float(t1))}" if t1 is not None else f"t≈{_fmt_sec(float(t0))}")
            except (TypeError, ValueError):
                pass
        if mod:
            extra_bits.append(str(mod))
        trail = (" — " + ", ".join(extra_bits)) if extra_bits else ""
        lines.append(
            f"[Source {i}] {chunk.get('doc_name', 'Unknown')} (chunk {chunk.get('chunk_index', 0)}){trail}:"
        )
        lines.append(chunk.get("content", ""))
        lines.append("")
    return "\n".join(lines)


def _parse_response(raw: str) -> tuple[str, float]:
    """Extract answer text and confidence from structured LLM response."""
    answer = raw
    confidence = 0.75

    if "<answer>" in raw and "</answer>" in raw:
        start = raw.index("<answer>") + len("<answer>")
        end = raw.index("</answer>")
        answer = raw[start:end].strip()

    if "<confidence>" in raw and "</confidence>" in raw:
        try:
            start = raw.index("<confidence>") + len("<confidence>")
            end = raw.index("</confidence>")
            confidence = float(raw[start:end].strip())
            confidence = max(0.0, min(1.0, confidence))
        except (ValueError, IndexError):
            pass

    return answer, confidence


def generate_answer(
    query: str,
    chunks: List[Dict[str, Any]],
    conversation_history: List[Dict[str, str]] = None,
) -> tuple[str, float, List[Dict]]:
    """
    Generate an answer synchronously. Returns (answer, confidence, sources).
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    context = _build_context_block(chunks)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if conversation_history:
        for turn in conversation_history[-10:]:
            messages.append({"role": turn["role"], "content": turn["content"]})

    user_message = f"""Context from knowledge base:
{context}

Question: {query}"""

    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model=settings.OPENAI_CHAT_MODEL,
        messages=messages,
        temperature=0.1,
        max_tokens=1500,
    )

    raw = response.choices[0].message.content or ""
    answer, confidence = _parse_response(raw)

    sources = _sources_from_chunks(chunks)

    log.info("reasoning.complete", confidence=confidence, sources=len(sources))
    return answer, confidence, sources


def stream_answer(
    query: str,
    chunks: List[Dict[str, Any]],
    conversation_history: List[Dict[str, str]] = None,
) -> Generator[str, None, None]:
    """
    Collects the full LLM response, parses out the clean answer,
    then yields SSE token + metadata + suggested_followups events.
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    context = _build_context_block(chunks)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if conversation_history:
        for turn in conversation_history[-10:]:
            messages.append({"role": turn["role"], "content": turn["content"]})

    messages.append({
        "role": "user",
        "content": f"Context from knowledge base:\n{context}\n\nQuestion: {query}",
    })

    full_response = ""
    try:
        stream = client.chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL,
            messages=messages,
            temperature=0.1,
            max_tokens=1500,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                full_response += delta

    except Exception as e:
        log.error("reasoning.stream_error", error=str(e))
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        return

    answer, confidence = _parse_response(full_response)

    sources = _sources_from_chunks(chunks)

    # Stream the clean answer as a single token so the frontend shows it immediately
    yield f"data: {json.dumps({'type': 'token', 'content': answer})}\n\n"

    # Generate suggested follow-up questions (non-blocking second LLM call)
    suggested_followups = []
    try:
        followup_prompt = (
            f"Based on this Q&A exchange, suggest exactly 3 short follow-up questions a user might ask next.\n\n"
            f"Question: {query}\n"
            f"Answer: {answer[:500]}\n\n"
            "Output only the 3 questions as a JSON array of strings, no explanation.\n"
            'Example: ["What is X?", "How does Y work?", "Can you explain Z?"]'
        )
        fu_resp = client.chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL,
            messages=[{"role": "user", "content": followup_prompt}],
            temperature=0.7,
            max_tokens=200,
        )
        fu_text = (fu_resp.choices[0].message.content or "").strip()
        if fu_text.startswith("["):
            suggested_followups = json.loads(fu_text)[:3]
    except Exception:
        pass

    metadata = {
        "type": "metadata",
        "answer": answer,
        "confidence": confidence,
        "sources": sources,
        "suggested_followups": suggested_followups,
    }
    yield f"data: {json.dumps(metadata)}\n\n"
    yield "data: [DONE]\n\n"


def stream_answer_analytics(
    query: str,
    chunks: List[Dict[str, Any]],
    conversation_history: List[Dict[str, str]] = None,
    spreadsheet_bytes: Optional[bytes] = None,
    spreadsheet_type: Optional[str] = None,
    chart_description: Optional[str] = None,
) -> Generator[str, None, None]:
    """
    Non-streaming analytics LLM call packaged as SSE (token + metadata + follow-ups)
    for compatibility with the chat UI.
    """
    from app.agents.analytics_agent import generate_analytics_answer

    try:
        answer, confidence, sources = generate_analytics_answer(
            query=query,
            chunks=chunks,
            spreadsheet_bytes=spreadsheet_bytes,
            spreadsheet_type=spreadsheet_type,
            conversation_history=conversation_history or [],
            chart_description=chart_description,
        )
    except Exception as e:
        log.error("reasoning.analytics_error", error=str(e))
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        return

    yield f"data: {json.dumps({'type': 'token', 'content': answer})}\n\n"

    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    suggested_followups: List[str] = []
    try:
        followup_prompt = (
            f"Based on this Q&A exchange, suggest exactly 3 short follow-up questions a user might ask next.\n\n"
            f"Question: {query}\n"
            f"Answer: {answer[:500]}\n\n"
            "Output only the 3 questions as a JSON array of strings, no explanation.\n"
            'Example: ["What is X?", "How does Y work?", "Can you explain Z?"]'
        )
        fu_resp = client.chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL,
            messages=[{"role": "user", "content": followup_prompt}],
            temperature=0.7,
            max_tokens=200,
        )
        fu_text = (fu_resp.choices[0].message.content or "").strip()
        if fu_text.startswith("["):
            suggested_followups = json.loads(fu_text)[:3]
    except Exception:
        pass

    metadata = {
        "type": "metadata",
        "answer": answer,
        "confidence": confidence,
        "sources": sources,
        "suggested_followups": suggested_followups,
    }
    yield f"data: {json.dumps(metadata)}\n\n"
    yield "data: [DONE]\n\n"
