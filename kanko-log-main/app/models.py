import uuid
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False)       # @id
    display_name = Column(String(100), nullable=True)                # 表示名
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    bio = Column(Text, nullable=True)                                # 自己紹介
    avatar_url = Column(String(1024), nullable=True)                 # アイコン画像
    cover_url = Column(String(1024), nullable=True)                  # ヘッダー背景画像
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    spots = relationship("Spot", back_populates="author", cascade="all, delete-orphan")
    likes = relationship("SpotLike", back_populates="user", cascade="all, delete-orphan")

class Follow(Base):
    __tablename__ = "follows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    follower_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    following_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("follower_id", "following_id", name="unique_follow"),)

class Spot(Base):
    __tablename__ = "spots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    name = Column(String(200), nullable=False)
    memo = Column(Text, nullable=True)
    geom = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)
    google_map_url = Column(String(1024), nullable=True)
    media_url = Column(String(1024), nullable=True)
    media_type = Column(String(20), nullable=True)
    rating = Column(Integer, nullable=True)
    visited_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    author = relationship("User", back_populates="spots")
    likes = relationship("SpotLike", back_populates="spot", cascade="all, delete-orphan")

class SpotLike(Base):
    __tablename__ = "spot_likes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    spot_id = Column(UUID(as_uuid=True), ForeignKey("spots.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="likes")
    spot = relationship("Spot", back_populates="likes")
    __table_args__ = (UniqueConstraint("user_id", "spot_id", name="unique_spot_like"),)

class DirectMessage(Base):
    __tablename__ = "direct_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sender_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recipient_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())