import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user,
)
from app.models.models import User, Department, AuditLog
from app.schemas.schemas import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshRequest, UserOut, DepartmentOut, UpdateMeRequest
)

router = APIRouter(prefix="/auth", tags=["auth"])

# ─── Google OAuth 2.0 ─────────────────────────────────────────────────────────
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _google_oauth_finish_html(access_token: str, refresh_token: str, frontend_base: str) -> HTMLResponse:
    """Send the browser to the SPA with tokens in the URL hash.

    When ``GOOGLE_REDIRECT_URI`` points at the API (e.g. :8000), this page runs on the **API origin**.
    ``localStorage`` is per-origin, so writing tokens here would not be visible on :3000. The SPA
    route ``/auth/google/callback`` reads the hash and stores JWTs on the frontend origin.
    """
    base = frontend_base.rstrip("/")
    fragment = urlencode({"access_token": access_token, "refresh_token": refresh_token})
    base_js = json.dumps(base)
    frag_js = json.dumps(fragment)
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="robots" content="noindex"/><title>Signing in…</title></head>
<body>
<p style="font-family:sans-serif">Redirecting…</p>
<script>
(function(){{
  var base = {base_js};
  var frag = {frag_js};
  window.location.replace(base + "/auth/google/callback#" + frag);
}})();
</script>
</body></html>"""
    return HTMLResponse(content=page)


@router.get("/google")
def google_login():
    """Redirect the browser to Google's OAuth 2.0 consent screen."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth is not configured")
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    qs = urlencode(params)
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{qs}")


@router.get("/google/oauth-setup")
def google_oauth_setup():
    """
    Shows the exact redirect URI sent to Google. If sign-in fails with redirect_uri_mismatch,
    register **redirect_uri** verbatim in Google Cloud Console → Credentials → OAuth client →
    Authorized redirect URIs (Web application type).
    """
    if not settings.GOOGLE_CLIENT_ID:
        return {
            "configured": False,
            "message": "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in environment / .env",
        }
    uri = settings.GOOGLE_REDIRECT_URI.strip()
    return {
        "configured": True,
        "redirect_uri": uri,
        "frontend_public_url": settings.frontend_public_url,
        "google_console_steps": [
            "https://console.cloud.google.com/apis/credentials",
            "Open OAuth 2.0 Client ID (type: Web application)",
            'Authorized redirect URIs → Add URI → paste redirect_uri exactly (no trailing slash unless it is part of yours)',
            "Save, wait ~1 minute, retry sign-in",
        ],
        "common_mismatches": [
            "localhost:3000 vs localhost:8000 (Docker SPA vs API-only)",
            "http vs https",
            "localhost vs 127.0.0.1",
            'Extra "/" at end of callback path',
        ],
    }


@router.get("/google/callback")
def google_callback(request: Request, db: Session = Depends(get_db)):
    """Exchange authorization code for Google user info; create or log in user."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth is not configured")

    q = request.query_params
    if q.get("error"):
        err_msg = (
            q.get("error_description")
            or q.get("error")
            or "Sign-in was canceled or failed."
        ).strip()
        qs = urlencode({"error": "oauth_failed", "message": err_msg[:240]})
        return RedirectResponse(url=f"{settings.frontend_public_url}/login?{qs}")

    code = q.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Exchange code → access token
    with httpx.Client(timeout=15) as client:
        token_resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to exchange code with Google")
    google_tokens = token_resp.json()
    g_access_token = google_tokens.get("access_token")

    # Fetch user info
    with httpx.Client(timeout=10) as client:
        info_resp = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {g_access_token}"},
        )
    if info_resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to fetch user info from Google")
    ginfo = info_resp.json()

    google_id = ginfo.get("sub")
    email = ginfo.get("email", "")
    name = ginfo.get("name", email.split("@")[0])

    if not google_id or not email:
        raise HTTPException(status_code=400, detail="Google did not return email/id")

    # Auto-provision or look up user
    user = db.query(User).filter(User.google_id == google_id).first()
    if not user:
        user = db.query(User).filter(User.email == email).first()
        if user:
            # Link existing account to Google
            user.google_id = google_id
            user.auth_provider = "google"
        else:
            # Auto-provision new user
            dept = _auto_assign_dept_by_email(email, db)
            user = User(
                name=name,
                email=email,
                password_hash=None,
                auth_provider="google",
                google_id=google_id,
                dept_id=dept.id if dept else None,
                role="user",
            )
            db.add(user)
    db.commit()
    db.refresh(user)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    # Issue same JWT tokens as regular login
    access_token = create_access_token(
        {"sub": str(user.id), "role": user.role, "dept_id": str(user.dept_id) if user.dept_id else None},
    )
    refresh_token = create_refresh_token(str(user.id))
    db.add(AuditLog(actor_id=user.id, actor_email=user.email, action="google_login", target_type="user", target_id=str(user.id)))
    db.commit()

    return _google_oauth_finish_html(access_token, refresh_token, settings.frontend_public_url)


def _auto_assign_dept_by_email(email: str, db: Session) -> Optional[Department]:
    """Map email domain to department (simple heuristic, configurable via naming convention)."""
    domain_map = {
        "eng": "Engineering",
        "hr": "HR",
        "finance": "Finance",
        "ops": "Operations",
        "sales": "Sales",
        "marketing": "Marketing",
    }
    if "@" in email:
        sub = email.split("@")[1].split(".")[0].lower()
        dept_name = domain_map.get(sub)
        if dept_name:
            return db.query(Department).filter(Department.name == dept_name).first()
    return None


@router.get("/departments", response_model=List[DepartmentOut])
def list_departments_public(db: Session = Depends(get_db)):
    """Public endpoint — returns departments for the registration form."""
    return db.query(Department).order_by(Department.name).all()


def _log_audit(db: Session, actor: User | None, action: str, target_type: str, target_id: str, request: Request = None):
    log = AuditLog(
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        ip_address=request.client.host if request else None,
    )
    db.add(log)
    db.commit()


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    dept = None
    if payload.dept_id:
        dept = db.query(Department).filter(Department.id == payload.dept_id).first()
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")

    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role="user",
        dept_id=payload.dept_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _log_audit(db, None, "user.register", "user", str(user.id), request)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    access_token = create_access_token({"sub": str(user.id), "role": user.role, "dept_id": str(user.dept_id) if user.dept_id else None})
    refresh_token = create_refresh_token(str(user.id))

    _log_audit(db, user, "user.login", "user", str(user.id), request)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(payload: RefreshRequest, db: Session = Depends(get_db)):
    token_data = decode_token(payload.refresh_token)
    if token_data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = token_data.get("sub")
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    access_token = create_access_token({"sub": str(user.id), "role": user.role, "dept_id": str(user.dept_id) if user.dept_id else None})
    new_refresh = create_refresh_token(str(user.id))
    return TokenResponse(access_token=access_token, refresh_token=new_refresh)


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: UpdateMeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changed = False
    if payload.name is not None:
        current_user.name = payload.name.strip()
        changed = True
    if payload.dept_id is not None:
        dept = db.query(Department).filter(Department.id == payload.dept_id).first()
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        current_user.dept_id = payload.dept_id
        changed = True
    if changed:
        db.commit()
        db.refresh(current_user)
    return current_user
