import json
import os
import mimetypes
import posixpath
from pathlib import Path
import re
import shutil
import time
import traceback
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from geoalchemy2.shape import from_shape, to_shape
from jose import jwt
from pydantic import BaseModel
from shapely.geometry import Point
from sqlalchemy import and_, bindparam, desc, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import DirectMessage, Follow, Notification, Spot, SpotLike, SpotMedia, User
from app.schemas import (
    DMCreate,
    DMResponse,
    SpotResponse,
    TokenResponse,
    UserLogin,
    UserProfile,
    UserRegister,
)
import app.auth as auth_module
from app.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    require_current_user,
    verify_password,
)


class PrivacyUpdate(BaseModel):
    is_private: bool


class FollowDecision(BaseModel):
    target_username: str
    action: str


class CommentCreate(BaseModel):
    content: str


class CommentCountsRequest(BaseModel):
    spot_ids: List[uuid.UUID]


class AccountDeleteRequest(BaseModel):
    password: str
    confirm_username: str


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def validate_new_username(raw_username: str) -> str:
    raw_username = raw_username or ""
    if re.search(r"\s", raw_username):
        raise HTTPException(
            status_code=400,
            detail='User IDにスペースは使用できません。スペースの代わりに「_」を使用してください。',
        )

    username = raw_username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="User IDを入力してください。")
    if len(username) > 50:
        raise HTTPException(status_code=400, detail="User IDは50文字以内で入力してください。")
    if not USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(
            status_code=400,
            detail='User IDに使用できるのは半角英数字と「_」のみです。',
        )
    return username

def find_user_by_username_exact_ci(db: Session, raw_username: str) -> Optional[User]:
    """Case-insensitive exact username lookup.

    Do not use ILIKE for login/profile lookups because SQL treats '_' as
    a single-character wildcard. For example, 'OKEYA_RUI' could otherwise
    match an older account named 'OKEYA RUI'.
    """
    username = (raw_username or "").strip()
    if not username:
        return None
    return db.query(User).filter(func.lower(User.username) == username.lower()).first()


def _current_user_from_request(request: Request, db: Session) -> Optional[User]:
    # Only Bearer tokens authenticate API requests. Media cookies cannot change data.
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header.split(" ", 1)[1].strip()
    if not token:
        return None
    key, algorithm = authentication_key()
    try:
        payload = jwt.decode(token, key, algorithms=[algorithm],
                             options={"require_exp": True, "require_sub": True})
        if payload.get("purpose") or payload.get("aud"):
            return None
        return find_user_by_username_exact_ci(db, payload.get("sub", ""))
    except Exception:
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    return _current_user_from_request(request, db)


def require_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _current_user_from_request(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="認証が必要です")
    return user



