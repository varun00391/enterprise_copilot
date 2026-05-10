import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.database import engine, Base
from app.api import auth, documents, chat, analytics, admin, voice, health

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)

limiter = Limiter(key_func=get_remote_address, default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"])

app = FastAPI(
    title="OrgMind API",
    description="Enterprise Departmental Knowledge Platform",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    _ensure_nltk_unstructured_corpora()
    Base.metadata.create_all(bind=engine)
    _seed_default_departments()
    _seed_admin_user()


def _ensure_nltk_unstructured_corpora() -> None:
    """Unstructured image/pdf paths need NLTK; NLTK 3.8.2+ expects averaged_perceptron_tagger_eng
    (legacy averaged_perceptron_tagger alone does not satisfy pos_tag). Download into a writable dir.
    """
    import nltk
    from pathlib import Path

    try:
        nltk.data.find("taggers/averaged_perceptron_tagger_eng")
        return
    except LookupError:
        pass

    dest = Path.home() / "nltk_data"
    dest.mkdir(parents=True, exist_ok=True)
    nltk.download("averaged_perceptron_tagger_eng", download_dir=str(dest), quiet=True)


def _seed_default_departments():
    from sqlalchemy.orm import sessionmaker
    from app.models.models import Department
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        default_depts = [
            ("Human Resources", "hr"),
            ("Finance", "finance"),
            ("Legal", "legal"),
            ("Engineering", "engineering"),
        ]
        for name, slug in default_depts:
            if not db.query(Department).filter(Department.slug == slug).first():
                db.add(Department(name=name, slug=slug))
        db.commit()
    finally:
        db.close()


def _seed_admin_user():
    from sqlalchemy.orm import sessionmaker
    from app.models.models import User
    from app.core.security import hash_password
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        if not db.query(User).filter(User.role == "super_admin").first():
            admin = User(
                name="Admin",
                email="admin@gmail.com",
                password_hash=hash_password("admin@123"),
                role="super_admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()


app.include_router(auth.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(voice.router, prefix="/api")
app.include_router(health.router, prefix="/api")


@app.get("/")
def root():
    return {"message": "OrgMind API v1.0.0", "docs": "/api/docs"}
