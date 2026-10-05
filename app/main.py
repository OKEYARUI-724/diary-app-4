import json
import os
import re
import shutil
import time
import traceback
import uuid
from datetime import date, datetime
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
from geoalchemy2.shape import from_shape, to_shape
from jose import jwt
from pydantic import BaseModel
from shapely.geometry import Point
from sqlalchemy import and_, desc, func, or_, text
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
    """Resolve the JWT subject with exact, case-insensitive username matching."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None

    secret_key = getattr(auth_module, "SECRET_KEY", None) or os.getenv("SECRET_KEY", "")
    algorithm = getattr(auth_module, "ALGORITHM", None) or os.getenv("JWT_ALGORITHM", "HS256")
    if not secret_key:
        return None

    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        username = payload.get("sub")
        if not username:
            return None
        return find_user_by_username_exact_ci(db, username)
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
    except Exception as exc:
        print(f"[DB Migration Note] {exc}")


for i in range(10):
    try:
        migrate_social_features()
        Base.metadata.create_all(bind=engine)
        print("Database connected successfully!")
        break
    except Exception as exc:
        print(f"Waiting for database... ({i + 1}/10): {exc}")
        time.sleep(2)


app = FastAPI(title="WITHLOG API")

upload_dir = "static/uploads"
os.makedirs(upload_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_ui():
    return FileResponse("static/index.html")


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
def register(user_in: UserRegister, db: Session = Depends(get_db)):
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
    return TokenResponse(access_token=token, user=build_user_profile(user, user, db))


@app.post("/auth/login", response_model=TokenResponse)
def login(user_in: UserLogin, db: Session = Depends(get_db)):
    username = user_in.username.strip()
    user = find_user_by_username_exact_ci(db, username)
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="IDまたはパスワードが正しくありません")

    token = create_access_token(data={"sub": user.username})
    return TokenResponse(access_token=token, user=build_user_profile(user, user, db))


@app.get("/auth/me", response_model=UserProfile)
def get_me(current_user: User = Depends(require_current_user), db: Session = Depends(get_db)):
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
    current_user.is_private = payload.is_private
    db.commit()
    return {"status": "ok", "is_private": bool(current_user.is_private)}


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

    if avatar and avatar.filename:
        ext = os.path.splitext(avatar.filename)[1].lower()
        avatar_name = f"avatar_{current_user.id}_{uuid.uuid4()}{ext}"
        path = os.path.join(upload_dir, avatar_name)
        with open(path, "wb") as buf:
            shutil.copyfileobj(avatar.file, buf)
        current_user.avatar_url = f"/static/uploads/{avatar_name}"

    if cover and cover.filename:
        ext = os.path.splitext(cover.filename)[1].lower()
        cover_name = f"cover_{current_user.id}_{uuid.uuid4()}{ext}"
        path = os.path.join(upload_dir, cover_name)
        with open(path, "wb") as buf:
            shutil.copyfileobj(cover.file, buf)
        current_user.cover_url = f"/static/uploads/{cover_name}"

    db.commit()
    db.refresh(current_user)
    return build_user_profile(current_user, current_user, db)


# --- Following / private accounts / friend requests ---

@app.post("/users/{username}/follow")
def toggle_follow(
    username: str,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    clean = username.strip()
    target_user = find_user_by_username_exact_ci(db, clean)
    if not target_user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="自分自身はフォローできません")

    existing = db.query(Follow).filter(
        Follow.follower_id == current_user.id,
        Follow.following_id == target_user.id,
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        return {"following": False, "follow_status": "none"}

    relation_status = "pending" if target_user.is_private else "accepted"
    new_follow = Follow(
        follower_id=current_user.id,
        following_id=target_user.id,
        status=relation_status,
    )
    db.add(new_follow)

    if relation_status == "pending":
        add_notification(
            db,
            target_user.id,
            current_user.id,
            "follow_request",
            f"@{current_user.username} さんからフォロー申請が届きました！",
        )
    else:
        add_notification(
            db,
            target_user.id,
            current_user.id,
            "follow",
            f"@{current_user.username} さんにフォローされました！",
        )

    db.commit()
    return {
        "following": relation_status == "accepted",
        "follow_status": "pending" if relation_status == "pending" else "following",
    }


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
def handle_follow_decision(
    payload: FollowDecision,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    clean = payload.target_username.strip()
    sender = find_user_by_username_exact_ci(db, clean)
    if not sender:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    relation = db.query(Follow).filter(
        Follow.follower_id == sender.id,
        Follow.following_id == current_user.id,
        Follow.status == "pending",
    ).first()
    if not relation:
        raise HTTPException(status_code=404, detail="対象のフォロー申請がありません")

    action = payload.action.strip().lower()
    if action == "accept":
        relation.status = "accepted"
        add_notification(
            db,
            sender.id,
            current_user.id,
            "follow_accepted",
            f"@{current_user.username} さんへのフォロー申請が承認されました！",
        )
        db.commit()
        return {"status": "accepted"}

    if action in {"decline", "reject"}:
        db.delete(relation)
        db.commit()
        return {"status": "declined"}

    raise HTTPException(status_code=400, detail="action は accept または decline を指定してください")


@app.get("/api/users/{user_id}/followers")
def get_followers(user_id: str, db: Session = Depends(get_db)):
    clean = user_id.strip()
    try:
        target = db.query(User).filter(User.id == uuid.UUID(clean)).first()
    except ValueError:
        target = find_user_by_username_exact_ci(db, clean)
    if not target:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

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
def get_following(user_id: str, db: Session = Depends(get_db)):
    clean = user_id.strip()
    try:
        target = db.query(User).filter(User.id == uuid.UUID(clean)).first()
    except ValueError:
        target = find_user_by_username_exact_ci(db, clean)
    if not target:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

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
            Spot.user_id == user.id
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

@app.get("/media/{spot_id}")
def serve_spot_media(
    spot_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    media = db.query(SpotMedia).filter(SpotMedia.spot_id == spot_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    return Response(
        content=bytes(media.data),
        media_type=media.content_type or "application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- Spots & likes ---

@app.post("/spots/upload", response_model=SpotResponse)
async def create_spot(
    name: str = Form(...),
    latitude: Optional[float] = Form(37.5665),
    longitude: Optional[float] = Form(126.9780),
    memo: Optional[str] = Form(None),
    visited_at: Optional[datetime] = Form(None),
    rating: Optional[int] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: Optional[User] = Depends(get_current_user),
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

    google_url = f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
    point = Point(longitude, latitude)
    wkb_geom = from_shape(point, srid=4326)

    spot = Spot(
        user_id=current_user.id if current_user else None,
        name=name,
        memo=memo,
        rating=rating,
        geom=wkb_geom,
        google_map_url=google_url,
        media_url=media_url,
        media_type=media_type,
        visited_at=visited_at or datetime.now(),
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

    if current_user:
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
                f"@{current_user.username} さんが新しい思い出「{spot.name}」を投稿しました！",
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
        media_url=spot.media_url,
        media_type=spot.media_type,
        google_map_url=spot.google_map_url,
        latitude=pt.y,
        longitude=pt.x,
        rating=spot.rating,
        visited_at=spot.visited_at,
        likes_count=0,
        is_liked=False,
    )


@app.get("/spots", response_model=List[SpotResponse])
def get_spots(
    target_date: Optional[date] = None,
    feed_type: str = "all",
    target_username: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Spot)

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
                media_url=spot.media_url,
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


@app.post("/spots/{spot_id}/like")
def toggle_like(
    spot_id: uuid.UUID,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    spot = db.query(Spot).filter(Spot.id == spot_id).first()
    if not spot:
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
    return {"liked": is_liked, "likes_count": count}


@app.delete("/spots/{spot_id}")
def delete_spot(
    spot_id: uuid.UUID,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    spot = db.query(Spot).filter(Spot.id == spot_id).first()
    if not spot:
        raise HTTPException(status_code=404, detail="Spot not found")
    if spot.user_id and current_user and spot.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="他人の投稿は削除できません")

    # Legacy compatibility: remove an old local upload if it still exists.
    # New uploads live in spot_media and are deleted automatically by ON DELETE CASCADE.
    if spot.media_url and spot.media_url.startswith("/static/uploads/"):
        local_path = spot.media_url.lstrip("/")
        if os.path.exists(local_path):
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
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, username: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[username.lower()] = websocket

    def disconnect(self, username: str):
        self.active_connections.pop(username.lower(), None)

    async def send_personal_message(self, message: dict, recipient_username: str):
        websocket = self.active_connections.get(recipient_username.lower())
        if websocket:
            await websocket.send_text(json.dumps(message, ensure_ascii=False))


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
def delete_message(
    message_id: uuid.UUID,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    msg = db.query(DirectMessage).filter(DirectMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="メッセージが見つかりません")
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="自分の送信メッセージのみ削除できます")

    db.delete(msg)
    db.commit()
    return {"status": "deleted", "id": str(message_id)}


@app.websocket("/ws/dm")
async def websocket_dm_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    try:
        secret_key = getattr(auth_module, "SECRET_KEY", None) or os.getenv("SECRET_KEY", "")
        algorithm = getattr(auth_module, "ALGORITHM", None) or os.getenv("JWT_ALGORITHM", "HS256")
        if not secret_key:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        username = payload.get("sub")
        if not username:
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
        manager.disconnect(user.username)
    except Exception:
        manager.disconnect(user.username)


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
