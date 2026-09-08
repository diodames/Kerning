"""FastAPI app: auth, profile, digest, static reader."""

import hashlib
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app import config
from app.db import get_db, init_db
from app.jobs import enqueue
from app.mail import send_magic_link
from app.models import Job, MagicLink, Profile, Session as DbSession, User, UserDigest

ROOT = Path(__file__).resolve().parent.parent
COOKIE = "kerning_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STATIC_OK = {
    "/index.html", "/digest.json", "/digest.md", "/accounts.txt",
    "/bsky-accounts.txt", "/substack.txt", "/favicon.svg", "/favicon.png",
    "/favicon.ico", "/apple-touch-icon.png", "/og-image.png", "/llms.txt",
}
_HITS = defaultdict(deque)


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utcnow():
    return datetime.now(timezone.utc)


def _as_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _rate_ok(key, n, window_s):
    now = time.time()
    q = _HITS[key]
    while q and q[0] < now - window_s:
        q.popleft()
    if len(q) >= n:
        return False
    q.append(now)
    return True


class StaticWhitelist(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if request.method == "GET" and path in STATIC_OK:
            target = ROOT / path.lstrip("/")
            if target.is_file():
                return FileResponse(target)
        return await call_next(request)


app = FastAPI(title="Kerning", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(StaticWhitelist)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.APP_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)


@app.on_event("startup")
def _startup():
    init_db()


class EmailIn(BaseModel):
    email: str
    timezone: str = ""


class MeIn(BaseModel):
    timezone: str = ""


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise HTTPException(401, "sign in")
    rec = db.get(DbSession, _hash(raw))
    if not rec or _as_utc(rec.expires) < _utcnow():
        raise HTTPException(401, "sign in")
    user = db.get(User, rec.user_id)
    if not user:
        raise HTTPException(401, "sign in")
    return user


def _set_session_cookie(response, token):
    secure = config.APP_ORIGIN.startswith("https://")
    response.set_cookie(
        COOKIE, token, httponly=True, samesite="lax", secure=secure,
        max_age=config.SESSION_DAYS * 86400, path="/",
    )


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/auth/request")
def auth_request(body: EmailIn, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if not _rate_ok("auth-ip:" + ip, 8, 3600):
        raise HTTPException(429, "too many sign-in requests. try again later.")
    email = (body.email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "enter a valid email address.")
    if not _rate_ok("auth-email:" + email, 4, 3600):
        raise HTTPException(429, "too many sign-in requests. try again later.")
    token = secrets.token_urlsafe(32)
    db.add(MagicLink(
        token_hash=_hash(token),
        email=email,
        expires=_utcnow() + timedelta(minutes=config.MAGIC_MINUTES),
    ))
    db.commit()
    origin = config.APP_ORIGIN or str(request.base_url).rstrip("/")
    url = origin + "/auth/callback?token=" + token
    if body.timezone:
        url += "&tz=" + body.timezone
    mode = send_magic_link(email, url)
    out = {"ok": True, "delivered": mode}
    if mode == "logged" and config.is_dev_origin(origin):
        out["devLink"] = url
    return out


@app.get("/auth/callback")
def auth_callback(token: str, db: Session = Depends(get_db), tz: str = ""):
    rec = db.get(MagicLink, _hash(token or ""))
    if not rec or _as_utc(rec.expires) < _utcnow():
        return RedirectResponse(config.APP_ORIGIN + "/?expired=1", status_code=302)
    email = rec.email
    db.delete(rec)
    user = db.query(User).filter(User.email == email).one_or_none()
    first = user is None
    if first:
        user = User(email=email, timezone=tz or config.DEFAULT_TZ)
        db.add(user)
        db.flush()
        db.add(Profile(user_id=user.id, data={}))
        enqueue(db, "crawl")
        enqueue(db, "cut", user.id, delay_seconds=2, force=True)
    elif tz:
        user.timezone = tz
    session_token = secrets.token_urlsafe(32)
    db.add(DbSession(
        token_hash=_hash(session_token),
        user_id=user.id,
        expires=_utcnow() + timedelta(days=config.SESSION_DAYS),
    ))
    db.commit()
    res = RedirectResponse(config.APP_ORIGIN + "/", status_code=302)
    _set_session_cookie(res, session_token)
    return res


@app.post("/auth/logout")
def auth_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(COOKIE)
    if raw:
        rec = db.get(DbSession, _hash(raw))
        if rec:
            db.delete(rec)
            db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "timezone": user.timezone}


@app.put("/me")
def me_update(body: MeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.timezone:
        user.timezone = body.timezone
        db.commit()
    return {"id": user.id, "email": user.email, "timezone": user.timezone}


@app.get("/me/profile")
def get_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = db.get(Profile, user.id)
    return rec.data if rec else {"weights": {}, "ratings": {}, "saved": [], "seeds": {}}


@app.put("/me/profile")
def put_profile(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = db.get(Profile, user.id)
    data = {
        "weights": body.get("weights") or {},
        "ratings": body.get("ratings") or {},
        "saved": body.get("saved") or [],
        "seeds": body.get("seeds") or {},
    }
    if rec:
        rec.data = data
        rec.updated_at = _utcnow()
    else:
        rec = Profile(user_id=user.id, data=data)
        db.add(rec)
    enqueue(db, "cut", user.id, delay_seconds=15 * 60, force=True)
    db.commit()
    return {"ok": True}


@app.get("/me/digest")
def get_digest(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = db.get(UserDigest, user.id)
    if not rec:
        raise HTTPException(404, "digest not ready")
    return {"generated_at": rec.generated_at, "cadences": rec.cadences}


@app.post("/me/rebuild")
def rebuild(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not _rate_ok("rebuild:" + user.id, 6, 3600):
        raise HTTPException(429, "too many rebuilds. try again later.")
    crawl = enqueue(db, "crawl", force_soon=True)
    job = enqueue(db, "cut", user.id, force_soon=True, force=True)
    return {"jobId": job.id, "status": job.status, "crawlId": crawl.id}


@app.get("/me/jobs/{job_id}")
def job_status(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = db.get(Job, job_id)
    if not rec or (rec.user_id and rec.user_id != user.id):
        raise HTTPException(404, "job not found")
    return {"id": rec.id, "kind": rec.kind, "status": rec.status, "error": rec.error}


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")
