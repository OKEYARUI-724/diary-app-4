$ErrorActionPreference = 'Stop'

Write-Host '=== Repair YouTube endpoint syntax ===' -ForegroundColor Cyan

# Find project root.
$root = (Get-Location).Path
if (-not (Test-Path (Join-Path $root 'docker-compose.yml'))) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (Test-Path (Join-Path $scriptDir '..\docker-compose.yml')) {
        $root = (Resolve-Path (Join-Path $scriptDir '..')).Path
    } else {
        throw 'Project root not found. Run from kanko-log-main.'
    }
}

$mainPath = Join-Path $root 'app\main.py'
$composePath = Join-Path $root 'docker-compose.yml'
$requirementsPath = Join-Path $root 'requirements.txt'
$envPath = Join-Path $root '.env'

if (-not (Test-Path $mainPath)) { throw "Missing file: $mainPath" }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item $mainPath "$mainPath.before-youtube-syntax-$stamp.bak"
Write-Host 'OK: backup created' -ForegroundColor Green

# Read/write explicitly as UTF-8 without BOM.
$utf8 = New-Object System.Text.UTF8Encoding($false)
$text = [System.IO.File]::ReadAllText($mainPath, [System.Text.Encoding]::UTF8)

# Remove the previously appended broken block.
$marker = '# === YouTube music search API (added by fix_youtube_music.ps1) ==='
$idx = $text.IndexOf($marker, [System.StringComparison]::Ordinal)
if ($idx -ge 0) {
    $text = $text.Substring(0, $idx).TrimEnd() + "`r`n`r`n"
    Write-Host 'OK: removed broken YouTube endpoint block' -ForegroundColor Green
} else {
    # Fallback: if the route exists but the marker was altered, stop before making duplicates.
    if ($text -match '@app\.get\(["'']\/api\/music\/search["'']\)') {
        throw 'Existing /api/music/search route found without the repair marker. Please send app/main.py so it can be repaired safely.'
    }
    Write-Host 'INFO: broken marker not found; adding endpoint once' -ForegroundColor Yellow
}

$endpoint = @'
# === YouTube music search API (ASCII-safe repair) ===
@app.get("/api/music/search")
async def youtube_music_search(q: str, limit: int = 10):
    import os
    import httpx
    from fastapi import HTTPException

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

        items.append({
            "youtube_video_id": video_id,
            "title": snippet.get("title") or "",
            "artist": snippet.get("channelTitle") or "",
            "cover_url": cover_url,
            "external_url": f"https://www.youtube.com/watch?v={video_id}",
            "embed_url": f"https://www.youtube.com/embed/{video_id}",
        })

    return {"items": items}
# === end YouTube music search API ===
'@

$text = $text + $endpoint + "`r`n"
[System.IO.File]::WriteAllText($mainPath, $text, $utf8)
Write-Host 'OK: wrote clean /api/music/search endpoint' -ForegroundColor Green

# Ensure httpx exists in requirements.txt.
if (Test-Path $requirementsPath) {
    $req = [System.IO.File]::ReadAllText($requirementsPath, [System.Text.Encoding]::UTF8)
    if ($req -notmatch '(?m)^httpx(?:[<>=~!].*)?$') {
        $req = $req.TrimEnd() + "`r`nhttpx>=0.27.0`r`n"
        [System.IO.File]::WriteAllText($requirementsPath, $req, $utf8)
        Write-Host 'OK: added httpx to requirements.txt' -ForegroundColor Green
    } else {
        Write-Host 'OK: httpx already present' -ForegroundColor Green
    }
}

# Ensure YOUTUBE_API_KEY is passed into the API container.
if (Test-Path $composePath) {
    $compose = [System.IO.File]::ReadAllText($composePath, [System.Text.Encoding]::UTF8)
    if ($compose -notmatch '(?m)^\s*YOUTUBE_API_KEY\s*:') {
        $dbLine = '      DATABASE_URL: postgresql+psycopg2://postgres:password@db:5432/kanko_db'
        if ($compose.Contains($dbLine)) {
            $compose = $compose.Replace($dbLine, $dbLine + "`r`n      YOUTUBE_API_KEY: `${YOUTUBE_API_KEY:-}")
            [System.IO.File]::WriteAllText($composePath, $compose, $utf8)
            Write-Host 'OK: added YOUTUBE_API_KEY to docker-compose.yml' -ForegroundColor Green
        } else {
            Write-Host 'WARNING: could not locate DATABASE_URL line in docker-compose.yml' -ForegroundColor Yellow
        }
    } else {
        Write-Host 'OK: YOUTUBE_API_KEY already present in docker-compose.yml' -ForegroundColor Green
    }
}

if (Test-Path $envPath) {
    $envText = [System.IO.File]::ReadAllText($envPath, [System.Text.Encoding]::UTF8)
    if ($envText -match '(?m)^YOUTUBE_API_KEY\s*=\s*([^\r\n]+)') {
        if ($Matches[1].Trim().Length -gt 10) {
            Write-Host 'OK: .env contains YOUTUBE_API_KEY (hidden)' -ForegroundColor Green
        } else {
            Write-Host 'WARNING: YOUTUBE_API_KEY looks empty or too short' -ForegroundColor Yellow
        }
    } else {
        Write-Host 'WARNING: .env does not contain YOUTUBE_API_KEY' -ForegroundColor Yellow
    }
} else {
    Write-Host 'WARNING: .env not found' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '=== Repair complete ===' -ForegroundColor Cyan
Write-Host 'Next:' -ForegroundColor White
Write-Host '  docker rm -f kanko_db kanko_api' -ForegroundColor White
Write-Host '  docker compose up --build' -ForegroundColor White
