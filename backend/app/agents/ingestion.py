"""
Ingestion Agent — parses documents, chunks text, generates embeddings,
and stores vectors in Qdrant with department namespace isolation.
"""
import hashlib
import io
import json
import re
import uuid
from typing import List, Dict, Any

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, PayloadSchemaType

from app.core.config import settings
from app.services.embeddings import embed_texts

log = structlog.get_logger()

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
VECTOR_DIM = 1536  # text-embedding-3-small

_VISION_PAGE_PROMPT = (
    "Extract every readable string. For charts, graphs, tables, or diagrams, "
    "state axes, units, legend, series names, trends, and important numbers. "
    "For screenshots of UIs, describe labels and controls."
)


def _pdf_pages_vision_descriptions(file_bytes: bytes, max_pages: int) -> List[str]:
    """Rasterize PDF pages and run the vision model (same path as raster images)."""
    import fitz  # PyMuPDF
    from app.agents.multimodal import describe_image

    descriptions: List[str] = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        n = min(doc.page_count, max(1, max_pages))
        for i in range(n):
            page = doc.load_page(i)
            mat = fitz.Matrix(1.5, 1.5)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            png_bytes = pix.tobytes("png")
            try:
                desc = describe_image(png_bytes, _VISION_PAGE_PROMPT).strip()
                if desc:
                    descriptions.append(f"[Page {i + 1} — visual analysis]\n{desc}")
            except Exception as e:
                log.warning("ingestion.pdf_page_vision_failed", page=i + 1, error=str(e))
    finally:
        doc.close()
    return descriptions


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.QDRANT_URL)


def ensure_collection(client: QdrantClient, dept_id: str) -> None:
    collection_name = f"dept_{dept_id}"
    existing = [c.name for c in client.get_collections().collections]
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )


