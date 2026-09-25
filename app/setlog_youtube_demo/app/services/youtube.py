import os
import re

import httpx
from fastapi import HTTPException

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _api_key() -> str:
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="YouTube APIキーが未設定です。.env に YOUTUBE_API_KEY を設定してください。",
        )
    return api_key


def _best_thumbnail(thumbnails: dict) -> str | None:
    for key in ("maxres", "standard", "high", "medium", "default"):
        item = thumbnails.get(key) or {}
        url = item.get("url")
        if url:
            return str(url)
    return None


def _youtube_error(response: httpx.Response, fallback: str) -> HTTPException:
    detail = fallback
    try:
        payload = response.json()
        message = ((payload.get("error") or {}).get("message") or "").strip()
        if message:
            detail = f"{fallback} ({message})"
    except Exception:
        pass
    return HTTPException(status_code=502, detail=detail)


async def search_videos(query: str, limit: int = 10) -> list[dict]:
    api_key = _api_key()

    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max(1, min(limit, 20)),
        "regionCode": "JP",
        "relevanceLanguage": "ja",
        "safeSearch": "moderate",
        "videoEmbeddable": "true",
        "key": api_key,
    }

    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(SEARCH_URL, params=params)

    if response.status_code >= 400:
        raise _youtube_error(response, "YouTubeの動画検索に失敗しました。")

    results: list[dict] = []
    for item in response.json().get("items", []):
        video_id = ((item.get("id") or {}).get("videoId") or "").strip()
        snippet = item.get("snippet") or {}
        if not VIDEO_ID_RE.fullmatch(video_id):
            continue

        results.append(
            {
                "youtube_video_id": video_id,
                "title": snippet.get("title"),
                "artist": snippet.get("channelTitle"),
                "cover_url": _best_thumbnail(snippet.get("thumbnails") or {}),
                "external_url": f"https://www.youtube.com/watch?v={video_id}",
                "embed_url": f"https://www.youtube.com/embed/{video_id}",
            }
        )

    return results


async def get_video(video_id: str) -> dict:
    api_key = _api_key()
    video_id = (video_id or "").strip()
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise HTTPException(status_code=400, detail="YouTube動画IDが正しくありません。")

    params = {
        "part": "snippet,status",
        "id": video_id,
        "key": api_key,
    }

    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(VIDEOS_URL, params=params)

    if response.status_code >= 400:
        raise _youtube_error(response, "YouTubeの動画情報取得に失敗しました。")

    items = response.json().get("items", [])
    if not items:
        raise HTTPException(status_code=400, detail="選択したYouTube動画が見つかりませんでした。")

    item = items[0]
    snippet = item.get("snippet") or {}
    status = item.get("status") or {}

    if status.get("embeddable") is False:
        raise HTTPException(status_code=400, detail="この動画は外部サイトへの埋め込みが許可されていません。")

    return {
        "youtube_video_id": video_id,
        "title": snippet.get("title"),
        "artist": snippet.get("channelTitle"),
        "cover_url": _best_thumbnail(snippet.get("thumbnails") or {}),
        "external_url": f"https://www.youtube.com/watch?v={video_id}",
        "embed_url": f"https://www.youtube.com/embed/{video_id}",
    }
