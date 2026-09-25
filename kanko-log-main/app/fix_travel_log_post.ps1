$ErrorActionPreference = 'Stop'

Write-Host '=== Fix music ADD submit -> /spots/upload ===' -ForegroundColor Cyan

$root = (Get-Location).Path
if (-not (Test-Path (Join-Path $root 'static\add.html'))) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (Test-Path (Join-Path $scriptDir '..\static\add.html')) {
        $root = (Resolve-Path (Join-Path $scriptDir '..')).Path
    } else {
        throw 'static\add.html was not found. Run this from kanko-log-main.'
    }
}

$addPath = Join-Path $root 'static\add.html'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = "$addPath.before-spots-upload-$stamp.bak"
Copy-Item $addPath $backup -Force
Write-Host "OK: backup created: $backup" -ForegroundColor Green

$html = Get-Content $addPath -Raw -Encoding UTF8
$marker = 'TRAVEL_LOG_SPOTS_UPLOAD_PATCH_V1'

if ($html.Contains($marker)) {
    Write-Host 'OK: submit patch is already installed.' -ForegroundColor Green
    exit 0
}

$patch = @'
<!-- TRAVEL_LOG_SPOTS_UPLOAD_PATCH_V1 -->
<style>
  #travelSpotNameField { margin-top: 2px; }
  #travelSpotNameField input { width: 100%; }
  .travel-post-note {
    margin: 8px 0 0;
    color: #8a7f85;
    font-size: 11px;
    line-height: 1.6;
  }
</style>
<script>
(() => {
  function storageToken() {
    const stores = [window.localStorage, window.sessionStorage];
    const keys = [
      "access_token", "accessToken", "token", "auth_token",
      "authToken", "jwt", "jwt_token", "bearer_token"
    ];

    for (const store of stores) {
      if (!store) continue;

      for (const key of keys) {
        let value = store.getItem(key);
        if (!value) continue;

        value = String(value).trim();

        try {
          const obj = JSON.parse(value);
          value =
            obj?.access_token ||
            obj?.accessToken ||
            obj?.token ||
            obj?.jwt ||
            value;
        } catch (_) {}

        if (value && value !== "null" && value !== "undefined") {
          return value.replace(/^Bearer\s+/i, "");
        }
      }

      for (let i = 0; i < store.length; i++) {
        const key = store.key(i);
        if (!key) continue;
        const lower = key.toLowerCase();
        if (!lower.includes("token") && !lower.includes("auth")) continue;

        let value = store.getItem(key);
        if (!value) continue;

        try {
          const obj = JSON.parse(value);
          value =
            obj?.access_token ||
            obj?.accessToken ||
            obj?.token ||
            obj?.jwt ||
            "";
        } catch (_) {}

        if (value) return String(value).replace(/^Bearer\s+/i, "");
      }
    }
    return "";
  }

  function installTitleField() {
    const form = document.getElementById("postForm");
    if (!form || document.getElementById("travelSpotName")) return;

    const caption = form.querySelector('textarea[name="caption"]');
    const captionField = caption?.closest("label.field");

    const field = document.createElement("label");
    field.className = "field";
    field.id = "travelSpotNameField";
    field.innerHTML = `
      <span class="field-label">スポット名 / タイトル</span>
      <input
        id="travelSpotName"
        type="text"
        maxlength="120"
        placeholder="例：広安里海水浴場 / 釜山 DAY1"
        required
      />
      <span class="travel-post-note">ホーム画面に表示される投稿タイトルです。</span>
    `;

    if (captionField) captionField.before(field);
    else form.prepend(field);
  }

  async function submitTravelLog(event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.id !== "postForm") return;

    // The old demo handler posts to /api/posts. Stop it completely.
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    const submitButton = form.querySelector('button[type="submit"]');
    const originalText = submitButton?.textContent || "投稿する";

    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "投稿中...";
    }

    try {
      const image = document.getElementById("image")?.files?.[0];
      const caption = form.querySelector('textarea[name="caption"]')?.value?.trim() || "";
      const title =
        document.getElementById("travelSpotName")?.value?.trim() ||
        caption.slice(0, 80) ||
        "Music Log";

      if (!image) throw new Error("写真を選択してください。");

      const data = new FormData();
      data.append("name", title);
      data.append("memo", caption);
      data.append("visited_at", new Date().toISOString());
      data.append("file", image, image.name);

      // Preserve the selected YouTube music in the post memo.
      // The current Travel Log /spots/upload endpoint does not yet have
      // dedicated music columns, so this keeps the music information
      // together with the post without breaking the existing database.
      if (typeof selectedVideo !== "undefined" && selectedVideo) {
        const musicTitle = decodeEntities(selectedVideo.title || "");
        const artist = decodeEntities(selectedVideo.artist || "");
        const url =
          selectedVideo.external_url ||
          (selectedVideo.youtube_video_id
            ? `https://www.youtube.com/watch?v=${selectedVideo.youtube_video_id}`
            : "");

        const musicText =
          `\n\n🎵 ${musicTitle}` +
          (artist ? ` — ${artist}` : "") +
          (url ? `\n${url}` : "");

        data.set("memo", `${caption}${musicText}`.trim());
      }

      const headers = {};
      const token = storageToken();
      if (token) headers.Authorization = `Bearer ${token}`;

      let response = await fetch("/spots/upload", {
        method: "POST",
        headers,
        body: data,
        credentials: "same-origin"
      });

      // If the page uses a browser session rather than localStorage bearer auth,
      // the request above already includes cookies. Give a clear message on 401.
      let payload = null;
      const raw = await response.text();
      try { payload = raw ? JSON.parse(raw) : {}; } catch (_) { payload = { detail: raw }; }

      if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
          throw new Error("ログイン情報を確認できませんでした。ホームに戻ってログインし直してください。");
        }
        throw new Error(
          payload?.detail ||
          payload?.message ||
          `投稿に失敗しました (HTTP ${response.status})`
        );
      }

      // Success: return to the real Travel Log home/feed.
      window.location.assign("/");
    } catch (error) {
      alert(error?.message || "投稿に失敗しました。");
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = originalText;
      }
    }
  }

  function hideDemoFeed() {
    const feed = document.getElementById("feed");
    const section = feed?.closest("section");
    if (section) section.style.display = "none";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      installTitleField();
      hideDemoFeed();
    });
  } else {
    installTitleField();
    hideDemoFeed();
  }

  // Capture phase makes this run before the old /api/posts handler.
  document.addEventListener("submit", submitTravelLog, true);
})();
</script>
'@

if ($html -match '</body>') {
    $html = $html -replace '</body>', ($patch + "`r`n</body>")
} else {
    $html = $html + "`r`n" + $patch
}

Set-Content -Path $addPath -Value $html -Encoding UTF8

Write-Host 'OK: static/add.html now submits to POST /spots/upload' -ForegroundColor Green
Write-Host 'OK: required field "name" is supplied as Spot name / title' -ForegroundColor Green
Write-Host 'OK: photo is sent as "file", caption as "memo", current time as "visited_at"' -ForegroundColor Green
Write-Host 'OK: selected music is preserved in memo for now' -ForegroundColor Green
Write-Host ''
Write-Host 'Next:' -ForegroundColor Cyan
Write-Host '  1) Reload http://localhost:8000/static/add.html with Ctrl+F5' -ForegroundColor White
Write-Host '  2) Choose photo + title + music' -ForegroundColor White
Write-Host '  3) Press 投稿する' -ForegroundColor White
Write-Host 'No Docker rebuild is normally required for this HTML-only patch.' -ForegroundColor Yellow
