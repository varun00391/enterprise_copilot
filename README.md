# OrgMind — Multimodal RAG, Graph RAG & Analytics

> AI-powered departmental knowledge management on a multi-agent LangGraph architecture: hybrid and graph-augmented RAG, voice agent, analytics, rich document ingestion (including video), and optional Neo4j knowledge graph.

---

## Quick Start (Docker Compose)

From the repository root:

```bash
# Copy and edit environment (see Environment Variables below)
cp .env.example .env

docker compose up --build
```

| Service | URL / notes |
|---------|-------------|
| Frontend | http://localhost:3000 |
| API docs | http://localhost:8000/api/docs |
| MinIO console | http://localhost:9001 (`orgmind_minio` / `orgmind_minio_secret`) |
| Neo4j Browser | http://localhost:7474 (default compose user: `neo4j` / password: `orgmind_graph_secret`) |

Graph RAG is **off** until you set `GRAPH_RAG_ENABLED=true` and valid `NEO4J_URI` / `NEO4J_PASSWORD` in `.env` (Compose wires `bolt://neo4j:7687` and the password above).

---

## Local Development (without full stack in Docker)

### Backend

```bash
# From repository root — start infra only (adjust if you run services elsewhere)
docker compose up postgres qdrant redis minio neo4j -d

cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8000
```

Install **ffmpeg** on the host if you want video ingestion locally (the backend Docker image already includes it).

### Frontend

```bash
cd frontend
npm install
npm run dev
# http://localhost:5173 — Vite proxies /api → backend :8000
```

---

## Architecture

```
Frontend (React 18 + Vite + Tailwind + React Router)
    ↓ REST, SSE, multipart
FastAPI (Python 3.11)
    ↓
LangGraph-style pipeline
    ├── Ingestion Agent    (parse → chunk → embed → Qdrant; PDF OCR/vision; video frames+STT)
    ├── Graph extraction   (optional LLM → entities/relations → Neo4j when configured)
    ├── Retrieval          (hybrid_search OR graph_rag_retrieve when Graph RAG active)
    ├── Reasoning Agent    (chat model + CoT-style prompt; streamed answer)
    ├── Security Agent     (namespace isolation, query sanitization)
    ├── Multimodal         (vision+RAG fusion for chat image uploads)
    └── Voice pipeline     (STT → same RAG as chat → TTS)
    ↓
Storage: Qdrant · PostgreSQL · MinIO · Redis · Neo4j (optional)
```

### Provider routing (summary)

| Capability | Typical provider | Notes |
|------------|------------------|--------|
| Chat completions | **EuriAI** (or any OpenAI-compatible URL) | `OPENAI_BASE_URL` + `OPENAI_CHAT_MODEL` |
| Embeddings (ingest + search) | Same client as chat | `OPENAI_EMBEDDING_MODEL`; **use Euri’s full gateway path** (see env) |
| Voice STT | **Deepgram** → **Groq Whisper** fallback | Avoids chat-only gateways missing `/audio/transcriptions` |
| Voice TTS | **Deepgram Aura** | Falls back to OpenAI TTS only when `OPENAI_BASE_URL` is real `api.openai.com` |
| Vision (chat images, ingestion, PDF vision path) | **Groq** (Llama 4 Scout) → OpenAI-compatible vision fallback | `GROQ_VISION_MODEL` |
| Graph extraction (Neo4j) | Same OpenAI-compatible chat stack | `GRAPH_EXTRACTION_MODEL` or `OPENAI_CHAT_MODEL` |

Chat and voice **RAG** both use the same retrieval + reasoning stack (vector-only or graph-augmented when enabled), so they share your LLM/embedding quota on the configured gateway (e.g. EuriAI daily limits).

---

## Tech Stack

| Area | Technology |
|------|------------|
| Backend | Python 3.11, FastAPI, Uvicorn |
| Agents | LangChain 0.2 + LangGraph 0.1 |
| Frontend | React 18, Vite 5, Tailwind CSS 3 |
| Auth | JWT (python-jose), bcrypt |
| Vector DB | Qdrant |
| Knowledge graph | Neo4j 5 (optional Graph RAG) |
| Relational DB | PostgreSQL 15, SQLAlchemy, Alembic |
| Object storage | MinIO (S3-compatible) |
| Cache / rate limit | Redis |
| Voice | Deepgram SDK (STT + TTS), Groq (Whisper / vision) |
| Documents | PyMuPDF, python-docx, openpyxl, Unstructured.io, crawl4ai |
| Video | ffmpeg (container + local dev), sampled frames + transcript ingest |

---

## Features (current)

### Chat

