-- Travel Log social feature migration
-- Safe for the current schema that already uses follows.following_id.

CREATE EXTENSION IF NOT EXISTS postgis;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS is_private BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE follows
ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'accepted';

UPDATE follows
SET status = 'accepted'
WHERE status IS NULL;

CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY,
    recipient_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sender_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL,
    message VARCHAR(255) NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient_created
ON notifications(recipient_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_follows_status
ON follows(status);