def _parse_document(file_bytes: bytes, file_type: str, filename: str) -> str:
    """Extract raw text from a document given its bytes and type."""
    ext = file_type.lower().lstrip(".")
    text = ""

    if ext == "pdf":
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        native_text = "".join(page.get_text() for page in doc)
        doc.close()
        native_len = len(native_text.strip())

        text = native_text
        ocr_fallback = False
        if native_len < settings.INGEST_PDF_OCR_FALLBACK_THRESHOLD:
            from unstructured.partition.pdf import partition_pdf
            elements = partition_pdf(file=io.BytesIO(file_bytes))
            text = "\n".join(str(el) for el in elements)
            ocr_fallback = True

        skip_vision = (
            not ocr_fallback
            and native_len >= settings.INGEST_PDF_VISION_SKIP_IF_NATIVE_CHARS
        )
        if not skip_vision:
            try:
                page_desc = _pdf_pages_vision_descriptions(
                    file_bytes,
                    max_pages=settings.INGEST_PDF_VISION_MAX_PAGES,
                )
                if page_desc:
                    parts = [text.strip()] if text.strip() else []
                    parts.extend(page_desc)
                    text = "\n\n".join(p for p in parts if p)
            except Exception as e:
                log.warning("ingestion.pdf_vision_failed", error=str(e))

    elif ext == "docx":
        import docx as python_docx
        doc = python_docx.Document(io.BytesIO(file_bytes))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    elif ext in ("xlsx", "xls"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
        rows = []
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                row_str = " | ".join(str(c) for c in row if c is not None)
                if row_str.strip():
                    rows.append(row_str)
        text = "\n".join(rows)

    elif ext == "csv":
        import csv
        reader = csv.reader(io.StringIO(file_bytes.decode("utf-8", errors="replace")))
        text = "\n".join(" | ".join(row) for row in reader)

    elif ext == "txt":
        text = file_bytes.decode("utf-8", errors="replace")

    elif ext == "json":
        try:
            data = json.loads(file_bytes.decode("utf-8", errors="replace"))
            text = json.dumps(data, indent=2)
        except json.JSONDecodeError:
            text = file_bytes.decode("utf-8", errors="replace")

    elif ext in ("png", "jpg", "jpeg"):
        from unstructured.partition.image import partition_image
        elements = partition_image(file=io.BytesIO(file_bytes))
        ocr_text = "\n".join(str(el) for el in elements).strip()

        # Vision augments OCR—especially for charts, diagrams, and UI screenshots
        # where Tesseract misses structure. Merged into one document for RAG.
        vision_text = ""
        try:
            from app.agents.multimodal import describe_image
            vision_text = describe_image(
                file_bytes,
                _VISION_PAGE_PROMPT,
            ).strip()
        except Exception as e:
            log.warning("ingestion.image_vision_failed", error=str(e))

        parts = []
        if ocr_text:
            parts.append(ocr_text)
        if vision_text:
            parts.append(f"[Visual analysis]\n{vision_text}")
        text = "\n\n".join(parts)

    elif ext == "pptx":
        from pptx import Presentation
        prs = Presentation(io.BytesIO(file_bytes))
        slide_texts = []
        for slide_num, slide in enumerate(prs.slides, 1):
            parts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    parts.append(shape.text.strip())
            # Include speaker notes
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    parts.append(f"[Notes]: {notes}")
            if parts:
                slide_texts.append(f"--- Slide {slide_num} ---\n" + "\n".join(parts))
        text = "\n\n".join(slide_texts)

    elif ext in ("mp3", "wav", "m4a", "ogg", "webm"):
        # Audio transcription via Groq Whisper (batch) or OpenAI Whisper
        from app.agents.voice import transcribe_audio
        fname = filename if filename.endswith(f".{ext}") else f"audio.{ext}"
        text = transcribe_audio(file_bytes, filename=fname, use_groq=True)

    else:
        text = file_bytes.decode("utf-8", errors="replace")

    return text.strip()


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Recursive character text splitter with token-approximate chunking."""
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def ingest_document(
    file_bytes: bytes,
    file_type: str,
    filename: str,
    doc_id: str,
    dept_id: str,
    metadata: Dict[str, Any] = None,
) -> int:
    """
    Full ingestion pipeline: parse → chunk → embed → store in Qdrant.
    Returns number of chunks indexed.
    """
    if metadata is None:
        metadata = {}

    log.info("ingestion.start", doc_id=doc_id, dept_id=dept_id, file_type=file_type)

    text = _parse_document(file_bytes, file_type, filename)
    if not text:
        raise ValueError("No text could be extracted from document")

    chunks = _chunk_text(text)
    if not chunks:
        raise ValueError("Document produced no chunks after splitting")

    log.info("ingestion.chunks_created", count=len(chunks), doc_id=doc_id)

    batch_size = 50
    client = get_qdrant_client()
    ensure_collection(client, dept_id)
    collection_name = f"dept_{dept_id}"

    total_indexed = 0
    for i in range(0, len(chunks), batch_size):
        batch_chunks = chunks[i : i + batch_size]
        embeddings = embed_texts(batch_chunks)

        points = []
        for j, (chunk, vector) in enumerate(zip(batch_chunks, embeddings)):
            chunk_idx = i + j
            point_id = str(uuid.uuid4())
            title = metadata.get("title") or ""
            source_url = metadata.get("source_url", "") or ""
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "doc_id": doc_id,
                        "dept_id": dept_id,
                        "filename": filename,
                        "chunk_index": chunk_idx,
                        "content": chunk,
                        "file_type": file_type,
                        "timestamp": metadata.get("created_at", ""),
                        "category": metadata.get("category", ""),
                        "author": metadata.get("author", ""),
                        "source_url": source_url,
                        "source_title": title,
                    },
                )
            )

        client.upsert(collection_name=collection_name, points=points)
        total_indexed += len(points)

    log.info("ingestion.complete", doc_id=doc_id, chunks=total_indexed)

    if settings.neo4j_configured and settings.GRAPH_BUILD_ON_INGEST:
        try:
            from app.agents.graph_ingest import ingest_graph_for_document

            ingest_graph_for_document(dept_id, doc_id, filename, chunks)
        except Exception as e:
            log.warning("ingestion.graph_build_failed", doc_id=doc_id, error=str(e))

    return total_indexed


def delete_document_vectors(doc_id: str, dept_id: str) -> None:
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    client = get_qdrant_client()
    collection_name = f"dept_{dept_id}"
    try:
        client.delete(
            collection_name=collection_name,
            points_selector=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
        )
    except Exception:
        pass