- Full-page chat with sessions, streaming, sources sidebar, feedback, suggested follow-ups (second LLM call).
- **Images:** `POST /api/chat/query` accepts `multipart/form-data` with fields `query` and optional `image` (PNG/JPEG). When an image is present, the pipeline runs **`run_multimodal_stream`** (vision + RAG). JSON-only requests behave as text RAG.
- **URL-only messages:** a message that is *only* a `http(s)://` URL enqueues a background web crawl into the department knowledge base (caps via `CRAWL_CHAT_*` in `.env`) and streams an acknowledgement.

### Voice Agent (sidebar: **Voice Agent**)

- Dedicated route with conversation transcript + TTS playback.
- **Conversation mode:** Start once → microphone opens with voice-activity detection (end-of-utterance on silence) → pipeline runs → assistant audio plays (when TTS succeeds) → listening resumes automatically until you **End call**.
- HTTP: `POST /api/voice/transcribe` (multipart audio). Optional WebSocket: `/api/voice/stream`.

### Knowledge base & ingestion

- Upload pipeline: MinIO → background ingest → chunks → embeddings → Qdrant (per `dept_id`).
- **Images as documents (PNG/JPG/JPEG):** OCR via Unstructured; sparse text triggers optional vision description (Groq → OpenAI-compatible fallback) before embedding.
- **Video (Phase 3):** Common container formats (e.g. MP4, MOV, WebM, MKV, …) → ffmpeg-based pipeline: sampled frames + speech transcript; chunks are indexed like other documents.
- **Knowledge graph (optional):** When Neo4j is configured and `GRAPH_BUILD_ON_INGEST` is on, ingestion can extract entities/relations into Neo4j for Graph RAG.

### Other

- Google OAuth (optional), PPTX + audio formats, URL crawl (Playwright / crawl4ai), analytics dashboards, admin tooling.
- OpenAPI collection: `orgmind_postman_collection.json` (import into Postman or compatible clients).

---

## Environment Variables

Copy `.env.example` to `.env` and set real secrets. Highlights:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | **Yes** | API key for your OpenAI-compatible gateway (e.g. Euri) |
| `OPENAI_BASE_URL` | **Yes** for EuriAI | Must include the **full gateway path**, e.g. `https://api.euron.one/api/v1/euri` — *not* `.../api/v1` alone, or **embeddings** (`/embeddings`) will 404. |
| `OPENAI_CHAT_MODEL` | Yes | Chat model id on that gateway |
| `OPENAI_EMBEDDING_MODEL` | Yes | Embedding model id |
| `SECRET_KEY` | **Yes** | JWT signing secret (change in production) |
| `DEEPGRAM_API_KEY` | Recommended | Voice STT + TTS |
| `GROQ_API_KEY` | Recommended | STT fallback, vision helpers, audio batch ingest |
| `DATABASE_URL`, `QDRANT_URL`, `REDIS_URL`, `MINIO_*` | Usually from compose | See `docker-compose.yml` |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | For graph features | e.g. `bolt://localhost:7687` locally; `bolt://neo4j:7687` in Compose |
| `GRAPH_RAG_ENABLED` | Optional | `true` to use Neo4j-augmented retrieval (requires valid Neo4j config) |
| `GRAPH_BUILD_ON_INGEST`, `GRAPH_*` | Optional | Chunk limits, traversal depth, relation limits — see `.env.example` |
| `VIDEO_*` | Optional | Frame sampling and ffmpeg timeouts for video ingestion |

Database and infra defaults are wired for Docker Compose; adjust paths if you run services elsewhere.

---

## API Endpoints (high level)

Open **http://localhost:8000/api/docs** for the full OpenAPI spec.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register`, `/api/auth/login`, `/api/auth/refresh` | Auth |
| GET | `/api/auth/me` | Current user |
| POST | `/api/documents/upload` | Ingest files (including video when ffmpeg available) |
| GET | `/api/documents`, `/api/documents/{id}/status` | List / status |
| POST | `/api/chat/query` | SSE chat — JSON **or** multipart (`query`, optional `image`) |
| GET | `/api/chat/history`, `/api/chat/session/{id}/messages` | Sessions |
| POST | `/api/chat/feedback` | Thumbs |
| POST | `/api/voice/transcribe` | Audio → transcript + answer + optional `audio_url` |
| WS | `/api/voice/stream` | Optional streaming voice protocol |
| GET | `/api/analytics/*`, `/api/admin/*` | Analytics & admin (role-gated) |
| GET | `/api/health` | Health |

All app HTTP routes are under **`/api/...`** (not `/api/v1/...` on this server).

---

## User Roles

