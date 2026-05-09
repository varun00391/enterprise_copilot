import hashlib
import threading
import uuid
from typing import List, Optional
from datetime import date

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, BackgroundTasks
from pydantic import BaseModel, HttpUrl, model_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.models import Document, User, AuditLog
from app.schemas.schemas import DocumentOut, DocumentStatusOut
from app.services.storage import upload_file, delete_file
from app.agents.ingestion import ingest_document, delete_document_vectors

log = structlog.get_logger()

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {
    "pdf", "docx", "txt", "xlsx", "xls", "csv", "json",
    "png", "jpg", "jpeg",
    "pptx",           # Phase 2
    "mp3", "wav", "m4a", "ogg",  # Phase 2 audio
}
# Containers/codecs decoded by ffmpeg in the backend (Phase 3 video)
VIDEO_EXTENSIONS = {
    "mp4", "mov", "m4v", "webm", "mkv", "avi", "wmv", "flv",
    "mpg", "mpeg", "3gp", "3g2", "ogv", "ts", "m2ts", "vob",
    "f4v", "asf", "divx", "mxf",
}
ALLOWED_EXTENSIONS |= VIDEO_EXTENSIONS
MAX_FILE_SIZE_BYTES = settings.MAX_FILE_SIZE_MB * 1024 * 1024


