-- Render PostgreSQL initialization for Travel Log
-- Generated to match app/models.py
-- Run this once on the new Render database.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    bio TEXT,
    avatar_url VARCHAR(1024),
    cover_url VARCHAR(1024),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS follows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    follower_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    following_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_follow UNIQUE (follower_id, following_id)
);

CREATE TABLE IF NOT EXISTS spots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    memo TEXT,
    geom GEOMETRY(Point, 4326) NOT NULL,
    google_map_url VARCHAR(1024),
    media_url VARCHAR(1024),
    media_type VARCHAR(20),
    rating INTEGER,
    visited_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS spot_likes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    spot_id UUID NOT NULL REFERENCES spots(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_spot_like UNIQUE (user_id, spot_id)
);

CREATE TABLE IF NOT EXISTS direct_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sender_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_spots_geom
    ON spots USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_spots_user_id
    ON spots(user_id);

CREATE INDEX IF NOT EXISTS idx_follows_follower_id
    ON follows(follower_id);

CREATE INDEX IF NOT EXISTS idx_follows_following_id
    ON follows(following_id);

CREATE INDEX IF NOT EXISTS idx_spot_likes_user_id
    ON spot_likes(user_id);

CREATE INDEX IF NOT EXISTS idx_spot_likes_spot_id
    ON spot_likes(spot_id);

CREATE INDEX IF NOT EXISTS idx_direct_messages_sender_id
    ON direct_messages(sender_id);

CREATE INDEX IF NOT EXISTS idx_direct_messages_recipient_id
    ON direct_messages(recipient_id);
