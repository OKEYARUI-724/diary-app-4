import os
import time
import uuid
import shutil
from datetime import date, datetime
from typing import List, Optional
from fastapi import FastAPI, Depends, UploadFile, File, Form, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point

from app.database import get_db, engine, Base
from app.models import Spot, User, SpotLike, Follow, DirectMessage
from app.schemas import (
    SpotResponse, UserRegister, UserLogin, UserProfile, TokenResponse, DMCreate, DMResponse
)
from app.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
    require_current_user
)

for i in range(10):
    try:
        Base.metadata.create_all(bind=engine)
        print("Database connected successfully!")
        break
    except Exception as e:
        print(f"Waiting for database... ({i+1}/10)")
        time.sleep(2)

app = FastAPI(title="Travel Log API")

upload_dir = "static/uploads"
os.makedirs(upload_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve_ui():
    return FileResponse("static/index.html")

def build_user_profile(target_user: User, current_user: Optional[User], db: Session) -> UserProfile:
    followers_count = db.query(Follow).filter(Follow.following_id == target_user.id).count()
    following_count = db.query(Follow).filter(Follow.follower_id == target_user.id).count()
    is_following = False
    if current_user:
        is_following = db.query(Follow).filter(
            Follow.follower_id == current_user.id,
            Follow.following_id == target_user.id
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
        is_following=is_following
    )

# --- 認証 & プロフィール ---

@app.post("/auth/register", response_model=TokenResponse)
def register(user_in: UserRegister, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user_in.username).first():
        raise HTTPException(status_code=400, detail="このIDは既に使われています")
    if db.query(User).filter(User.email == user_in.email).first():
        raise HTTPException(status_code=400, detail="このメールアドレスは既に使われています")

    user = User(
        username=user_in.username,
        display_name=user_in.display_name or user_in.username,
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password)
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(data={"sub": user.username})
    return TokenResponse(access_token=token, user=build_user_profile(user, user, db))

@app.post("/auth/login", response_model=TokenResponse)
def login(user_in: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == user_in.username).first()
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="IDまたはパスワードが正しくありません")

    token = create_access_token(data={"sub": user.username})
    return TokenResponse(access_token=token, user=build_user_profile(user, user, db))

@app.get("/auth/me", response_model=UserProfile)
def get_me(current_user: User = Depends(require_current_user), db: Session = Depends(get_db)):
    return build_user_profile(current_user, current_user, db)

# ユーザーID / 表示名 検索
@app.get("/users/search", response_model=List[UserProfile])
def search_users(q: str, current_user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    query_str = f"%{q.strip().lstrip('@')}%"
    users = db.query(User).filter(
        or_(
            User.username.ilike(query_str),
            User.display_name.ilike(query_str)
        )
    ).limit(10).all()

    return [build_user_profile(u, current_user, db) for u in users]

@app.get("/users/{username}", response_model=UserProfile)
def get_user_profile(username: str, current_user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    return build_user_profile(user, current_user, db)

@app.post("/users/profile", response_model=UserProfile)
async def update_profile(
    display_name: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
    cover: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db)
):
    if display_name is not None:
        current_user.display_name = display_name
    if bio is not None:
        current_user.bio = bio

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

# --- フォロー ---

@app.post("/users/{username}/follow")
def toggle_follow(username: str, current_user: User = Depends(require_current_user), db: Session = Depends(get_db)):
    target_user = db.query(User).filter(User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="自分自身はフォローできません")

    existing = db.query(Follow).filter(
        Follow.follower_id == current_user.id,
        Follow.following_id == target_user.id
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        return {"following": False}
    else:
        new_follow = Follow(follower_id=current_user.id, following_id=target_user.id)
        db.add(new_follow)
        db.commit()
        return {"following": True}

# --- スポット & いいね ---

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
    db: Session = Depends(get_db)
):
    media_url = None
    media_type = None

    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        file_id = f"{uuid.uuid4()}{ext}"
        save_path = os.path.join(upload_dir, file_id)
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        media_url = f"/static/uploads/{file_id}"
        media_type = "video" if file.content_type and file.content_type.startswith("video") else "image"

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
        visited_at=visited_at or datetime.now()
    )
    db.add(spot)
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
        is_liked=False
    )

