$ErrorActionPreference = 'Stop'

Write-Host '=== YouTube music API repair ===' -ForegroundColor Cyan

# Resolve project root from current directory or this script location.
$current = Get-Location
$root = $current.Path
if (-not (Test-Path (Join-Path $root 'docker-compose.yml'))) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (Test-Path (Join-Path $scriptDir '..\docker-compose.yml')) {
        $root = (Resolve-Path (Join-Path $scriptDir '..')).Path
    } elseif (Test-Path (Join-Path $scriptDir 'docker-compose.yml')) {
        $root = $scriptDir
    } else {
        throw 'kanko-log-main project root could not be found. Run this script from the project root.'
    }
}

Write-Host "Project root: $root"

$composePath = Join-Path $root 'docker-compose.yml'
$requirementsPath = Join-Path $root 'requirements.txt'
$mainPath = Join-Path $root 'app\main.py'
$envPath = Join-Path $root '.env'

foreach ($p in @($composePath, $requirementsPath, $mainPath)) {
    if (-not (Test-Path $p)) { throw "Required file not found: $p" }
}

# Backups
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item $composePath "$composePath.before-youtube-$stamp.bak"
Copy-Item $requirementsPath "$requirementsPath.before-youtube-$stamp.bak"
Copy-Item $mainPath "$mainPath.before-youtube-$stamp.bak"
Write-Host 'OK: backups created' -ForegroundColor Green

# 1) Ensure httpx dependency.
$requirements = Get-Content $requirementsPath -Raw
if ($requirements -notmatch '(?m)^httpx(?:[<>=~!].*)?$') {
    Add-Content -Path $requirementsPath -Value "`nhttpx>=0.27.0"
    Write-Host 'OK: added httpx to requirements.txt' -ForegroundColor Green
} else {
    Write-Host 'OK: httpx already present' -ForegroundColor Green
}

# 2) Ensure Docker passes YOUTUBE_API_KEY from .env into the api container.
$compose = Get-Content $composePath -Raw
if ($compose -notmatch '(?m)^\s*YOUTUBE_API_KEY\s*:') {
    $needle = '      DATABASE_URL: postgresql+psycopg2://postgres:password@db:5432/kanko_db'
    if ($compose.Contains($needle)) {
        $replacement = $needle + "`r`n      YOUTUBE_API_KEY: `${YOUTUBE_API_KEY:-}"
        $compose = $compose.Replace($needle, $replacement)
        Set-Content -Path $composePath -Value $compose -Encoding UTF8
        Write-Host 'OK: added YOUTUBE_API_KEY to docker-compose.yml' -ForegroundColor Green
    } else {
        throw 'Could not find api environment section in docker-compose.yml.'
    }
} else {
    Write-Host 'OK: YOUTUBE_API_KEY already present in docker-compose.yml' -ForegroundColor Green
}

# 3) Append the missing FastAPI search endpoint only once.
$main = Get-Content $mainPath -Raw
if ($main -notmatch '/api/music/search') {
$pythonPatch = @'

# === YouTube music search API (added by fix_youtube_music.ps1) ===
@app.get("/api/music/search")
async def youtube_music_search(q: str, limit: int = 10):
    """Search public YouTube videos for the music picker."""
    import os
    import httpx
    from fastapi import HTTPException

    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="曲名かアーティスト名を入力してください。")

    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="YOUTUBE_API_KEY がサーバーに設定されていません。.env と docker-compose.yml を確認してください。",
        )

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
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"YouTube API に接続できませんでした: {exc}")

    if response.status_code != 200:
        try:
            payload = response.json()
            message = (
                payload.get("error", {}).get("message")
                or "YouTube API の検索に失敗しました。"
            )
        except Exception:
            message = "YouTube API の検索に失敗しました。"
        raise HTTPException(status_code=response.status_code, detail=message)

    payload = response.json()
    items = []
    for item in payload.get("items", []):
        video_id = (item.get("id") or {}).get("videoId")
        snippet = item.get("snippet") or {}
        if not video_id:
            continue

        thumbs = snippet.get("thumbnails") or {}
        thumb = (
            (thumbs.get("high") or {}).get("url")
            or (thumbs.get("medium") or {}).get("url")
            or (thumbs.get("default") or {}).get("url")
            or ""
        )
        items.append({
            "youtube_video_id": video_id,
            "title": snippet.get("title") or "",
            "artist": snippet.get("channelTitle") or "",
            "cover_url": thumb,
            "external_url": f"https://www.youtube.com/watch?v={video_id}",
            "embed_url": f"https://www.youtube.com/embed/{video_id}",
        })

    return {"items": items}
# === end YouTube music search API ===
'@
    Add-Content -Path $mainPath -Value $pythonPatch -Encoding UTF8
    Write-Host 'OK: added /api/music/search to app/main.py' -ForegroundColor Green
} else {
    Write-Host 'OK: /api/music/search already exists in app/main.py' -ForegroundColor Green
}

# 4) Check .env presence without printing the secret.
if (-not (Test-Path $envPath)) {
    Write-Host 'WARNING: .env was not found.' -ForegroundColor Yellow
    Write-Host 'Create .env and add: YOUTUBE_API_KEY=your_new_api_key' -ForegroundColor Yellow
} else {
    $envText = Get-Content $envPath -Raw
    if ($envText -match '(?m)^YOUTUBE_API_KEY\s*=\s*([^\r\n]+)') {
        $value = $Matches[1].Trim()
        if ($value.Length -gt 10) {
            Write-Host 'OK: YOUTUBE_API_KEY exists in .env (value hidden)' -ForegroundColor Green
        } else {
            Write-Host 'WARNING: YOUTUBE_API_KEY looks empty or too short.' -ForegroundColor Yellow
        }
    } else {
        Write-Host 'WARNING: YOUTUBE_API_KEY is missing from .env.' -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host '=== Repair complete ===' -ForegroundColor Cyan
Write-Host 'Next commands:' -ForegroundColor White
Write-Host '  docker rm -f kanko_db kanko_api' -ForegroundColor White
Write-Host '  docker compose up --build' -ForegroundColor White
Write-Host ''
Write-Host 'Then open http://localhost:8000 and try the ADD music search again.' -ForegroundColor White