def migrate_social_features():
    """Add the friend's social columns/tables without deleting existing data."""
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS is_private BOOLEAN NOT NULL DEFAULT FALSE;
            """))
            conn.execute(text("""
                ALTER TABLE follows
                ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'accepted';
            """))
            conn.execute(text("""
                UPDATE follows SET status = 'accepted' WHERE status IS NULL;
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id UUID PRIMARY KEY,
                    recipient_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    sender_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    type VARCHAR(50) NOT NULL,
                    message VARCHAR(255) NOT NULL,
                    is_read BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_notifications_recipient_created
                ON notifications(recipient_id, created_at DESC);
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_follows_status
                ON follows(status);
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS spot_comments (
                    id UUID PRIMARY KEY,
                    spot_id UUID NOT NULL REFERENCES spots(id) ON DELETE CASCADE,
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    content VARCHAR(500) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_spot_comments_spot_created
                ON spot_comments(spot_id, created_at);
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_spot_comments_user
                ON spot_comments(user_id);
            """))
    except Exception as exc:
        print(f"[DB Migration Note] {exc}")


app = FastAPI(title="WITHLOG API")


def _background_db_setup():
    """Run DB maintenance without blocking Render from opening its web port."""
    for i in range(10):
        try:
            Base.metadata.create_all(bind=engine)
            migrate_social_features()
            print("Database connected successfully!", flush=True)
            return
        except Exception as exc:
            print(f"Waiting for database... ({i + 1}/10): {exc}", flush=True)
            time.sleep(2)


@app.on_event("startup")
def start_background_db_setup():
    threading.Thread(target=_background_db_setup, daemon=True).start()


# --- Privacy: all reads use the same ownership / accepted-follower policy. ---
MEDIA_COOKIE = "withlog_media_v1"
MEDIA_AUDIENCE = "withlog-media"
PRIVACY_VERSION = "privacy-v1"
NO_STORE = "private, no-store, max-age=0"
SAFE_MEDIA_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/avif",
    "video/mp4", "video/webm", "video/ogg", "video/quicktime",
}

def authentication_key():
    # The old auth module has a development fallback. Never trust that public key.
    key = getattr(auth_module, "SECRET_KEY", None) or os.getenv("SECRET_KEY", "")
    weak_keys = {
        "your-secret-travel-log-super-key-2026",
        "travel-log-production-secret-2026",
    }
    if not isinstance(key, str) or len(key.strip()) < 32 or key in weak_keys:
        raise HTTPException(
            status_code=503,
            detail="安全な認証のため、RenderのEnvironmentに32文字以上のランダムなSECRET_KEYを設定してください。",
        )
    return key, getattr(auth_module, "ALGORITHM", "HS256")

def can_view_user_posts(author: Optional[User], viewer: Optional[User], db: Session) -> bool:
    if author is None:
        return False
    if viewer and viewer.id == author.id:
        return True
    if author.is_private is False:
        return True
    if viewer is None:
        return False
    return db.query(Follow.id).filter(
        Follow.follower_id == viewer.id,
        Follow.following_id == author.id,
        Follow.status == "accepted",
    ).first() is not None

DAILY_WITH_RE = re.compile(r"\[\[WITH_DAILY:(\d{4}-\d{2}-\d{2}):[^\]]+\]\]")

def _daily_with_day_from_memo(memo: Optional[str]) -> Optional[str]:
    match = DAILY_WITH_RE.search(memo or "")
    return match.group(1) if match else None

def _viewer_has_daily_with_day(day_key: str, viewer: Optional[User], db: Session) -> bool:
    if not viewer or not day_key:
        return False
    marker_prefix = f"[[WITH_DAILY:{day_key}:"
    return db.query(Spot.id).filter(
        Spot.user_id == viewer.id,
        Spot.memo.isnot(None),
        Spot.memo.like(f"%{marker_prefix}%"),
        Spot.visited_at <= func.now(),
    ).first() is not None

def _daily_with_locked_for_viewer(spot: Spot, viewer: Optional[User], db: Session) -> bool:
    day_key = _daily_with_day_from_memo(spot.memo)
    if not day_key:
        return False
    if viewer and spot.user_id == viewer.id:
        return False
    return not _viewer_has_daily_with_day(day_key, viewer, db)

def _spot_is_published(spot: Spot) -> bool:
    """Return True once the post's publication time has arrived."""
    if not spot.visited_at:
        return True
    publish_at = spot.visited_at
    if publish_at.tzinfo is None:
        publish_at = publish_at.replace(tzinfo=timezone.utc)
    return publish_at <= datetime.now(timezone.utc)

def can_view_spot(spot: Optional[Spot], viewer: Optional[User], db: Session) -> bool:
    if spot is None:
        return False
    # A scheduled post stays private until its publication time. The author may
    # still access its media by direct authenticated URL while preparing it.
    if not _spot_is_published(spot):
        return bool(viewer and spot.user_id == viewer.id)
    # Keep historical guest posts public; new posts require normal profile access.
    if spot.user_id is not None and not can_view_user_posts(spot.author, viewer, db):
        return False
    # TODAY'S WITH is reveal-after-post: another user's media/comments/likes stay
    # inaccessible until the viewer has published their own TODAY'S WITH that day.
    if _daily_with_locked_for_viewer(spot, viewer, db):
        return False
    return True

def visible_spots_query(db: Session, viewer: Optional[User]):
    allowed = [Spot.user_id.is_(None), Spot.author.has(User.is_private.is_(False))]
    if viewer:
        accepted = db.query(Follow.id).filter(
            Follow.following_id == Spot.user_id,
            Follow.follower_id == viewer.id,
            Follow.status == "accepted",
        ).exists()
        allowed.extend([Spot.user_id == viewer.id, accepted])
    # visited_at doubles as the publication time. Future rows are scheduled
    # posts and must not appear in any feed until PostgreSQL's clock reaches it.
    return db.query(Spot).filter(or_(*allowed), Spot.visited_at <= func.now())

def protected_media_url(spot: Spot):
    # A versioned, access-checked URL also avoids earlier public image-cache entries.
    return f"/media/{spot.id}?v={PRIVACY_VERSION}" if spot.media_url else None

def _lock_user(db: Session, user_id):
    return db.query(User).filter(User.id == user_id).with_for_update().populate_existing().one()

def _clear_request_notifications(db: Session, owner_id, requester_id):
    db.query(Notification).filter(
        Notification.recipient_id == owner_id,
        Notification.sender_id == requester_id,
        Notification.type == "follow_request",
    ).delete(synchronize_session=False)

def set_media_cookie(response: Response, request: Request, user: User, access_token: str):
    key, algorithm = authentication_key()
    payload = jwt.decode(access_token, key, algorithms=[algorithm],
                         options={"require_exp": True, "require_sub": True})
    # Separate, read-only token. It is never accepted as an API Bearer token.
    now = int(time.time())
    expires = min(int(payload["exp"]), now + 8 * 3600)
    media_token = jwt.encode({
        "sub": str(user.id), "aud": MEDIA_AUDIENCE, "purpose": MEDIA_AUDIENCE,
        "iat": now, "exp": expires,
    }, key, algorithm=algorithm)
    response.set_cookie(
        MEDIA_COOKIE, media_token, max_age=max(1, expires-now), path="/",
        httponly=True, samesite="lax",
        secure=bool(os.getenv("RENDER")) or request.url.scheme == "https",
    )

def media_current_user(request: Request, db: Session) -> Optional[User]:
    if request.headers.get("Authorization"):
        return _current_user_from_request(request, db)
    token = request.cookies.get(MEDIA_COOKIE)
    if not token:
        return None
    key, algorithm = authentication_key()
    try:
        payload = jwt.decode(token, key, algorithms=[algorithm], audience=MEDIA_AUDIENCE,
                             options={"require_exp": True, "require_sub": True})
        if payload.get("purpose") != MEDIA_AUDIENCE:
            return None
        return db.query(User).filter(User.id == uuid.UUID(payload["sub"])).first()
    except Exception:
        return None

def safe_media_headers(content_type):
    headers = {
        "Cache-Control": NO_STORE, "Vary": "Cookie, Authorization",
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox",
    }
    if content_type not in SAFE_MEDIA_TYPES:
        headers["Content-Disposition"] = "attachment"
    return headers

def local_upload_path(media_url: str):
    # Resolve against a fixed directory; do not allow traversal or arbitrary files.
    prefix = "/static/uploads/"
    clean = "/" + (media_url or "").lstrip("/")
    if not clean.startswith(prefix) or "?" in clean or "#" in clean:
        return None
    base = Path(upload_dir).resolve()
    candidate = (base / clean[len(prefix):]).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None

def legacy_upload_response(path: str, scope):
    request = Request(scope)
    relative = posixpath.normpath(path.replace("\\", "/"))
    url = "/static/" + relative
    candidate = local_upload_path(url)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Media not found")
    with Session(engine) as db:
        viewer = media_current_user(request, db)
        matches = db.query(Spot).filter(Spot.media_url.in_([url, url.lstrip("/")])).all()
        if matches:
            if not all(can_view_spot(spot, viewer, db) for spot in matches):
                raise HTTPException(status_code=404, detail="Media not found")
        else:
            # Profile photos/covers are public. Unreferenced uploads are denied.
            is_profile = db.query(User.id).filter(or_(
                User.avatar_url == url, User.cover_url == url,
            )).first() is not None
            if not is_profile:
                raise HTTPException(status_code=404, detail="Media not found")
    ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
    return FileResponse(candidate, media_type=ctype if ctype in SAFE_MEDIA_TYPES else "application/octet-stream",
                        headers=safe_media_headers(ctype))

class ProtectedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        normalized = posixpath.normpath(path.replace("\\", "/"))
        if normalized == "uploads" or normalized.startswith("uploads/"):
            return await run_in_threadpool(legacy_upload_response, normalized, scope)
        return await super().get_response(path, scope)

@app.middleware("http")
async def privacy_response_headers(request: Request, call_next):
    response = await call_next(request)
    # Never share authenticated feed data, private images, or HTML between users.
    path = request.url.path
    if not path.startswith("/static/") or "/uploads/" in path or path.endswith(".html"):
        response.headers["Cache-Control"] = NO_STORE
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        values = {v.strip() for v in response.headers.get("Vary", "").split(",") if v.strip()}
        response.headers["Vary"] = ", ".join(sorted(values | {"Cookie", "Authorization"}))
    response.headers["X-Withlog-Privacy-Version"] = PRIVACY_VERSION
    return response

@app.post("/auth/media-session")
def refresh_media_session(request: Request, response: Response,
                          current_user: User = Depends(require_current_user)):
    set_media_cookie(response, request, current_user,
                     request.headers["Authorization"].split(" ", 1)[1].strip())
    return {"status": "ok"}

@app.post("/auth/logout")
def logout_media_session(response: Response):
    # Deletes only the host's read-only media cookie; does not accept it for API writes.
    response.delete_cookie(MEDIA_COOKIE, path="/", httponly=True, samesite="lax")
    return {"status": "ok"}


upload_dir = "static/uploads"
os.makedirs(upload_dir, exist_ok=True)
app.mount("/static", ProtectedStaticFiles(directory="static"), name="static")


@app.get("/")
def serve_ui():
    # Never store the main HTML in browser or intermediary caches.
    return FileResponse(
        "static/index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def accepted_follow_filter():
    return Follow.status == "accepted"


def build_user_profile(target_user: User, current_user: Optional[User], db: Session) -> UserProfile:
    followers_count = db.query(Follow).filter(
        Follow.following_id == target_user.id,
        accepted_follow_filter(),
    ).count()
    following_count = db.query(Follow).filter(
        Follow.follower_id == target_user.id,
        accepted_follow_filter(),
    ).count()

    is_following = False
    if current_user:
        is_following = db.query(Follow).filter(
            Follow.follower_id == current_user.id,
            Follow.following_id == target_user.id,
            accepted_follow_filter(),
        ).first() is not None

    return UserProfile(
        id=target_user.id,
        username=target_user.username,
        display_name=target_user.display_name or target_user.username,
        bio=target_user.bio,
        avatar_url=target_user.avatar_url,
        cover_url=target_user.cover_url,
        followers_count=followers_count,
        following_count=following_count,
        is_following=is_following,
    )


def build_extended_profile(target_user: User, current_user: Optional[User], db: Session) -> dict:
    followers_count = db.query(Follow).filter(
        Follow.following_id == target_user.id,
        accepted_follow_filter(),
    ).count()
    following_count = db.query(Follow).filter(
        Follow.follower_id == target_user.id,
        accepted_follow_filter(),
    ).count()

    follow_status = "none"
    if current_user and current_user.id != target_user.id:
        relation = db.query(Follow).filter(
            Follow.follower_id == current_user.id,
            Follow.following_id == target_user.id,
        ).first()
        if relation:
            follow_status = "following" if relation.status == "accepted" else "pending"

    return {
        "id": str(target_user.id),
        "username": target_user.username,
        "display_name": target_user.display_name or target_user.username,
        "bio": target_user.bio,
        "avatar_url": target_user.avatar_url,
        "cover_url": target_user.cover_url,
        "followers_count": followers_count,
        "following_count": following_count,
        "is_following": follow_status == "following",
        "follow_status": follow_status,
        "is_private": bool(target_user.is_private),
        "can_view_posts": can_view_user_posts(target_user, current_user, db),
    }


def add_notification(
    db: Session,
    recipient_id,
    sender_id,
    notification_type: str,
    message: str,
):
    if recipient_id == sender_id:
        return
    db.add(
        Notification(
            recipient_id=recipient_id,
            sender_id=sender_id,
            type=notification_type,
            message=message[:255],
        )
    )


# --- Authentication & profile ---

@app.post("/auth/register", response_model=TokenResponse)
def register(user_in: UserRegister, request: Request, response: Response, db: Session = Depends(get_db)):
    authentication_key()
    username = validate_new_username(user_in.username)

    # User ID is unique regardless of upper/lower case.
    existing_user = db.query(User).filter(func.lower(User.username) == username.lower()).first()
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="このUser IDはすでに使用されています。別のIDを入力してください。",
        )

    if db.query(User).filter(User.email == user_in.email).first():
        raise HTTPException(status_code=400, detail="このメールアドレスは既に使われています")

    user = User(
        username=username,
        display_name=(user_in.display_name or username).strip(),
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        is_private=False,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="このUser IDまたはメールアドレスはすでに使用されています。",
        )
    db.refresh(user)

    token = create_access_token(data={"sub": user.username})
    set_media_cookie(response, request, user, token)
    return TokenResponse(access_token=token, user=build_user_profile(user, user, db))


@app.post("/auth/login", response_model=TokenResponse)
def login(user_in: UserLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    authentication_key()
    username = user_in.username.strip()
    user = find_user_by_username_exact_ci(db, username)
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="IDまたはパスワードが正しくありません")

    token = create_access_token(data={"sub": user.username})
    set_media_cookie(response, request, user, token)
    return TokenResponse(access_token=token, user=build_user_profile(user, user, db))


@app.get("/auth/me", response_model=UserProfile)
def get_me(request: Request, response: Response,
           current_user: User = Depends(require_current_user), db: Session = Depends(get_db)):
    set_media_cookie(response, request, current_user,
                     request.headers["Authorization"].split(" ", 1)[1].strip())
    return build_user_profile(current_user, current_user, db)


@app.get("/users/search", response_model=List[UserProfile])
def search_users(
    q: str,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query_str = f"%{q.strip().lstrip('@')}%"
    users = db.query(User).filter(
        or_(User.username.ilike(query_str), User.display_name.ilike(query_str))
    ).limit(10).all()
    return [build_user_profile(u, current_user, db) for u in users]


@app.get("/users/privacy")
def get_privacy(current_user: User = Depends(require_current_user)):
    return {"is_private": bool(current_user.is_private)}


@app.post("/users/privacy")
def update_privacy(
    payload: PrivacyUpdate,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    owner = _lock_user(db, current_user.id)
    owner.is_private = payload.is_private
    approved = 0
    if not payload.is_private:
        # Public mode accepts pending requests; tell the owner in the confirmation UI.
        pending = db.query(Follow).filter(
            Follow.following_id == owner.id, Follow.status == "pending",
        ).with_for_update().all()
        for relation in pending:
            relation.status = "accepted"
            _clear_request_notifications(db, owner.id, relation.follower_id)
            add_notification(db, relation.follower_id, owner.id, "follow_accepted",
                             f"@{owner.username} さんのフォローが承認されました。")
        approved = len(pending)
    db.commit()
    return {"status": "ok", "is_private": bool(owner.is_private),
            "accepted_pending_count": approved}


@app.get("/users/{username}")
def get_user_profile(
    username: str,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clean = username.strip()
    user = find_user_by_username_exact_ci(db, clean)
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    return build_extended_profile(user, current_user, db)


PROFILE_IMAGE_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/avif",
}
PROFILE_IMAGE_MAX_BYTES = 10 * 1024 * 1024


def ensure_profile_media_table(db: Session):
    # Keep profile media in PostgreSQL so Render deploys/restarts cannot erase it.
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS user_profile_media (
            user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            avatar_content BYTEA,
            avatar_content_type VARCHAR(100),
            cover_content BYTEA,
            cover_content_type VARCHAR(100),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """))


async def read_profile_image(upload: UploadFile, label: str):
    content_type = (upload.content_type or "").lower().strip()
    if content_type not in PROFILE_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail=f"{label}はJPEG・PNG・WebP・GIF・AVIF画像を選択してください")
    data = await upload.read(PROFILE_IMAGE_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail=f"{label}の画像データが空です")
    if len(data) > PROFILE_IMAGE_MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"{label}は10MB以下の画像を選択してください")
    return data, content_type


@app.get("/profile-media/{username}/{kind}")
def get_profile_media(
    username: str,
    kind: str,
    db: Session = Depends(get_db),
):
    if kind not in {"avatar", "cover"}:
        raise HTTPException(status_code=404, detail="Profile image not found")

    user = find_user_by_username_exact_ci(db, username.strip())
    if not user:
        raise HTTPException(status_code=404, detail="Profile image not found")

    ensure_profile_media_table(db)
    if kind == "avatar":
        row = db.execute(text("""
            SELECT avatar_content AS content, avatar_content_type AS content_type
            FROM user_profile_media
            WHERE user_id = :user_id
        """), {"user_id": user.id}).mappings().first()
    else:
        row = db.execute(text("""
            SELECT cover_content AS content, cover_content_type AS content_type
            FROM user_profile_media
            WHERE user_id = :user_id
        """), {"user_id": user.id}).mappings().first()

    if not row or row["content"] is None:
        raise HTTPException(status_code=404, detail="Profile image not found")

    content_type = (row["content_type"] or "application/octet-stream").lower()
    if content_type not in PROFILE_IMAGE_TYPES:
        content_type = "application/octet-stream"
    return Response(
        content=bytes(row["content"]),
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/users/profile", response_model=UserProfile)
async def update_profile(
    display_name: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
    cover: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    if display_name is not None:
        current_user.display_name = display_name.strip()
    if bio is not None:
        current_user.bio = bio.strip()

    ensure_profile_media_table(db)
    version = str(int(time.time() * 1000))

    if avatar and avatar.filename:
        avatar_data, avatar_type = await read_profile_image(avatar, "アイコン")
        db.execute(text("""
            INSERT INTO user_profile_media (user_id, avatar_content, avatar_content_type, updated_at)
            VALUES (:user_id, :content, :content_type, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                avatar_content = EXCLUDED.avatar_content,
                avatar_content_type = EXCLUDED.avatar_content_type,
                updated_at = CURRENT_TIMESTAMP
        """), {
            "user_id": current_user.id,
            "content": avatar_data,
            "content_type": avatar_type,
        })
        current_user.avatar_url = f"/profile-media/{current_user.username}/avatar?v={version}"

    if cover and cover.filename:
        cover_data, cover_type = await read_profile_image(cover, "背景画像")
        db.execute(text("""
            INSERT INTO user_profile_media (user_id, cover_content, cover_content_type, updated_at)
            VALUES (:user_id, :content, :content_type, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                cover_content = EXCLUDED.cover_content,
                cover_content_type = EXCLUDED.cover_content_type,
                updated_at = CURRENT_TIMESTAMP
        """), {
            "user_id": current_user.id,
            "content": cover_data,
            "content_type": cover_type,
        })
        current_user.cover_url = f"/profile-media/{current_user.username}/cover?v={version}"

    db.commit()
    db.refresh(current_user)
    return build_user_profile(current_user, current_user, db)


@app.delete("/users/me/account")
def delete_my_account(
    payload: AccountDeleteRequest,
    response: Response,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Permanently delete the signed-in account and all account-owned data.

    Database records are removed through PostgreSQL foreign-key ON DELETE CASCADE
    rules (posts/media, comments, likes, follows, notifications and DMs). Legacy
    files stored under static/uploads are removed on a best-effort basis after the
    database commit.
    """
    password = payload.password or ""
    confirm_username = (payload.confirm_username or "").strip()
    if confirm_username != current_user.username:
        raise HTTPException(status_code=400, detail="確認用のユーザーIDが一致しません")
    if not verify_password(password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="パスワードが正しくありません")

    # Collect legacy local files before deleting their database references.
    local_files = set()
    for url in (current_user.avatar_url, current_user.cover_url):
        candidate = local_upload_path(url) if url else None
        if candidate is not None:
            local_files.add(candidate)

    # Current builds include the user UUID in profile filenames. Also sweep older
    # replaced avatars/covers for this account that may no longer be referenced.
    upload_base = Path(upload_dir).resolve()
    for pattern in (f"avatar_{current_user.id}_*", f"cover_{current_user.id}_*"):
        for candidate in upload_base.glob(pattern):
            if candidate.is_file():
                local_files.add(candidate.resolve())

    legacy_media_urls = db.query(Spot.media_url).filter(
        Spot.user_id == current_user.id,
        Spot.media_url.like("/static/uploads/%"),
    ).all()
    for (url,) in legacy_media_urls:
        candidate = local_upload_path(url) if url else None
        if candidate is not None:
            local_files.add(candidate)

    user_id = current_user.id
    try:
        # Use a direct DELETE so the database, not partial ORM relationships, is
        # the single source of truth for cascading deletion.
        result = db.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=404, detail="アカウントが見つかりません")
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="アカウントを削除できませんでした。時間をおいてもう一度お試しください")

    for path in local_files:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            # After the DB deletion, ProtectedStaticFiles no longer serves
            # unreferenced uploads, even if filesystem cleanup fails.
            pass

    response.delete_cookie(MEDIA_COOKIE, path="/", httponly=True, samesite="lax")
    return {"status": "deleted"}


# --- Following / private accounts / friend requests ---

@app.post("/users/{username}/follow")
def toggle_follow(username: str, current_user: User = Depends(require_current_user),
                  db: Session = Depends(get_db)):
    target = find_user_by_username_exact_ci(db, username)
    if not target:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="自分自身はフォローできません")
    target = _lock_user(db, target.id)
    existing = db.query(Follow).filter(
        Follow.follower_id == current_user.id, Follow.following_id == target.id,
    ).with_for_update().first()
    if existing:
        db.delete(existing)
        _clear_request_notifications(db, target.id, current_user.id)
        db.commit()
        return {"following": False, "follow_status": "none"}
    pending = bool(target.is_private)
    db.add(Follow(follower_id=current_user.id, following_id=target.id,
                  status="pending" if pending else "accepted"))
    _clear_request_notifications(db, target.id, current_user.id)
    add_notification(db, target.id, current_user.id,
                     "follow_request" if pending else "follow",
                     f"@{current_user.username} さんからフォロー申請が届きました。" if pending
                     else f"@{current_user.username} さんにフォローされました。")
    db.commit()
    return {"following": not pending, "follow_status": "pending" if pending else "following"}


@app.get("/friends/outgoing-requests")
def get_outgoing_requests(
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    reqs = db.query(Follow).filter(
        Follow.follower_id == current_user.id,
        Follow.status == "pending",
    ).all()
    ids = [r.following_id for r in reqs]
    users = db.query(User).filter(User.id.in_(ids)).all() if ids else []
    return [
        {
            "id": str(u.id),
            "username": u.username,
            "display_name": u.display_name or u.username,
            "avatar_url": u.avatar_url,
        }
        for u in users
    ]


@app.get("/friends/incoming-requests")
def get_incoming_requests(
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    reqs = db.query(Follow).filter(
        Follow.following_id == current_user.id,
        Follow.status == "pending",
    ).all()
    ids = [r.follower_id for r in reqs]
    users = db.query(User).filter(User.id.in_(ids)).all() if ids else []
    return [
        {
            "id": str(u.id),
            "username": u.username,
            "display_name": u.display_name or u.username,
            "avatar_url": u.avatar_url,
        }
        for u in users
    ]


@app.post("/friends/decision")
def handle_follow_decision(payload: FollowDecision,
                           current_user: User = Depends(require_current_user),
                           db: Session = Depends(get_db)):
    action = payload.action.strip().lower()
    if action not in {"accept", "decline", "reject"}:
        raise HTTPException(status_code=400, detail="action は accept または decline を指定してください")
    owner = _lock_user(db, current_user.id)
    sender = find_user_by_username_exact_ci(db, payload.target_username)
    if not sender:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    relation = db.query(Follow).filter(
        Follow.follower_id == sender.id, Follow.following_id == owner.id,
        Follow.status == "pending",
    ).with_for_update().first()
    if not relation:
        raise HTTPException(status_code=404, detail="対象のフォロー申請は取り消されたか、すでに処理されています")
    _clear_request_notifications(db, owner.id, sender.id)
    if action == "accept":
        relation.status = "accepted"
        add_notification(db, sender.id, owner.id, "follow_accepted",
                         f"@{owner.username} さんへのフォロー申請が承認されました。")
        result = "accepted"
    else:
        db.delete(relation)
        result = "declined"
    db.commit()
    return {"status": result}

@app.delete("/users/me/followers/{username}")
def remove_follower(username: str, current_user: User = Depends(require_current_user),
                    db: Session = Depends(get_db)):
    owner = _lock_user(db, current_user.id)
    follower = find_user_by_username_exact_ci(db, username)
    if not follower:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    relation = db.query(Follow).filter(
        Follow.following_id == owner.id, Follow.follower_id == follower.id,
    ).with_for_update().first()
    if relation:
        db.delete(relation)
        _clear_request_notifications(db, owner.id, follower.id)
    db.commit()
    return {"status": "removed"}


@app.get("/api/users/{user_id}/followers")
def get_followers(user_id: str, current_user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    clean = user_id.strip()
    try:
        target = db.query(User).filter(User.id == uuid.UUID(clean)).first()
    except ValueError:
        target = find_user_by_username_exact_ci(db, clean)
    if not target:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    if not can_view_user_posts(target, current_user, db):
        raise HTTPException(status_code=403, detail="非公開アカウントのため、承認されたフォロワーのみ閲覧できます")
    follows = db.query(Follow).filter(
        Follow.following_id == target.id,
        Follow.status == "accepted",
    ).all()
    ids = [f.follower_id for f in follows]
    users = db.query(User).filter(User.id.in_(ids)).all() if ids else []
    return [
        {
            "id": str(u.id),
            "username": u.username,
            "display_name": u.display_name or u.username,
            "avatar_url": u.avatar_url,
            "is_private": bool(u.is_private),
        }
        for u in users
    ]


@app.get("/api/users/{user_id}/following")
def get_following(user_id: str, current_user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    clean = user_id.strip()
    try:
        target = db.query(User).filter(User.id == uuid.UUID(clean)).first()
    except ValueError:
        target = find_user_by_username_exact_ci(db, clean)
    if not target:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    if not can_view_user_posts(target, current_user, db):
        raise HTTPException(status_code=403, detail="非公開アカウントのため、承認されたフォロワーのみ閲覧できます")
    follows = db.query(Follow).filter(
        Follow.follower_id == target.id,
        Follow.status == "accepted",
    ).all()
    ids = [f.following_id for f in follows]
    users = db.query(User).filter(User.id.in_(ids)).all() if ids else []
    return [
        {
            "id": str(u.id),
            "username": u.username,
            "display_name": u.display_name or u.username,
            "avatar_url": u.avatar_url,
            "is_private": bool(u.is_private),
        }
        for u in users
    ]


@app.get("/users/following/stories")
def get_following_stories(
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user:
        return []

    follows = db.query(Follow).filter(
        Follow.follower_id == current_user.id,
        Follow.status == "accepted",
    ).all()
    ids = [f.following_id for f in follows]
    if not ids:
        return []

    users = db.query(User).filter(User.id.in_(ids)).all()
    result = []
    for user in users:
        latest_spot = db.query(Spot).filter(
            Spot.user_id == user.id,
            Spot.visited_at <= func.now(),
        ).order_by(desc(Spot.visited_at)).first()
        result.append(
            {
                "id": str(user.id),
                "username": user.username,
                "display_name": user.display_name or user.username,
                "avatar_url": user.avatar_url,
                "has_recent_spot": latest_spot is not None,
            }
        )
    return result


# --- Persistent post media (PostgreSQL BYTEA) ---

@app.api_route("/media/{spot_id}", methods=["GET", "HEAD"])
def serve_spot_media(spot_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    viewer = media_current_user(request, db)
    spot = db.query(Spot).filter(Spot.id == spot_id).first()
    if not can_view_spot(spot, viewer, db):
        raise HTTPException(status_code=404, detail="Media not found")
    media = db.query(SpotMedia).filter(SpotMedia.spot_id == spot_id).first()
    if media is None:
        candidate = local_upload_path(spot.media_url)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Media not found")
        ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        return FileResponse(candidate,
                            media_type=ctype if ctype in SAFE_MEDIA_TYPES else "application/octet-stream",
                            headers=safe_media_headers(ctype))
    data = bytes(media.data)
    ctype = (media.content_type or "application/octet-stream").split(";", 1)[0].lower()
    headers = safe_media_headers(ctype)
    headers["Accept-Ranges"] = "bytes"
    start, end, response_status = 0, len(data) - 1, 200
    # Single byte ranges support seeking without bypassing the access check above.
    byte_range = request.headers.get("Range")
    if byte_range and request.method == "GET" and not request.headers.get("If-Range"):
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range)
        if not match or not any(match.groups()) or not data:
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{len(data)}"})
        left, right = match.groups()
        if left:
            start = int(left)
            end = min(int(right), len(data)-1) if right else len(data)-1
        else:
            length = int(right)
            if length == 0:
                return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{len(data)}"})
            start = max(0, len(data)-length)
        if start > end or start >= len(data):
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{len(data)}"})
        response_status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
    headers["Content-Length"] = str(max(0, end-start+1))
    return Response(content=b"" if request.method == "HEAD" else data[start:end+1],
                    status_code=response_status,
                    media_type=ctype if ctype in SAFE_MEDIA_TYPES else "application/octet-stream",
                    headers=headers)


# --- Spots & likes ---

@app.post("/spots/upload", response_model=SpotResponse)
async def create_spot(
    name: str = Form(""),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    memo: Optional[str] = Form(None),
    visited_at: Optional[datetime] = Form(None),
    rating: Optional[int] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    media_url = None
    media_type = None
    media_bytes = None
    media_filename = None
    media_content_type = None

    if file and file.filename:
        media_bytes = await file.read()
        if not media_bytes:
            raise HTTPException(status_code=400, detail="アップロードされたファイルが空です")
        media_filename = os.path.basename(file.filename)
        media_content_type = file.content_type or "application/octet-stream"
        media_type = "video" if media_content_type.startswith("video") else "image"

    # Location is optional. Keep a neutral geometry value for the existing DB schema,
    # but do not expose a map link unless the user selected a real location.
    has_location = latitude is not None and longitude is not None
    if has_location:
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise HTTPException(status_code=400, detail="緯度または経度が正しくありません")
        google_url = f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
        point = Point(longitude, latitude)
    else:
        google_url = None
        point = Point(0.0, 0.0)
    wkb_geom = from_shape(point, srid=4326)

    # The existing visited_at column is also the publication timestamp. This
    # keeps scheduled posting backward-compatible and avoids a risky DB migration.
    now_utc = datetime.now(timezone.utc)
    publish_at = visited_at or now_utc
    if publish_at.tzinfo is None:
        publish_at = publish_at.replace(tzinfo=timezone.utc)
    # Times within 30 seconds of now are treated as an immediate post.
    is_scheduled = publish_at > now_utc + timedelta(seconds=30)
    if not is_scheduled:
        publish_at = now_utc

    spot = Spot(
        user_id=current_user.id if current_user else None,
        name=(name or "").strip(),
        memo=memo,
        rating=rating,
        geom=wkb_geom,
        google_map_url=google_url,
        media_url=media_url,
        media_type=media_type,
        visited_at=publish_at,
    )
    db.add(spot)
    db.flush()

    if media_bytes is not None:
        db.add(
            SpotMedia(
                spot_id=spot.id,
                filename=media_filename,
                content_type=media_content_type,
                data=media_bytes,
            )
        )
        spot.media_url = f"/media/{spot.id}"

    if current_user and not is_scheduled:
        followers = db.query(Follow).filter(
            Follow.following_id == current_user.id,
            Follow.status == "accepted",
        ).all()
        for relation in followers:
            add_notification(
                db,
                relation.follower_id,
                current_user.id,
                "new_post",
                (f"@{current_user.username} さんが今日のWITHを投稿しました！"
                 if _daily_with_day_from_memo(spot.memo)
                 else f"@{current_user.username} さんが新しい思い出「{spot.name}」を投稿しました！"),
            )

    db.commit()
    db.refresh(spot)

    pt = to_shape(spot.geom)
    return SpotResponse(
        id=spot.id,
        user_id=spot.user_id,
        username=current_user.username if current_user else "guest",
        display_name=current_user.display_name if current_user else "Guest",
        author_avatar_url=current_user.avatar_url if current_user else None,
        name=spot.name,
        memo=spot.memo,
        media_url=protected_media_url(spot),
        media_type=spot.media_type,
        google_map_url=spot.google_map_url,
        latitude=pt.y,
        longitude=pt.x,
        rating=spot.rating,
        visited_at=spot.visited_at,
        likes_count=0,
        is_liked=False,
    )


@app.get("/spots")
def get_spots(
    target_date: Optional[date] = None,
    feed_type: str = "all",
    target_username: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = visible_spots_query(db, current_user)

    if feed_type == "following" and not current_user:
        raise HTTPException(status_code=401, detail="ログインが必要です")
    if feed_type == "following" and current_user:
        following_ids = db.query(Follow.following_id).filter(
            Follow.follower_id == current_user.id,
            Follow.status == "accepted",
        ).subquery()
        query = query.filter(Spot.user_id.in_(following_ids))
    elif feed_type == "user" and target_username:
        clean = target_username.strip()
        author = find_user_by_username_exact_ci(db, clean)
        if author:
            query = query.filter(Spot.user_id == author.id)
        else:
            return []

    if target_date:
        query = query.filter(func.date(Spot.visited_at) == target_date)

    records = query.order_by(Spot.visited_at.desc()).all()
    results = []

    for spot in records:
        daily_day = _daily_with_day_from_memo(spot.memo)
        if daily_day and _daily_with_locked_for_viewer(spot, current_user, db):
            # Return only enough metadata to render a blurred/locked placeholder.
            # Never send the photo, caption, song, title, map coordinates or counts.
            # Do not construct SpotResponse here. The normal post schema can be
            # stricter than this privacy placeholder (for example, map/media fields
            # may be required). Returning a small plain dict prevents one locked
            # TODAY'S WITH from making the entire /spots request fail validation.
            results.append({
                "id": str(spot.id),
                "user_id": str(spot.user_id) if spot.user_id else None,
                "username": spot.author.username if spot.author else "guest",
                "display_name": (spot.author.display_name or spot.author.username) if spot.author else "Guest",
                "author_avatar_url": spot.author.avatar_url if spot.author else None,
                "name": "今日のWITH",
                "memo": f"[[WITH_DAILY_LOCKED:{daily_day}]]",
                "visited_at": spot.visited_at.isoformat() if spot.visited_at else None,
                "likes_count": 0,
                "is_liked": False,
                "daily_with_locked": True,
                "daily_with_day": daily_day,
            })
            continue

        pt = to_shape(spot.geom)
        likes_count = db.query(SpotLike).filter(SpotLike.spot_id == spot.id).count()
        is_liked = False
        if current_user:
            is_liked = db.query(SpotLike).filter(
                SpotLike.spot_id == spot.id,
                SpotLike.user_id == current_user.id,
            ).first() is not None

        results.append(
            SpotResponse(
                id=spot.id,
                user_id=spot.user_id,
                username=spot.author.username if spot.author else "guest",
                display_name=spot.author.display_name or spot.author.username if spot.author else "Guest",
                author_avatar_url=spot.author.avatar_url if spot.author else None,
                name=spot.name,
                memo=spot.memo,
                media_url=protected_media_url(spot),
                media_type=spot.media_type,
                google_map_url=spot.google_map_url,
                latitude=pt.y,
                longitude=pt.x,
                rating=spot.rating,
                visited_at=spot.visited_at,
                likes_count=likes_count,
                is_liked=is_liked,
            )
        )
    return results


@app.get("/users/me/liked-spots", response_model=List[SpotResponse])
def get_my_liked_spots(
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Return posts liked by the signed-in user, newest like first."""
    liked_rows = (
        visible_spots_query(db, current_user)
        .join(SpotLike, SpotLike.spot_id == Spot.id)
        .filter(SpotLike.user_id == current_user.id)
        .order_by(SpotLike.created_at.desc())
        .all()
    )

    results = []
    for spot in liked_rows:
        # A previously-liked TODAY'S WITH must not become a back door around the
        # reveal-after-post rule. Hide it until this viewer posts that day's WITH.
        if _daily_with_locked_for_viewer(spot, current_user, db):
            continue

        # Do not expose a private account's post after access has been lost.
        if spot.author and spot.author.id != current_user.id and getattr(spot.author, "is_private", False):
            can_view = db.query(Follow).filter(
                Follow.follower_id == current_user.id,
                Follow.following_id == spot.author.id,
                Follow.status == "accepted",
            ).first() is not None
            if not can_view:
                continue

        pt = to_shape(spot.geom)
        likes_count = db.query(SpotLike).filter(SpotLike.spot_id == spot.id).count()
        results.append(
            SpotResponse(
                id=spot.id,
                user_id=spot.user_id,
                username=spot.author.username if spot.author else "guest",
                display_name=spot.author.display_name or spot.author.username if spot.author else "Guest",
                author_avatar_url=spot.author.avatar_url if spot.author else None,
                name=spot.name,
                memo=spot.memo,
                media_url=protected_media_url(spot),
                media_type=spot.media_type,
                google_map_url=spot.google_map_url,
                latitude=pt.y,
                longitude=pt.x,
                rating=spot.rating,
                visited_at=spot.visited_at,
                likes_count=likes_count,
                is_liked=True,
            )
        )

    return results


@app.post("/spots/{spot_id}/like")
async def toggle_like(
    spot_id: uuid.UUID,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    spot = db.query(Spot).filter(Spot.id == spot_id).first()
    if not can_view_spot(spot, current_user, db):
        raise HTTPException(status_code=404, detail="Spot not found")

    existing = db.query(SpotLike).filter(
        SpotLike.spot_id == spot_id,
        SpotLike.user_id == current_user.id,
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        is_liked = False
    else:
        db.add(SpotLike(user_id=current_user.id, spot_id=spot_id))
        db.commit()
        is_liked = True

    count = db.query(SpotLike).filter(SpotLike.spot_id == spot_id).count()

    # Reuse the authenticated WebSocket connection used by DM/comments so every
    # connected viewer of this post sees the like counter change immediately.
    await manager.send_spot_event(
        {
            "event": "like_changed",
            "spot_id": str(spot.id),
            "count": int(count),
            "actor_username": current_user.username,
            "liked": bool(is_liked),
        },
        spot,
        db,
    )

    return {"liked": is_liked, "likes_count": count}


@app.post("/comments/counts")
def get_comment_counts(
    payload: CommentCountsRequest,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # One request supplies all counters shown in the current feed. Visibility is
    # checked here as well so a private post count is never leaked.
    requested_ids = list(dict.fromkeys(payload.spot_ids))[:200]
    if not requested_ids:
        return {"counts": {}}

    visible_rows = visible_spots_query(db, current_user).filter(
        Spot.id.in_(requested_ids)
    ).with_entities(Spot.id).all()
    visible_ids = [row[0] for row in visible_rows]
    counts = {str(spot_id): 0 for spot_id in visible_ids}
    if not visible_ids:
        return {"counts": counts}

    stmt = text("""
        SELECT spot_id, COUNT(*) AS count
        FROM spot_comments
        WHERE spot_id IN :spot_ids
        GROUP BY spot_id
    """).bindparams(bindparam("spot_ids", expanding=True))
    rows = db.execute(stmt, {"spot_ids": visible_ids}).mappings().all()
    for row in rows:
        counts[str(row["spot_id"])] = int(row["count"] or 0)
    return {"counts": counts}


@app.get("/spots/{spot_id}/comments")
def get_spot_comments(
    spot_id: uuid.UUID,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    spot = db.query(Spot).filter(Spot.id == spot_id).first()
    if not can_view_spot(spot, current_user, db):
        raise HTTPException(status_code=404, detail="投稿が見つかりません")

    rows = db.execute(text("""
        SELECT
            c.id, c.content, c.created_at, c.user_id,
            u.username, COALESCE(u.display_name, u.username) AS display_name, u.avatar_url
        FROM spot_comments c
        JOIN users u ON u.id = c.user_id
        WHERE c.spot_id = :spot_id
        ORDER BY c.created_at ASC
        LIMIT 200
    """), {"spot_id": spot_id}).mappings().all()

    count = db.execute(text("""
        SELECT COUNT(*) AS count
        FROM spot_comments
        WHERE spot_id = :spot_id
    """), {"spot_id": spot_id}).scalar() or 0

    viewer_id = current_user.id if current_user else None
    comments = []
    for row in rows:
        comments.append({
            "id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "username": row["username"],
            "display_name": row["display_name"],
            "avatar_url": row["avatar_url"],
            "content": row["content"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "can_delete": bool(viewer_id and viewer_id == row["user_id"]),
        })

    return {"comments": comments, "count": int(count)}


@app.post("/spots/{spot_id}/comments")
async def create_spot_comment(
    spot_id: uuid.UUID,
    payload: CommentCreate,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    spot = db.query(Spot).filter(Spot.id == spot_id).first()
    if not can_view_spot(spot, current_user, db):
        raise HTTPException(status_code=404, detail="投稿が見つかりません")

    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="コメントを入力してください")
    if len(content) > 500:
        raise HTTPException(status_code=400, detail="コメントは500文字以内で入力してください")

    comment_id = uuid.uuid4()
    created_at = datetime.utcnow()
    db.execute(text("""
        INSERT INTO spot_comments (id, spot_id, user_id, content, created_at)
        VALUES (:id, :spot_id, :user_id, :content, :created_at)
    """), {
        "id": comment_id,
        "spot_id": spot.id,
        "user_id": current_user.id,
        "content": content,
        "created_at": created_at,
    })

    if spot.user_id and spot.user_id != current_user.id:
        preview = content.replace("\n", " ")[:80]
        add_notification(
            db,
            spot.user_id,
            current_user.id,
            "comment",
            f"@{current_user.username} さんが『{spot.name}』にコメントしました: {preview}",
        )

    db.commit()
    count = db.execute(
        text("SELECT COUNT(*) FROM spot_comments WHERE spot_id = :spot_id"),
        {"spot_id": spot.id},
    ).scalar() or 0

    # Push the new count immediately to every currently connected user who is
    # allowed to see this post. The browser uses this for the feed badge even
    # when the comment panel itself is closed.
    await manager.send_spot_event(
        {
            "event": "comment_created",
            "spot_id": str(spot.id),
            "comment_id": str(comment_id),
            "count": int(count),
        },
        spot,
        db,
    )

    return {
        "comment": {
            "id": str(comment_id),
            "user_id": str(current_user.id),
            "username": current_user.username,
            "display_name": current_user.display_name or current_user.username,
            "avatar_url": current_user.avatar_url,
            "content": content,
            "created_at": created_at.isoformat(),
            "can_delete": True,
        },
        "count": int(count),
    }


@app.delete("/comments/{comment_id}")
async def delete_spot_comment(
    comment_id: uuid.UUID,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    row = db.execute(text("""
        SELECT id, spot_id, user_id
        FROM spot_comments
        WHERE id = :comment_id
        FOR UPDATE
    """), {"comment_id": comment_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="コメントが見つかりません")

    spot = db.query(Spot).filter(Spot.id == row["spot_id"]).first()
    if not spot:
        raise HTTPException(status_code=404, detail="投稿が見つかりません")

    if current_user.id != row["user_id"]:
        raise HTTPException(status_code=403, detail="コメントした本人だけが削除できます")

    db.execute(text("DELETE FROM spot_comments WHERE id = :comment_id"), {"comment_id": comment_id})
    db.commit()
    count = db.execute(
        text("SELECT COUNT(*) FROM spot_comments WHERE spot_id = :spot_id"),
        {"spot_id": spot.id},
    ).scalar() or 0

    await manager.send_spot_event(
        {
            "event": "comment_deleted",
            "spot_id": str(spot.id),
            "comment_id": str(comment_id),
            "count": int(count),
        },
        spot,
        db,
    )

    return {"status": "deleted", "count": int(count)}


@app.delete("/spots/{spot_id}")
def delete_spot(
    spot_id: uuid.UUID,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    spot = db.query(Spot).filter(Spot.id == spot_id).first()
    if not spot:
        raise HTTPException(status_code=404, detail="Spot not found")
    if spot.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="他人の投稿は削除できません")

    # Legacy compatibility: remove an old local upload if it still exists.
    # New uploads live in spot_media and are deleted automatically by ON DELETE CASCADE.
    if spot.media_url and spot.media_url.startswith("/static/uploads/"):
        local_path = local_upload_path(spot.media_url)
        if local_path is not None:
            try:
                os.remove(local_path)
            except Exception:
                pass

    db.delete(spot)
    db.commit()
    return {"message": "deleted successfully"}


# --- Notifications ---

@app.get("/notifications")
def get_notifications(
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    notifications = db.query(Notification).filter(
        Notification.recipient_id == current_user.id
    ).order_by(desc(Notification.created_at)).limit(30).all()

    return [
        {
            "id": str(item.id),
            "type": item.type,
            "message": item.message,
            "is_read": item.is_read,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "sender_username": item.sender.username if item.sender else "someone",
            "sender_avatar_url": item.sender.avatar_url if item.sender else None,
        }
        for item in notifications
        if item.type != "new_post" or can_view_user_posts(item.sender, current_user, db)
    ]


@app.post("/notifications/read")
def mark_notifications_read(
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    db.query(Notification).filter(
        Notification.recipient_id == current_user.id,
        Notification.is_read.is_(False),
    ).update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"status": "ok"}


# --- Direct messages + WebSocket ---

class ConnectionManager:
    def __init__(self):
        # Keep every tab/device connected for the same account.
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, username: str, websocket: WebSocket):
        await websocket.accept()
        key = username.lower()
        bucket = self.active_connections.setdefault(key, [])
        if websocket not in bucket:
            bucket.append(websocket)

    def disconnect(self, username: str, websocket: Optional[WebSocket] = None):
        key = username.lower()
        if websocket is None:
            self.active_connections.pop(key, None)
            return
        bucket = self.active_connections.get(key, [])
        bucket = [item for item in bucket if item is not websocket]
        if bucket:
            self.active_connections[key] = bucket
        else:
            self.active_connections.pop(key, None)

    async def send_personal_message(self, message: dict, recipient_username: str):
        sockets = list(self.active_connections.get(recipient_username.lower(), []))
        if not sockets:
            return
        payload = json.dumps(message, ensure_ascii=False)
        stale = []
        for websocket in sockets:
            try:
                await websocket.send_text(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(recipient_username, websocket)

    async def send_spot_event(self, message: dict, spot: Spot, db: Session):
        """Send a realtime post event only to connected users who may view it."""
        connected_usernames = list(self.active_connections.keys())
        for username in connected_usernames:
            try:
                viewer = find_user_by_username_exact_ci(db, username)
                if viewer and can_view_spot(spot, viewer, db):
                    await self.send_personal_message(message, viewer.username)
            except Exception:
                # A stale websocket/user must never make comment creation fail.
                continue


manager = ConnectionManager()


@app.get("/messages/conversations", response_model=List[UserProfile])
def get_conversations(
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    user_ids = db.query(DirectMessage.recipient_id).filter(
        DirectMessage.sender_id == current_user.id
    ).union(
        db.query(DirectMessage.sender_id).filter(
            DirectMessage.recipient_id == current_user.id
        )
    ).all()
    unique_ids = [uid[0] for uid in user_ids]
    users = db.query(User).filter(User.id.in_(unique_ids)).all() if unique_ids else []
    return [build_user_profile(user, current_user, db) for user in users]


@app.get("/messages/{partner_username}", response_model=List[DMResponse])
def get_messages(
    partner_username: str,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    clean = partner_username.strip()
    partner = find_user_by_username_exact_ci(db, clean)
    if not partner:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    messages = db.query(DirectMessage).filter(
        or_(
            and_(DirectMessage.sender_id == current_user.id, DirectMessage.recipient_id == partner.id),
            and_(DirectMessage.sender_id == partner.id, DirectMessage.recipient_id == current_user.id),
        )
    ).order_by(DirectMessage.created_at.asc()).all()

    sender_cache = {current_user.id: current_user.username, partner.id: partner.username}
    return [
        DMResponse(
            id=message.id,
            sender_id=message.sender_id,
            sender_username=sender_cache.get(message.sender_id, "unknown"),
            recipient_id=message.recipient_id,
            content=message.content,
            created_at=message.created_at,
        )
        for message in messages
    ]


@app.post("/messages", response_model=DMResponse)
async def send_message(
    msg_in: DMCreate,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    clean = msg_in.recipient_username.strip()
    recipient = find_user_by_username_exact_ci(db, clean)
    if not recipient:
        raise HTTPException(status_code=404, detail="送信先のユーザーが見つかりません")

    msg = DirectMessage(
        sender_id=current_user.id,
        recipient_id=recipient.id,
        content=msg_in.content.strip(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    msg_data = {
        "event": "dm_created",
        "id": str(msg.id),
        "sender_username": current_user.username,
        "recipient_username": recipient.username,
        "content": msg.content,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }
    await manager.send_personal_message(msg_data, recipient.username)
    await manager.send_personal_message(msg_data, current_user.username)

    return DMResponse(
        id=msg.id,
        sender_id=msg.sender_id,
        sender_username=current_user.username,
        recipient_id=msg.recipient_id,
        content=msg.content,
        created_at=msg.created_at,
    )


@app.delete("/messages/{message_id}")
async def delete_message(
    message_id: uuid.UUID,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    msg = db.query(DirectMessage).filter(DirectMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="メッセージが見つかりません")
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="自分の送信メッセージのみ削除できます")

    recipient = db.query(User).filter(User.id == msg.recipient_id).first()
    recipient_username = recipient.username if recipient else None

    db.delete(msg)
    db.commit()

    event = {
        "event": "dm_deleted",
        "id": str(message_id),
        "sender_username": current_user.username,
        "recipient_username": recipient_username,
    }
    await manager.send_personal_message(event, current_user.username)
    if recipient_username:
        await manager.send_personal_message(event, recipient_username)
    return {"status": "deleted", "id": str(message_id)}


@app.websocket("/ws/dm")
async def websocket_dm_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    try:
        secret_key, algorithm = authentication_key()
        if not secret_key:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        payload = jwt.decode(token, secret_key, algorithms=[algorithm], options={"require_exp": True, "require_sub": True})
        username = payload.get("sub")
        if not username or payload.get("purpose") or payload.get("aud"):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        user = find_user_by_username_exact_ci(db, username)
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(user.username, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user.username, websocket)
    except Exception:
        manager.disconnect(user.username, websocket)


# --- YouTube music search ---

@app.get("/api/music/search")
async def youtube_music_search(q: str, limit: int = 10):
    import httpx

    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Enter a song or artist name.")

    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="YOUTUBE_API_KEY is not configured on the server.")

    safe_limit = max(1, min(int(limit or 10), 10))
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": safe_limit,
        "key": api_key,
        "regionCode": "JP",
        "relevanceLanguage": "ja",
        "safeSearch": "moderate",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params=params,
            )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not connect to YouTube API.")

    if response.status_code != 200:
        try:
            payload = response.json()
            message = payload.get("error", {}).get("message") or "YouTube search failed."
        except Exception:
            message = "YouTube search failed."
        raise HTTPException(status_code=response.status_code, detail=message)

    payload = response.json()
    items = []

    for item in payload.get("items", []):
        video_id = (item.get("id") or {}).get("videoId")
        snippet = item.get("snippet") or {}
        if not video_id:
            continue

        thumbnails = snippet.get("thumbnails") or {}
        cover_url = (
            (thumbnails.get("high") or {}).get("url")
            or (thumbnails.get("medium") or {}).get("url")
            or (thumbnails.get("default") or {}).get("url")
            or ""
        )

        items.append(
            {
                "youtube_video_id": video_id,
                "title": snippet.get("title") or "",
                "artist": snippet.get("channelTitle") or "",
                "cover_url": cover_url,
                "external_url": f"https://www.youtube.com/watch?v={video_id}",
                "embed_url": f"https://www.youtube.com/embed/{video_id}",
            }
        )

    return {"items": items}
