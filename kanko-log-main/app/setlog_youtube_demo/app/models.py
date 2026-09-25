from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    youtube_video_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    music_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    music_artist: Mapped[str | None] = mapped_column(String(255), nullable=True)
    music_cover_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    music_external_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