def _get_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _process_document_bg(
    doc_id: str,
    dept_id: str,
    file_bytes: bytes,
    file_type: str,
    filename: str,
    metadata: dict,
    db_url: str,
):
    """Background task to run the ingestion pipeline."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.models import Document as DocModel

    engine = create_engine(db_url)
    SessionBG = sessionmaker(bind=engine)
    db = SessionBG()

    try:
        doc_pk = uuid.UUID(doc_id) if isinstance(doc_id, str) else doc_id
        doc = db.query(DocModel).filter(DocModel.id == doc_pk).first()
        if not doc:
            log.warning("documents.bg_doc_not_found_skip", doc_id=doc_id)
            return

        doc.status = "parsing"
        db.commit()

        doc.status = "chunking"
        db.commit()

        doc.status = "embedding"
        db.commit()

        if file_type in VIDEO_EXTENSIONS:
            from app.agents.video_agent import run_video_ingestion_graph

            chunk_count = run_video_ingestion_graph(
                file_bytes=file_bytes,
                file_type=file_type,
                filename=filename,
                doc_id=doc_id,
                dept_id=dept_id,
                metadata=metadata,
            )
        else:
            chunk_count = ingest_document(
                file_bytes=file_bytes,
                file_type=file_type,
                filename=filename,
                doc_id=doc_id,
                dept_id=dept_id,
                metadata=metadata,
            )

        doc.status = "indexed"
        doc.chunk_count = chunk_count
        db.commit()
        log.info("documents.indexed", doc_id=doc_id, chunks=chunk_count)

    except Exception as e:
        log.error("documents.ingestion_failed", doc_id=doc_id, error=str(e))
        try:
            pk = uuid.UUID(doc_id) if isinstance(doc_id, str) else doc_id
        except (ValueError, TypeError):
            pk = None
        if pk is not None:
            if row := db.query(DocModel).filter(DocModel.id == pk).first():
                row.status = "failed"
                row.error_message = str(e)[:500]
                db.commit()
    finally:
        db.close()
        engine.dispose()


def _schedule_document_ingestion(**kwargs) -> None:
    """Run ingestion in a daemon thread so multiple uploads process concurrently."""
    threading.Thread(target=_process_document_bg, kwargs=kwargs, daemon=True).start()


@router.post("/upload", response_model=List[DocumentOut])
async def upload_documents(
    files: List[UploadFile] = File(...),
    category: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.dept_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a department")

    if len(files) > settings.MAX_FILES_PER_BATCH:
        raise HTTPException(status_code=400, detail=f"Maximum {settings.MAX_FILES_PER_BATCH} files per batch")

    results = []
    dept_id = str(current_user.dept_id)
    seen_hashes_this_request: set[str] = set()

    for upload in files:
        ext = _get_extension(upload.filename or "unknown")
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"File type '.{ext}' is not supported")

        file_bytes = await upload.read()

        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=400, detail=f"File '{upload.filename}' exceeds {settings.MAX_FILE_SIZE_MB}MB limit")

        sha256 = hashlib.sha256(file_bytes).hexdigest()
        if sha256 in seen_hashes_this_request:
            raise HTTPException(
                status_code=400,
                detail="This upload repeats the same file content more than once. Remove duplicate copies from the batch.",
            )
        seen_hashes_this_request.add(sha256)
        existing = db.query(Document).filter(
            Document.sha256_hash == sha256,
            Document.dept_id == current_user.dept_id,
        ).first()
        if existing:
            if existing.status == "failed":
                # Clean up the failed attempt so the user can retry
                try:
                    delete_file(existing.minio_path)
                except Exception:
                    pass
                try:
                    delete_document_vectors(str(existing.id), str(existing.dept_id))
                except Exception:
                    pass
                try:
                    from app.services.graph_store import delete_graph_for_document

                    delete_graph_for_document(str(existing.dept_id), str(existing.id))
                except Exception:
                    pass
                db.delete(existing)
                db.commit()
            else:
                raise HTTPException(status_code=409, detail=f"'{upload.filename}' already exists in the knowledge base")

        doc_id = str(uuid.uuid4())
        minio_path = f"{dept_id}/{doc_id}/{upload.filename}"
        upload_file(minio_path, file_bytes, upload.content_type or "application/octet-stream")

        doc = Document(
            id=uuid.UUID(doc_id),
            filename=upload.filename or doc_id,
            original_name=upload.filename or doc_id,
            dept_id=current_user.dept_id,
            uploaded_by=current_user.id,
            file_type=ext,
            status="uploaded",
            sha256_hash=sha256,
            minio_path=minio_path,
            file_size_bytes=len(file_bytes),
            category=category,
            author=author,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        metadata = {"created_at": str(doc.created_at), "category": category or "", "author": author or ""}
        _schedule_document_ingestion(
            doc_id=doc_id,
            dept_id=dept_id,
            file_bytes=file_bytes,
            file_type=ext,
            filename=upload.filename or doc_id,
            metadata=metadata,
            db_url=settings.DATABASE_URL,
        )

        audit = AuditLog(
            actor_id=current_user.id,
            actor_email=current_user.email,
            action="document.upload",
            target_type="document",
            target_id=doc_id,
        )
        db.add(audit)
        db.commit()
        results.append(doc)

    return results


@router.get("", response_model=List[DocumentOut])
def list_documents(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Document).filter(Document.dept_id == current_user.dept_id)
    if status:
        query = query.filter(Document.status == status)
    return query.order_by(Document.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{doc_id}/status", response_model=DocumentStatusOut)
def get_document_status(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.dept_id == current_user.dept_id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if current_user.role != "super_admin" and str(doc.dept_id) != str(current_user.dept_id):
        raise HTTPException(status_code=403, detail="Access denied")

    delete_file(doc.minio_path)
    delete_document_vectors(str(doc.id), str(doc.dept_id))
    try:
        from app.services.graph_store import delete_graph_for_document

        delete_graph_for_document(str(doc.dept_id), str(doc.id))
    except Exception:
        pass
    db.delete(doc)

    audit = AuditLog(
        actor_id=current_user.id,
        actor_email=current_user.email,
        action="document.delete",
        target_type="document",
        target_id=doc_id,
    )
    db.add(audit)
    db.commit()


# ─── Web Crawl (Phase 2 single-site + Phase 3 bulk / sitemap) ────────────────

class CrawlRequest(BaseModel):
    urls: List[str]
    crawl_mode: str = "auto"
    max_depth: Optional[int] = None
    max_pages_per_seed: Optional[int] = None
    max_pages_per_url: Optional[int] = None
    max_pages_total: Optional[int] = None

    @model_validator(mode="after")
    def _legacy_pages_field(self):
        if self.max_pages_per_seed is None and self.max_pages_per_url is not None:
            self.max_pages_per_seed = self.max_pages_per_url
        return self


def _make_crawl_placeholder_doc(db: Session, user: User, url: str, label: Optional[str] = None) -> tuple[str, Document]:
    doc_id = str(uuid.uuid4())
    sha = hashlib.sha256(url.encode()).hexdigest()
    display = (label or url)[:500]
    doc = Document(
        id=doc_id,
        filename=f"web_{sha[:8]}.txt",
        original_name=display,
        dept_id=user.dept_id,
        uploaded_by=user.id,
        file_type="url",
        status="uploaded",
        sha256_hash=sha,
        minio_path=f"crawl/{doc_id}/content.txt",
        source_type="web_crawl",
        source_url=url[:2000],
    )
    db.add(doc)
    return doc_id, doc


def _ingest_crawl_pages_for_root(
    bg_db,
    pages: List[dict],
    root_doc: Document,
    dept_id: str,
    uploaded_by_id,
    extra_metadata: Optional[dict] = None,
):
    """One DB row + vector doc_id per crawled page; reuses root_doc for the first page."""
    import re

    if extra_metadata is None:
        extra_metadata = {}
    indexed_any = False
    for i, page in enumerate(pages):
        content = page.get("content") or ""
        if not content.strip():
            continue
        content_bytes = content.encode("utf-8")
        body_hash = hashlib.sha256(content_bytes).hexdigest()
        purl = page.get("url") or ""
        title = page.get("title") or purl
        md = {**extra_metadata, "source_url": purl, "title": title}
        if i == 0:
            doc_row = root_doc
            doc_id_str = str(root_doc.id)
        else:
            doc_id_str = str(uuid.uuid4())
            doc_row = Document(
                id=doc_id_str,
                filename=f"web_{body_hash[:12]}.txt",
                original_name=purl[:500],
                dept_id=root_doc.dept_id,
                uploaded_by=uploaded_by_id,
                file_type="url",
                status="parsing",
                sha256_hash=body_hash,
                minio_path=f"crawl/{doc_id_str}/content.txt",
                source_type="web_crawl",
                source_url=purl[:2000],
            )
            bg_db.add(doc_row)
            bg_db.flush()

        doc_row.status = "parsing"
        bg_db.commit()
        try:
            safe_name = re.sub(r"[^\w\-./]+", "_", str(title))[:120] + ".txt"
            n_chunks = ingest_document(
                file_bytes=content_bytes,
                file_type="txt",
                filename=safe_name,
                doc_id=doc_id_str,
                dept_id=dept_id,
                metadata=md,
            )
            doc_row.chunk_count = n_chunks
            doc_row.status = "indexed"
            doc_row.sha256_hash = body_hash
            doc_row.source_url = purl[:2000]
            doc_row.original_name = purl[:500]
            indexed_any = True
        except Exception as page_err:
            log.error("crawl.page_ingest_failed", url=purl, error=str(page_err))
            doc_row.status = "failed"
            doc_row.error_message = str(page_err)[:500]
        bg_db.commit()

    if not indexed_any and pages:
        root_doc.status = "failed"
        root_doc.error_message = "All crawled pages failed ingestion"
        bg_db.commit()


def _crawl_background(
    job_kind: str,
    dept_id: str,
    user_id: str,
    db_url: str,
    seed_urls: List[str],
    doc_ids: List[str],
    max_depth: int,
    max_pages_per_seed: int,
    max_pages_total: int,
):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.agents.web_crawl import crawl_pages, expand_sitemap_urls

    engine = create_engine(db_url)
    BgSession = sessionmaker(bind=engine)
    bg_db = BgSession()

    try:
        if job_kind == "sitemap":
            doc = bg_db.query(Document).filter(Document.id == doc_ids[0]).first()
            if not doc:
                return
            try:
                doc.status = "parsing"
                bg_db.commit()
                entry = seed_urls[0]
                page_urls = expand_sitemap_urls(entry, max_urls=max_pages_total)
                if not page_urls:
                    doc.status = "failed"
                    doc.error_message = "Sitemap contained no URLs"
                    bg_db.commit()
                    return
                cap = min(len(page_urls), max_pages_total)
                pages = crawl_pages(
                    page_urls[:cap],
                    max_depth=0,
                    max_pages=cap,
                    follow_links=False,
                )
                if not pages:
                    doc.status = "failed"
                    doc.error_message = "No crawlable content from sitemap URLs"
                    bg_db.commit()
                    return
                uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
                _ingest_crawl_pages_for_root(bg_db, pages, doc, dept_id, uid, {})
            except Exception as e:
                log.error("crawl.sitemap_job_failed", error=str(e))
                if doc:
                    doc.status = "failed"
                    doc.error_message = str(e)[:500]
                    bg_db.commit()
            return

        for seed_url, doc_id in zip(seed_urls, doc_ids):
            doc = bg_db.query(Document).filter(Document.id == doc_id).first()
            if not doc:
                continue
            try:
                doc.status = "parsing"
                bg_db.commit()
                pages = crawl_pages(
                    [seed_url],
                    max_depth=max_depth,
                    max_pages=max_pages_per_seed,
                    follow_links=True,
                )
                if not pages:
                    doc.status = "failed"
                    doc.error_message = "No content found at URL"
                    bg_db.commit()
                    continue
                uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
                _ingest_crawl_pages_for_root(bg_db, pages, doc, dept_id, uid, {})
            except Exception as e:
                log.error("crawl.url_failed", url=seed_url, error=str(e))
                doc.status = "failed"
                doc.error_message = str(e)[:500]
                bg_db.commit()
    finally:
        bg_db.close()


def schedule_web_crawl_job(
    background_tasks: BackgroundTasks,
    db: Session,
    current_user: User,
    urls: List[str],
    crawl_mode: str = "auto",
    max_depth: Optional[int] = None,
    max_pages_per_seed: Optional[int] = None,
    max_pages_total: Optional[int] = None,
) -> dict:
    from app.agents.web_crawl import looks_like_sitemap_url, normalize_http_url

    if not current_user.dept_id:
        raise HTTPException(status_code=400, detail="User is not assigned to a department")
    raw = [u for u in urls if u and str(u).strip()]
    if not raw:
        raise HTTPException(status_code=400, detail="No URLs provided")

    normalized = [normalize_http_url(u.strip()) for u in raw]

    mode = (crawl_mode or "auto").lower().strip()
    if mode not in ("auto", "site_pages", "sitemap"):
        raise HTTPException(status_code=400, detail="crawl_mode must be auto, site_pages, or sitemap")

    effective = mode
    if mode == "auto":
        effective = "sitemap" if len(normalized) == 1 and looks_like_sitemap_url(normalized[0]) else "site_pages"
    elif mode == "sitemap" and len(normalized) != 1:
        raise HTTPException(status_code=400, detail="Sitemap crawl requires exactly one URL")

    if effective == "site_pages" and len(normalized) > settings.CRAWL_MAX_SEED_URLS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {settings.CRAWL_MAX_SEED_URLS} seed URLs per batch",
        )

    max_ptotal = max_pages_total if max_pages_total is not None else settings.CRAWL_MAX_PAGES_TOTAL
    max_pseed = max_pages_per_seed if max_pages_per_seed is not None else settings.CRAWL_MAX_PAGES_PER_URL
    depth = max_depth if max_depth is not None else settings.CRAWL_MAX_DEPTH

    doc_ids: List[str] = []
    results: List[dict] = []

    if effective == "sitemap":
        u = normalized[0]
        doc_id, _ = _make_crawl_placeholder_doc(db, current_user, u, label=f"Sitemap: {u[:240]}")
        doc_ids.append(doc_id)
        results.append({"url": u, "doc_id": doc_id, "status": "queued", "crawl_mode": "sitemap"})
    else:
        for u in normalized:
            doc_id, _ = _make_crawl_placeholder_doc(db, current_user, u)
            doc_ids.append(doc_id)
            results.append({"url": u, "doc_id": doc_id, "status": "queued", "crawl_mode": "site_pages"})

    db.add(
        AuditLog(
            actor_id=current_user.id,
            actor_email=current_user.email,
            action="document.crawl",
            target_type="crawl_batch",
            target_id=",".join(doc_ids),
        )
    )
    db.commit()

    background_tasks.add_task(
        _crawl_background,
        job_kind=effective,
        dept_id=str(current_user.dept_id),
        user_id=str(current_user.id),
        db_url=settings.DATABASE_URL,
        seed_urls=normalized,
        doc_ids=doc_ids,
        max_depth=depth,
        max_pages_per_seed=max_pseed,
        max_pages_total=max_ptotal,
    )
    return {"submitted": len(results), "documents": results, "crawl_mode": effective}


@router.post("/crawl")
def submit_crawl(
    payload: CrawlRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit seed URLs or a sitemap URL for web crawl ingestion (bulk + link following)."""
    return schedule_web_crawl_job(
        background_tasks,
        db,
        current_user,
        payload.urls,
        crawl_mode=payload.crawl_mode,
        max_depth=payload.max_depth,
        max_pages_per_seed=payload.max_pages_per_seed,
        max_pages_total=payload.max_pages_total,
    )
