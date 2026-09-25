$ErrorActionPreference = 'Stop'

Write-Host '=== Travel Log direct submit repair V2 ===' -ForegroundColor Cyan

$root = (Get-Location).Path
$addPath = Join-Path $root 'static\add.html'

if (-not (Test-Path $addPath)) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $candidate = Join-Path $scriptDir '..\static\add.html'
    if (Test-Path $candidate) {
        $root = (Resolve-Path (Join-Path $scriptDir '..')).Path
        $addPath = Join-Path $root 'static\add.html'
    } else {
        throw 'static\add.html was not found. Run this from kanko-log-main.'
    }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = "$addPath.before-direct-submit-$stamp.bak"
Copy-Item $addPath $backup -Force
Write-Host "OK: backup created: $backup" -ForegroundColor Green

$html = Get-Content $addPath -Raw -Encoding UTF8

# Remove the earlier appended patch if present, so only one submit handler remains.
$html = [regex]::Replace(
    $html,
    '(?s)<!-- TRAVEL_LOG_SPOTS_UPLOAD_PATCH_V1 -->.*?</script>\s*',
    ''
)

# Add title field to the form markup once.
if ($html -notmatch 'id="travelSpotName"') {
    $needle = '<label class="field">'
    $idx = $html.IndexOf($needle)
    if ($idx -ge 0) {
        # Insert before the first normal field after preview by targeting the caption field label.
        $captionNeedle = '<textarea name="caption"'
        $captionIdx = $html.IndexOf($captionNeedle)
        if ($captionIdx -ge 0) {
            $labelStart = $html.LastIndexOf('<label class="field">', $captionIdx)
            if ($labelStart -ge 0) {
                $field = @'
        <label class="field">
          <span class="field-label">スポット名 / タイトル</span>
          <input id="travelSpotName" type="text" maxlength="120" placeholder="例：広安里海水浴場 / 釜山 DAY1" required />
        </label>

'@
                $html = $html.Insert($labelStart, $field)
            }
        }
    }
}

# Replace the original demo submit handler completely.
$pattern = '(?s)postForm\.addEventListener\("submit",\s*async\s*\(event\)\s*=>\s*\{.*?\n\}\);\s*\n\s*async function loadPosts\(\)'
if ($html -notmatch $pattern) {
    throw 'Could not find the original postForm submit handler in static\add.html. No changes were written.'
}

$replacement = @'
postForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const submitButton = postForm.querySelector('button[type="submit"]');
  const originalText = submitButton?.textContent || "投稿する";

  if (submitButton) {
    submitButton.disabled = true;
    submitButton.textContent = "投稿中...";
  }

  try {
    const image = imageInput.files?.[0];
    if (!image) throw new Error("写真を選択してください。");

    const caption =
      postForm.querySelector('textarea[name="caption"]')?.value?.trim() || "";

    const name =
      document.getElementById("travelSpotName")?.value?.trim() ||
      caption.slice(0, 80) ||
      "Music Log";

    const formData = new FormData();
    formData.append("name", name);
    formData.append("memo", caption);
    formData.append("visited_at", new Date().toISOString());
    formData.append("file", image, image.name);

    if (selectedVideo) {
      const musicTitle = decodeEntities(selectedVideo.title || "");
      const artist = decodeEntities(selectedVideo.artist || "");
      const videoId = selectedVideo.youtube_video_id || "";
      const youtubeUrl =
        selectedVideo.external_url ||
        (videoId ? `https://www.youtube.com/watch?v=${videoId}` : "");

      const musicText =
        `\n\n🎵 ${musicTitle}` +
        (artist ? ` — ${artist}` : "") +
        (youtubeUrl ? `\n${youtubeUrl}` : "");

      formData.set("memo", `${caption}${musicText}`.trim());
    }

    const headers = {};
    const candidateKeys = [
      "access_token", "accessToken", "token", "auth_token",
      "authToken", "jwt", "jwt_token", "bearer_token"
    ];

    for (const storage of [localStorage, sessionStorage]) {
      if (headers.Authorization) break;

      for (const key of candidateKeys) {
        let value = storage.getItem(key);
        if (!value) continue;

        try {
          const parsed = JSON.parse(value);
          value =
            parsed?.access_token ||
            parsed?.accessToken ||
            parsed?.token ||
            parsed?.jwt ||
            value;
        } catch (_) {}

        value = String(value || "").replace(/^Bearer\s+/i, "").trim();

        if (value && value !== "null" && value !== "undefined") {
          headers.Authorization = `Bearer ${value}`;
          break;
        }
      }
    }

    const response = await fetch("/spots/upload", {
      method: "POST",
      headers,
      body: formData,
      credentials: "same-origin"
    });

    const raw = await response.text();
    let data = {};
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch (_) {
      data = { detail: raw };
    }

    if (!response.ok) {
      throw new Error(
        data?.detail ||
        data?.message ||
        `投稿に失敗しました (HTTP ${response.status})`
      );
    }

    window.location.assign("/");
  } catch (error) {
    alert(error?.message || "投稿に失敗しました。");
  } finally {
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.textContent = originalText;
    }
  }
});

async function loadPosts()
'@

$html = [regex]::Replace($html, $pattern, $replacement, 1)

# Disable demo feed loading; the real Travel Log home is the feed.
$html = [regex]::Replace(
    $html,
    '(?m)^\s*loadPosts\(\);\s*$',
    '// demo loadPosts disabled; real posts are shown on Travel Log home'
)

# Hide the demo "recent posts" section if it exists.
if ($html -notmatch 'TRAVEL_LOG_HIDE_DEMO_FEED_V2') {
    $hidePatch = @'
<!-- TRAVEL_LOG_HIDE_DEMO_FEED_V2 -->
<script>
document.addEventListener("DOMContentLoaded", () => {
  const feed = document.getElementById("feed");
  const section = feed?.closest("section");
  if (section) section.style.display = "none";
});
</script>
'@
    $html = $html -replace '</body>', ($hidePatch + "`r`n</body>")
}

Set-Content -Path $addPath -Value $html -Encoding UTF8

Write-Host 'OK: old POST /api/posts submit handler was removed' -ForegroundColor Green
Write-Host 'OK: submit now uses POST /spots/upload' -ForegroundColor Green
Write-Host 'OK: spot name/title field is present' -ForegroundColor Green
Write-Host ''
Write-Host 'Verification:' -ForegroundColor Cyan
$hits = Select-String -Path $addPath -Pattern '/api/posts|/spots/upload'
$hits | ForEach-Object { Write-Host ("  line {0}: {1}" -f $_.LineNumber, $_.Line.Trim()) }
Write-Host ''
Write-Host 'Reload /static/add.html with Ctrl+F5 and try posting again.' -ForegroundColor Yellow
