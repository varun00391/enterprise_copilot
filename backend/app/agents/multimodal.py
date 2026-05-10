"""
Multimodal Agent — handles image + text queries.

Uses Llama 4 Scout on Groq for vision analysis (ChartQA 88.8%, DocVQA 94.4%).
Falls back to GPT-4.1-mini vision if Groq is not configured.
Fuses vision description with RAG chunks for the Reasoning Agent.
"""
import base64
import io
from typing import List, Dict, Any, Optional

import structlog

from app.core.config import settings

log = structlog.get_logger()


def _resize_image(image_bytes: bytes, max_size: int = 2048) -> bytes:
    """Resize image to max_size px on longest side while preserving aspect ratio."""
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes))
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = io.BytesIO()
    fmt = img.format or "JPEG"
    img.save(buf, format=fmt)
    return buf.getvalue()


def _image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def describe_image_with_groq(image_bytes: bytes, query: str) -> str:
    """Analyze image using Llama 4 Scout on Groq."""
    from groq import Groq
    client = Groq(api_key=settings.GROQ_API_KEY)

    resized = _resize_image(image_bytes)
    b64 = _image_to_base64(resized)

    # Detect mime type
    mime = "image/jpeg"
    if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        mime = "image/png"

    response = client.chat.completions.create(
        model=settings.GROQ_VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Analyze this image in the context of the following question: {query}\n\n"
                            "Describe what you see in detail, focusing on information relevant to the question. "
                            "If this is a chart or graph, describe the data trends and key values. "
                            "If this is a document, extract the key text and structure."
                        ),
                    },
                ],
            }
        ],
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""


def describe_image_with_openai(image_bytes: bytes, query: str, presigned_url: Optional[str] = None) -> str:
    """Analyze image using GPT-4o vision (fallback)."""
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    if presigned_url:
        image_content = {"type": "image_url", "image_url": {"url": presigned_url}}
    else:
        resized = _resize_image(image_bytes)
        b64 = _image_to_base64(resized)
        mime = "image/png" if image_bytes[:8] == b'\x89PNG\r\n\x1a\n' else "image/jpeg"
        image_content = {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    image_content,
                    {
                        "type": "text",
                        "text": (
                            f"Analyze this image for the question: {query}\n"
                            "Describe key information, data, charts, or text visible in the image."
                        ),
                    },
                ],
            }
        ],
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""


def describe_image(
    image_bytes: bytes,
    query: str,
    presigned_url: Optional[str] = None,
) -> str:
    """Route to best available vision provider."""
    if settings.GROQ_API_KEY:
        try:
            return describe_image_with_groq(image_bytes, query)
        except Exception as e:
            log.warning("multimodal.groq_vision_failed", error=str(e))
    return describe_image_with_openai(image_bytes, query, presigned_url)


def run_multimodal_query(
    query: str,
    image_bytes: bytes,
    dept_id: str,
    user_id: str,
    session_id: str,
    conversation_history: list = None,
    image_presigned_url: Optional[str] = None,
    lf_client=None,
) -> dict:
    """
    Full multimodal pipeline:
    1. Vision analysis of image (Llama 4 Scout / GPT-4o)
    2. Hybrid RAG retrieval (same Phase 1 pipeline)
    3. Reasoning with fused context (vision + document chunks)
    Returns streaming-ready result with answer, confidence, sources.
    """
    log.info("multimodal.start", dept_id=dept_id, query=query[:100])

    # 1. Vision description
    vision_description = describe_image(image_bytes, query, image_presigned_url)
    log.info("multimodal.vision_complete", desc_len=len(vision_description))

    # 2. Retrieve relevant document chunks
    from app.agents.retrieval import hybrid_search
    chunks = hybrid_search(query=query, dept_id=dept_id)

    # 3. Fuse vision output with doc chunks and reason
    from app.agents.reasoning import stream_answer

    # Prepend vision context as a synthetic chunk
    vision_chunk = {
        "id": "vision-0",
        "score": 1.0,
        "content": f"[Image Analysis]\n{vision_description}",
        "doc_id": "image_attachment",
        "doc_name": "Attached Image",
        "chunk_index": 0,
        "file_type": "image",
        "page": None,
    }
    fused_chunks = [vision_chunk] + chunks

    return {
        "chunks": fused_chunks,
        "vision_description": vision_description,
        "stream_generator": stream_answer(
            query=query,
            chunks=fused_chunks,
            conversation_history=conversation_history or [],
            lf_client=lf_client,
        ),
    }
