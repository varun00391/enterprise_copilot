from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    DATABASE_URL: str = "postgresql://orgmind:orgmind_secret@localhost:5432/orgmind"

    QDRANT_URL: str = "http://localhost:6333"

    REDIS_URL: str = "redis://localhost:6379/0"

    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "orgmind_minio"
    MINIO_SECRET_KEY: str = "orgmind_minio_secret"
    MINIO_BUCKET: str = "orgmind-documents"
    MINIO_SECURE: bool = False

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.euron.one/api/v1/euri"
    OPENAI_CHAT_MODEL: str = "gpt-4o"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # Browser-visible app URL for OAuth return redirect (omit to use first entry in CORS_ORIGINS).
    FRONTEND_PUBLIC_URL: str = ""

    RATE_LIMIT_PER_MINUTE: int = 100
    MAX_FILE_SIZE_MB: int = 50
    MAX_FILES_PER_BATCH: int = 20

    # ── Phase 2: Google OAuth ──────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"

    # ── Phase 2: Deepgram — STT (Nova-3) + TTS (Aura) ─────────────────────
    DEEPGRAM_API_KEY: str = ""
    DEEPGRAM_STT_MODEL: str = "nova-3"
    DEEPGRAM_TTS_MODEL: str = "aura-2"
    DEEPGRAM_TTS_VOICE: str = "aura-asteria-en"

    # ── Phase 2: Groq — Vision (Llama 4 Scout) + batch audio (Whisper) ────
    GROQ_API_KEY: str = ""
    GROQ_STT_MODEL: str = "whisper-large-v3-turbo"
    GROQ_VISION_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    # ── Phase 2: Web Crawl ─────────────────────────────────────────────────
    PLAYWRIGHT_HEADLESS: bool = True
    CRAWL_MAX_DEPTH: int = 1
    CRAWL_MAX_PAGES_PER_URL: int = 50
    # Bulk / sitemap jobs (Phase 3)
    CRAWL_MAX_SEED_URLS: int = 25
    CRAWL_MAX_PAGES_TOTAL: int = 250
    CRAWL_SITEMAP_MAX_EXPAND: int = 400
    CRAWL_SITEMAP_MAX_FETCHES: int = 50
    CRAWL_REQUEST_DELAY_SEC: float = 0.2
    # When user pastes only a URL in chat, enqueue background crawl with these caps
    CRAWL_CHAT_MAX_PAGES_TOTAL: int = 120
    CRAWL_CHAT_MAX_DEPTH: int = 1
    CRAWL_CHAT_MAX_PAGES_PER_SEED: int = 80

    # ── Phase 2: Analytics Thresholds ─────────────────────────────────────
    DOCUMENT_FRESHNESS_THRESHOLD_DAYS: int = 90
    COVERAGE_GAP_CONFIDENCE_THRESHOLD: float = 0.5

    # ── Ingestion: PDF/image OCR + vision ────────────────────────────────
    # If PyMuPDF extracts fewer characters, run Unstructured/Tesseract OCR on the PDF.
    INGEST_PDF_OCR_FALLBACK_THRESHOLD: int = 100
    # When True conditions below trigger, render PDF pages to bitmaps and run vision (Groq → fallback).
    INGEST_PDF_VISION_MAX_PAGES: int = 15
    # If native PyMuPDF text is at least this long and OCR fallback was not used, skip vision (digital PDF).
    INGEST_PDF_VISION_SKIP_IF_NATIVE_CHARS: int = 1000

    # ── Phase 3: Knowledge graph + Graph RAG (Neo4j) ───────────────────────
    # Leave NEO4J_URI empty to disable graph features (vector-only RAG).
    NEO4J_URI: str = ""
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""
    GRAPH_RAG_ENABLED: bool = False
    GRAPH_BUILD_ON_INGEST: bool = True
    GRAPH_EXTRACTION_MODEL: str = ""  # default: OPENAI_CHAT_MODEL
    GRAPH_MAX_CHUNKS_PER_DOC: int = 32
    GRAPH_MAX_ENTITIES_PER_CHUNK: int = 14
    GRAPH_MAX_RELATIONS_PER_CHUNK: int = 20
    GRAPH_TRAVERSAL_DEPTH: int = 2
    GRAPH_TRAVERSAL_REL_LIMIT: int = 80
    GRAPH_QUERY_ENTITY_LIMIT: int = 8

    # ── Phase 3: Video ingestion (ffmpeg + STT + sampled frames) ───────────
    VIDEO_FRAME_SAMPLE_INTERVAL_SEC: float = 25.0
    VIDEO_MAX_SAMPLE_FRAMES: int = 48
    VIDEO_PROBE_TIMEOUT_SEC: int = 120
    VIDEO_FFMPEG_TIMEOUT_SEC: int = 900

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def neo4j_configured(self) -> bool:
        """Neo4j URI and password present (container or desktop)."""
        return bool(self.NEO4J_URI.strip() and self.NEO4J_PASSWORD.strip())

    @property
    def graph_rag_active(self) -> bool:
        """True when Graph RAG query path should run."""
        if not self.GRAPH_RAG_ENABLED:
            return False
        return self.neo4j_configured

    @property
    def graph_extraction_model(self) -> str:
        m = (self.GRAPH_EXTRACTION_MODEL or "").strip()
        return m if m else self.OPENAI_CHAT_MODEL

    @property
    def frontend_public_url(self) -> str:
        if self.FRONTEND_PUBLIC_URL and self.FRONTEND_PUBLIC_URL.strip():
            return self.FRONTEND_PUBLIC_URL.strip().rstrip("/")
        origins = self.cors_origins_list
        return origins[0].rstrip("/") if origins else "http://localhost:3000"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
