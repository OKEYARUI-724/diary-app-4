from pydantic import BaseModel, ConfigDict, EmailStr
from uuid import UUID
from datetime import datetime
from typing import Optional, List

class UserRegister(BaseModel):
    username: str
    display_name: Optional[str] = None
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    username: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    followers_count: int = 0
    following_count: int = 0
    is_following: bool = False

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile

class SpotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: Optional[UUID] = None
    username: Optional[str] = None
    display_name: Optional[str] = None
    author_avatar_url: Optional[str] = None
    name: str
    memo: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    google_map_url: str
    latitude: float
    longitude: float
    rating: Optional[int] = None
    visited_at: datetime
    likes_count: int = 0
    is_liked: bool = False

class DMCreate(BaseModel):
    recipient_username: str
    content: str

class DMResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sender_id: UUID
    sender_username: str
    recipient_id: UUID
    content: str
    created_at: datetime