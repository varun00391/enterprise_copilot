"""
Integration test: Upload PDF → query → assert answer contains citation.

This test suite covers the core Phase 1 value proposition end-to-end.

Requirements
------------
Run with:
    pytest backend/tests/test_integration.py -v

The test uses an in-memory SQLite database for the relational store and
mocks Qdrant, MinIO, and the OpenAI API so no external services are needed.
"""
import io
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ─── bootstrap test DB ──────────────────────────────────────────────────────

TEST_DB_URL = "sqlite:///./test_orgmind.db"

# Patch settings BEFORE importing the app so all modules pick up the override.
import app.core.config as _cfg
_cfg.settings.DATABASE_URL = TEST_DB_URL
_cfg.settings.OPENAI_API_KEY = "test-key"
_cfg.settings.QDRANT_URL = "http://localhost:6333"
_cfg.settings.MINIO_ENDPOINT = "localhost:9000"

from app.core.database import Base
from app.core.security import hash_password

engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


# ─── app + dependency overrides ─────────────────────────────────────────────

from main import app
from app.core.database import get_db

app.dependency_overrides[get_db] = override_get_db


# ─── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_db():
    """Recreate all tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def seeded_db():
    """Insert a department + regular user + admin directly."""
    from app.models.models import Department, User
    db = TestingSession()
    dept = Department(id=uuid.uuid4(), name="Engineering", slug="engineering")
    db.add(dept)
    db.flush()

    user = User(
        id=uuid.uuid4(),
        name="Test User",
        email="test@example.com",
        password_hash=hash_password("password123"),
        role="user",
        dept_id=dept.id,
        is_active=True,
    )
    admin = User(
        id=uuid.uuid4(),
        name="Admin",
        email="admin@example.com",
        password_hash=hash_password("adminpass123"),
        role="super_admin",
        is_active=True,
    )
    db.add_all([user, admin])
    db.commit()
    db.close()
    return {"dept_id": str(dept.id), "user_email": "test@example.com", "user_password": "password123"}


# ─── helper ─────────────────────────────────────────────────────────────────

def get_token(client, email, password):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# ─── Auth tests ──────────────────────────────────────────────────────────────

class TestAuth:
    def test_register_and_login(self, client):
        """Register a new user then login successfully."""
        # seed a department first
        from app.models.models import Department
        db = TestingSession()
        dept = Department(id=uuid.uuid4(), name="HR", slug="hr")
        db.add(dept)
        db.commit()
        dept_id = str(dept.id)
        db.close()

        resp = client.post("/api/auth/register", json={
            "name": "Alice",
            "email": "alice@example.com",
            "password": "securepass",
            "dept_id": dept_id,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "alice@example.com"
        assert data["role"] == "user"

        resp = client.post("/api/auth/login", json={"email": "alice@example.com", "password": "securepass"})
        assert resp.status_code == 200
        tokens = resp.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens

    def test_duplicate_email_rejected(self, client, seeded_db):
        resp = client.post("/api/auth/register", json={
            "name": "Dup",
            "email": seeded_db["user_email"],
            "password": "password123",
        })
        assert resp.status_code == 409

    def test_invalid_login(self, client, seeded_db):
        resp = client.post("/api/auth/login", json={"email": seeded_db["user_email"], "password": "wrong"})
        assert resp.status_code == 401

    def test_get_me(self, client, seeded_db):
        token = get_token(client, seeded_db["user_email"], seeded_db["user_password"])
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["email"] == seeded_db["user_email"]

    def test_update_me_name(self, client, seeded_db):
        token = get_token(client, seeded_db["user_email"], seeded_db["user_password"])
        resp = client.patch("/api/auth/me", json={"name": "Updated Name"},
                            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    def test_refresh_token(self, client, seeded_db):
        resp = client.post("/api/auth/login", json={"email": seeded_db["user_email"], "password": seeded_db["user_password"]})
        refresh = resp.json()["refresh_token"]
        resp2 = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert resp2.status_code == 200
        assert "access_token" in resp2.json()


# ─── Health test ─────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_endpoint(self, client):
        with patch("app.api.health.QdrantClient") as mock_qdrant, \
             patch("app.api.health.get_minio_client") as mock_minio, \
             patch("redis.from_url") as mock_redis:
            mock_qdrant.return_value.get_collections.return_value = MagicMock(collections=[])
            mock_minio.return_value.bucket_exists.return_value = True
            mock_redis.return_value.ping.return_value = True

            resp = client.get("/api/health")
            assert resp.status_code == 200
            body = resp.json()
            assert "status" in body
            assert "services" in body


# ─── Department tests ─────────────────────────────────────────────────────────

class TestDepartments:
    def test_public_list_departments(self, client, seeded_db):
        resp = client.get("/api/auth/departments")
        assert resp.status_code == 200
        depts = resp.json()
        assert any(d["slug"] == "engineering" for d in depts)


# ─── Upload → Ingest → Query integration ─────────────────────────────────────

class TestUploadQueryCitation:
    """
    Core Phase 1 integration test:
      1. Upload a minimal PDF (created in-memory with a known text snippet).
      2. Mock the ingestion pipeline to index one chunk containing that text.
      3. Mock the retrieval pipeline to return that chunk.
      4. Mock the LLM to return a cited answer referencing [Source 1].
      5. Assert the streamed response contains a citation marker.
    """

    KNOWN_TEXT = "The parental leave policy grants 12 weeks of fully paid leave."

    def _minimal_pdf_bytes(self) -> bytes:
        """Create the smallest valid PDF with our known text."""
        content = f"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length {len(self.KNOWN_TEXT) + 20}>>
stream
BT /F1 12 Tf 72 720 Td ({self.KNOWN_TEXT}) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000{len(self.KNOWN_TEXT) + 320:06d} 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
{len(self.KNOWN_TEXT) + 380}
%%EOF"""
        return content.encode()

    def test_upload_pdf_and_query_with_citation(self, client, seeded_db):
        token = get_token(client, seeded_db["user_email"], seeded_db["user_password"])
        headers = {"Authorization": f"Bearer {token}"}
        dept_id = seeded_db["dept_id"]

        # ── 1. Upload PDF ────────────────────────────────────────────────────
        with patch("app.api.documents.upload_file") as mock_upload, \
             patch("app.api.documents.ingest_document") as mock_ingest, \
             patch("app.api.documents.delete_document_vectors"):
            mock_upload.return_value = f"{dept_id}/test/policy.pdf"
            mock_ingest.return_value = 1  # one chunk indexed

            files = {"files": ("policy.pdf", self._minimal_pdf_bytes(), "application/pdf")}
            resp = client.post("/api/documents/upload", files=files, headers=headers)

            assert resp.status_code == 200, resp.text
            docs = resp.json()
            assert len(docs) == 1
            doc = docs[0]
            assert doc["file_type"] == "pdf"
            assert doc["original_name"] == "policy.pdf"

        # ── 2. Check document status endpoint ───────────────────────────────
        doc_id = doc["id"]
        status_resp = client.get(f"/api/documents/{doc_id}/status", headers=headers)
        assert status_resp.status_code == 200

        # ── 3. Query the knowledge base ─────────────────────────────────────
        mock_chunk = {
            "id": str(uuid.uuid4()),
            "score": 0.92,
            "content": self.KNOWN_TEXT,
            "doc_id": doc_id,
            "doc_name": "policy.pdf",
            "chunk_index": 0,
            "file_type": "pdf",
            "page": 1,
        }
        cited_answer = f"According to the HR policy [Source 1], {self.KNOWN_TEXT}"

        with patch("app.agents.retrieval.hybrid_search", return_value=[mock_chunk]), \
             patch("app.agents.reasoning.OpenAI") as mock_openai:

            # Wire OpenAI streaming mock
            mock_chunk_obj = MagicMock()
            mock_chunk_obj.choices = [MagicMock(delta=MagicMock(content=None))]

            final_chunk = MagicMock()
            final_chunk.choices = [MagicMock(
                delta=MagicMock(content=f"<answer>{cited_answer}</answer><confidence>0.92</confidence>")
            )]

            mock_openai.return_value.chat.completions.create.return_value = iter([final_chunk])

            resp = client.post(
                "/api/chat/query",
                json={"query": "What is the parental leave policy?"},
                headers=headers,
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        # ── 4. Parse SSE and assert citation is present ──────────────────────
        raw = resp.text
        events = [line[6:] for line in raw.splitlines() if line.startswith("data: ") and line[6:] != "[DONE]"]

        token_events = []
        metadata_event = None
        for ev in events:
            try:
                obj = json.loads(ev)
                if obj.get("type") == "token":
                    token_events.append(obj["content"])
                elif obj.get("type") == "metadata":
                    metadata_event = obj
            except json.JSONDecodeError:
                pass

        assert token_events, "No token events received in SSE stream"
        full_response = "".join(token_events)

        # Citation marker must be present
        assert "[Source 1]" in full_response or "[Source 1]" in (metadata_event or {}).get("answer", ""), \
            f"Citation '[Source 1]' not found in response: {full_response!r}"

        # Confidence score must be present
        assert metadata_event is not None, "No metadata event in SSE stream"
        assert metadata_event.get("confidence", 0) > 0, "Confidence score missing or zero"

        # Sources list must reference the uploaded PDF
        sources = metadata_event.get("sources", [])
        assert any(s.get("doc_name") == "policy.pdf" for s in sources), \
            f"policy.pdf not found in sources: {sources}"

    def test_duplicate_upload_rejected(self, client, seeded_db):
        """Uploading the same file twice returns 409."""
        token = get_token(client, seeded_db["user_email"], seeded_db["user_password"])
        headers = {"Authorization": f"Bearer {token}"}
        pdf = self._minimal_pdf_bytes()

        with patch("app.api.documents.upload_file"), \
             patch("app.api.documents.ingest_document", return_value=1), \
             patch("app.api.documents.delete_document_vectors"):
            client.post("/api/documents/upload",
                        files={"files": ("dup.pdf", pdf, "application/pdf")},
                        headers=headers)
            resp2 = client.post("/api/documents/upload",
                                files={"files": ("dup.pdf", pdf, "application/pdf")},
                                headers=headers)
        assert resp2.status_code == 409

    def test_chat_feedback(self, client, seeded_db):
        """Submit thumbs-up feedback on a chat message."""
        from app.models.models import ChatSession, ChatMessage
        db = TestingSession()
        user_id = db.execute(
            __import__("sqlalchemy").text("SELECT id FROM users WHERE email=:e"),
            {"e": seeded_db["user_email"]},
        ).scalar()
        dept_id = uuid.UUID(seeded_db["dept_id"])
        session = ChatSession(id=uuid.uuid4(), user_id=user_id, dept_id=dept_id)
        db.add(session)
        db.flush()
        msg = ChatMessage(id=uuid.uuid4(), session_id=session.id, role="assistant",
                          content="Test answer", confidence=0.9)
        db.add(msg)
        db.commit()
        msg_id = str(msg.id)
        db.close()

        token = get_token(client, seeded_db["user_email"], seeded_db["user_password"])
        resp = client.post("/api/chat/feedback",
                           json={"message_id": msg_id, "rating": "up"},
                           headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 201


# ─── Analytics tests ──────────────────────────────────────────────────────────

class TestAnalytics:
    def test_dashboard_metrics(self, client, seeded_db):
        token = get_token(client, seeded_db["user_email"], seeded_db["user_password"])
        resp = client.get("/api/analytics/dashboard", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert "total_documents" in body
        assert "questions_today" in body
        assert "avg_confidence" in body

    def test_recent_activity_empty(self, client, seeded_db):
        token = get_token(client, seeded_db["user_email"], seeded_db["user_password"])
        resp = client.get("/api/analytics/recent-activity", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ─── Admin tests ──────────────────────────────────────────────────────────────

class TestAdmin:
    def test_list_users_requires_super_admin(self, client, seeded_db):
        token = get_token(client, seeded_db["user_email"], seeded_db["user_password"])
        resp = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_admin_can_list_users(self, client, seeded_db):
        token = get_token(client, "admin@example.com", "adminpass123")
        resp = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_audit_log_accessible_by_super_admin(self, client, seeded_db):
        token = get_token(client, "admin@example.com", "adminpass123")
        resp = client.get("/api/admin/audit-log", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