| Role | Access |
|------|--------|
| `user` | Chat, Voice Agent, upload, knowledge base, analytics (scoped) |
| `dept_admin` | Above + admin panel (dept) |
| `super_admin` | Users, audit log, full admin |

---

## Supported File Formats

**Core:** PDF, DOCX, TXT, XLSX/XLS, CSV, JSON, PNG, JPG/JPEG  

**Phase 2:** PPTX, MP3/WAV/M4A/OGG (transcription ingest), URL crawl (configured in `.env`).

**Phase 3:** Video — MP4, MOV, M4V, WebM, MKV, AVI, and other ffmpeg-supported containers listed in the backend allowlist (see `VIDEO_EXTENSIONS` in `app/api/documents.py`).

---

## Optional Setup

### Neo4j & Graph RAG

1. With Docker Compose, Neo4j starts automatically; set `NEO4J_URI=bolt://neo4j:7687`, `NEO4J_USER=neo4j`, `NEO4J_PASSWORD` to match compose (default password in compose: `orgmind_graph_secret`).
2. Set `GRAPH_RAG_ENABLED=true` after confirming connectivity.
3. Re-ingest or run extraction as your workflow requires so the graph is populated (`GRAPH_BUILD_ON_INGEST`).

### Google OAuth

1. [Google Cloud Console](https://console.cloud.google.com) → Credentials → **OAuth 2.0 Client ID** with type **Web application** (not Desktop).
2. Under **Authorized redirect URIs**, add the URI **exactly** as your backend sends it:

   - **Docker with nginx SPA on port 3000** (compose default): `http://localhost:3000/api/auth/google/callback`  
     Set matching `GOOGLE_REDIRECT_URI` and `FRONTEND_PUBLIC_URL` in `.env`.
   - **Browser hits API only on 8000** (e.g. Vite proxies `/api` but OAuth callback goes to uvicorn): `http://localhost:8000/api/auth/google/callback`

   Google rejects `redirect_uri_mismatch` when this string differs by **scheme, host, port, path, or trailing slash**. `localhost` and `127.0.0.1` count as different.

3. Same value in `.env` as `GOOGLE_REDIRECT_URI=...` — must match Console **verbatim**.
4. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`.

After the API is running, open **`GET /api/auth/google/oauth-setup`** (e.g. [http://localhost:8000/api/auth/google/oauth-setup](http://localhost:8000/api/auth/google/oauth-setup)) — it echoes the **`redirect_uri`** you must whitelist.

### Deepgram

1. [console.deepgram.com](https://console.deepgram.com) → API key  
2. `DEEPGRAM_API_KEY=...`  
Optional: `DEEPGRAM_STT_MODEL`, `DEEPGRAM_TTS_VOICE`

### Groq

1. [console.groq.com](https://console.groq.com) → API key  
2. `GROQ_API_KEY=...` — used for Whisper fallback, vision, and related paths

Without Deepgram, STT/TTS degrade per code paths above; without Groq, more load may hit your chat gateway for fallbacks.

### Web crawl (Playwright)

```bash
pip install playwright && playwright install chromium
```

`PLAYWRIGHT_HEADLESS` and crawl limits are in `.env`.

### Migrations

```bash
cd backend && alembic upgrade head
```

---

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| `404` on `/embeddings` via gateway | Wrong `OPENAI_BASE_URL` — use provider’s full path (e.g. `.../api/v1/euri`). |
| `403` daily token / wallet | Gateway quota (e.g. Euri free tier); resets on provider schedule or add credits. |
| `404` on `/audio/speech` or `/audio/transcriptions` | Chat-only proxy URL; voice uses Deepgram/Groq + guarded OpenAI fallbacks in code. |
| Voice works but no sound file | TTS failed; answer text may still return with `audio_url: null`. |
| Graph RAG never triggers | `GRAPH_RAG_ENABLED=false`, missing `NEO4J_URI`/`NEO4J_PASSWORD`, or Neo4j not reachable. |
| Video upload fails or stalls | ffmpeg missing locally, or `VIDEO_FFMPEG_TIMEOUT_SEC` too low for large files. |

---

## Roadmap snapshot

- **Phase 1:** Auth, core formats, text chat, hybrid RAG, admin  
- **Phase 2:** Voice agent UI + pipeline, OAuth, extra formats & crawl, analytics, multimodal chat + ingestion  
- **Phase 3 (in progress / shipped):** Neo4j knowledge graph + Graph RAG, video ingestion, expanded crawl caps — deeper observability and product hardening  

---

## License / project

Internal / org-specific deployment — adjust `SECRET_KEY`, CORS, and provider keys before production.