@app.get("/spots", response_model=List[SpotResponse])
def get_spots(
    target_date: Optional[date] = None,
    feed_type: str = "all",
    target_username: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Spot)

    if feed_type == "following" and current_user:
        following_ids = db.query(Follow.following_id).filter(Follow.follower_id == current_user.id).subquery()
        query = query.filter(Spot.user_id.in_(following_ids))
    elif feed_type == "user" and target_username:
        author = db.query(User).filter(User.username == target_username).first()
        if author:
            query = query.filter(Spot.user_id == author.id)
        else:
            return []

    if target_date:
        query = query.filter(func.date(Spot.visited_at) == target_date)

    records = query.order_by(Spot.visited_at.desc()).all()
    results = []

    for s in records:
        pt = to_shape(s.geom)
        likes_count = db.query(SpotLike).filter(SpotLike.spot_id == s.id).count()
        is_liked = False
        if current_user:
            is_liked = db.query(SpotLike).filter(
                SpotLike.spot_id == s.id,
                SpotLike.user_id == current_user.id
            ).first() is not None

        results.append(
            SpotResponse(
                id=s.id,
                user_id=s.user_id,
                username=s.author.username if s.author else "guest",
                display_name=s.author.display_name or s.author.username if s.author else "Guest",
                author_avatar_url=s.author.avatar_url if s.author else None,
                name=s.name,
                memo=s.memo,
                media_url=s.media_url,
                media_type=s.media_type,
                google_map_url=s.google_map_url,
                latitude=pt.y,
                longitude=pt.x,
                rating=s.rating,
                visited_at=s.visited_at,
                likes_count=likes_count,
                is_liked=is_liked
            )
        )
    return results

@app.post("/spots/{spot_id}/like")
def toggle_like(spot_id: uuid.UUID, current_user: User = Depends(require_current_user), db: Session = Depends(get_db)):
    spot = db.query(Spot).filter(Spot.id == spot_id).first()
    if not spot:
        raise HTTPException(status_code=404, detail="Spot not found")

    existing = db.query(SpotLike).filter(
        SpotLike.spot_id == spot_id,
        SpotLike.user_id == current_user.id
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        is_liked = False
    else:
        new_like = SpotLike(user_id=current_user.id, spot_id=spot_id)
        db.add(new_like)
        db.commit()
        is_liked = True

    count = db.query(SpotLike).filter(SpotLike.spot_id == spot_id).count()
    return {"liked": is_liked, "likes_count": count}

@app.delete("/spots/{spot_id}")
def delete_spot(
    spot_id: uuid.UUID,
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    spot = db.query(Spot).filter(Spot.id == spot_id).first()
    if not spot:
        raise HTTPException(status_code=404, detail="Spot not found")
    if spot.user_id and current_user and spot.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="他人の投稿は削除できません")

    if spot.media_url:
        local_path = spot.media_url.lstrip("/")
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception:
                pass

    db.delete(spot)
    db.commit()
    return {"message": "deleted successfully"}

# --- DM（ダイレクトメッセージ） ---

# やり取りしたユーザー一覧を取得
@app.get("/messages/conversations", response_model=List[UserProfile])
def get_conversations(
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db)
):
    user_ids = db.query(DirectMessage.recipient_id).filter(DirectMessage.sender_id == current_user.id).union(
        db.query(DirectMessage.sender_id).filter(DirectMessage.recipient_id == current_user.id)
    ).all()
    unique_ids = [uid[0] for uid in user_ids]
    users = db.query(User).filter(User.id.in_(unique_ids)).all()
    return [build_user_profile(u, current_user, db) for u in users]

@app.get("/messages/{partner_username}", response_model=List[DMResponse])
def get_messages(
    partner_username: str,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db)
):
    partner = db.query(User).filter(User.username == partner_username).first()
    if not partner:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    messages = db.query(DirectMessage).filter(
        or_(
            and_(DirectMessage.sender_id == current_user.id, DirectMessage.recipient_id == partner.id),
            and_(DirectMessage.sender_id == partner.id, DirectMessage.recipient_id == current_user.id)
        )
    ).order_by(DirectMessage.created_at.asc()).all()

    sender_cache = {current_user.id: current_user.username, partner.id: partner.username}
    return [
        DMResponse(
            id=m.id,
            sender_id=m.sender_id,
            sender_username=sender_cache.get(m.sender_id, "unknown"),
            recipient_id=m.recipient_id,
            content=m.content,
            created_at=m.created_at
        ) for m in messages
    ]

@app.post("/messages", response_model=DMResponse)
def send_message(
    msg_in: DMCreate,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db)
):
    recipient = db.query(User).filter(User.username == msg_in.recipient_username).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="送信先のユーザーが見つかりません")

    msg = DirectMessage(
        sender_id=current_user.id,
        recipient_id=recipient.id,
        content=msg_in.content
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    return DMResponse(
        id=msg.id,
        sender_id=msg.sender_id,
        sender_username=current_user.username,
        recipient_id=msg.recipient_id,
        content=msg.content,
        created_at=msg.created_at
    )