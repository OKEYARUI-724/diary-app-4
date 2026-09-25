from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import Post
from .services.youtube import get_video, search_videos

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)

    # 以前のSpotifyデモと同じDBを使っている場合でも動くように、
    # YouTube用・音楽表示用の列が不足していれば追加します（PostgreSQL用）。
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE posts "
                    "ADD COLUMN IF NOT EXISTS youtube_video_id VARCHAR(32), "
                    "ADD COLUMN IF NOT EXISTS music_title VARCHAR(500), "
                    "ADD COLUMN IF NOT EXISTS music_artist VARCHAR(255), "
                    "ADD COLUMN IF NOT EXISTS music_cover_url VARCHAR(1000), "
                    "ADD COLUMN IF NOT EXISTS music_external_url VARCHAR(1000)"
                )
            )
    yield


app = FastAPI(title="Photo Diary + YouTube Music", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/music/search")
async def music_search(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=20),
):
    return {"items": await search_videos(q.strip(), limit)}


@app.get("/api/posts")
def list_posts(db: Session = Depends(get_db)):
    posts = db.query(Post).order_by(Post.id.desc()).all()
    return [serialize_post(post) for post in posts]


@app.post("/api/posts")
async def create_post(
    image: UploadFile = File(...),
    caption: str = Form(""),
    youtube_video_id: str | None = Form(None),
    db: Session = Depends(get_db),
):
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="画像ファイルを選択してください。")

    allowed_types = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    suffix = allowed_types.get(image.content_type)
    if not suffix:
        raise HTTPException(status_code=400, detail="JPEG / PNG / WebP / GIF の画像を選択してください。")

    # ブラウザから送られたタイトル等は信用せず、動画IDからサーバー側で再取得します。
    music = await get_video(youtube_video_id) if youtube_video_id else None

    contents = await image.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="画像は10MB以下にしてください。")

    filename = f"{uuid4().hex}{suffix}"
    destination = UPLOAD_DIR / filename
    destination.write_bytes(contents)

    post = Post(
        caption=caption.strip() or None,
        image_url=f"/static/uploads/{filename}",
        youtube_video_id=music["youtube_video_id"] if music else None,
        music_title=music["title"] if music else None,
        music_artist=music["artist"] if music else None,
        music_cover_url=music["cover_url"] if music else None,
        music_external_url=music["external_url"] if music else None,
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    return serialize_post(post)


def serialize_post(post: Post) -> dict:
    music = None
    if post.youtube_video_id and post.music_title:
        music = {
            "provider": "youtube",
            "youtube_video_id": post.youtube_video_id,
            "title": post.music_title,
            "artist": post.music_artist,
            "cover_url": post.music_cover_url,
            "external_url": post.music_external_url,
            "embed_url": f"https://www.youtube.com/embed/{post.youtube_video_id}",
        }

    return {
        "id": post.id,
        "caption": post.caption,
        "image_url": post.image_url,
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "music": music,
    }
