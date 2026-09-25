$ErrorActionPreference = 'Stop'

Write-Host '=== Travel Log POP 2D Home + Music Player ===' -ForegroundColor Cyan

# Find the real project root even if this script is placed inside app/.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$candidates = @(
    (Get-Location).Path,
    $scriptDir,
    (Join-Path $scriptDir '..'),
    (Join-Path $scriptDir '..\..'),
    (Join-Path $scriptDir '..\..\..')
)

$root = $null
foreach ($candidate in $candidates) {
    try {
        $resolved = (Resolve-Path $candidate -ErrorAction Stop).Path
        if (
            (Test-Path (Join-Path $resolved 'static\index.html')) -and
            (Test-Path (Join-Path $resolved 'docker-compose.yml'))
        ) {
            $root = $resolved
            break
        }
    } catch {}
}

if (-not $root) {
    throw 'kanko-log-main could not be found. The project root must contain static\index.html and docker-compose.yml.'
}

$homePath = Join-Path $root 'static\index.html'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupPath = "$homePath.before-pop2d-$stamp.bak"

Copy-Item $homePath $backupPath -Force
Write-Host "Project root: $root"
Write-Host "OK: backup created: $backupPath" -ForegroundColor Green

$html = Get-Content $homePath -Raw -Encoding UTF8

# Remove an older copy of this patch so it is safe to run again.
$html = [regex]::Replace(
    $html,
    '(?s)<!-- POP2D_HOME_MUSIC_V2_START -->.*?<!-- POP2D_HOME_MUSIC_V2_END -->\s*',
    ''
)

$patch = @'
<!-- POP2D_HOME_MUSIC_V2_START -->
<style id="pop2d-home-music-style">
:root {
  --pop-ink: #302a38;
  --pop-sub: #766d7b;
  --pop-line: #393240;
  --pop-paper: #fffaf7;
  --pop-lav: #b8a8c8;
  --pop-lav-2: #d7cadf;
  --pop-sage: #adbea9;
  --pop-sage-2: #d0dbcd;
  --pop-rose: #cba8b1;
  --pop-rose-2: #ead1d6;
  --pop-peach: #d4b09f;
  --pop-sand: #d8c7aa;
  --pop-sky: #aebdca;
  --pop-grad: linear-gradient(135deg, #b8a8c8 0%, #adbea9 52%, #cba8b1 100%);
  --pop-soft-grad: linear-gradient(135deg, #eee5f0 0%, #e4ece2 48%, #f0e2e5 100%);
}

/* Page */
html, body {
  min-height: 100%;
}

body {
  color: var(--pop-ink) !important;
  background:
    radial-gradient(circle at 6% 7%, rgba(184,168,200,.48) 0 150px, transparent 330px),
    radial-gradient(circle at 96% 22%, rgba(173,190,169,.48) 0 150px, transparent 330px),
    radial-gradient(circle at 68% 92%, rgba(203,168,177,.40) 0 170px, transparent 350px),
    linear-gradient(140deg, #eee8ed 0%, #e7ece6 48%, #f1e7e4 100%) !important;
  background-attachment: fixed !important;
}

/* More 2D, less glass */
body.pop2d-ready header,
body.pop2d-ready .header,
body.pop2d-ready .topbar,
body.pop2d-ready .top-bar,
body.pop2d-ready .navbar,
body.pop2d-ready .nav-bar,
body.pop2d-ready .pop2d-header {
  background: #fffaf7 !important;
  border-color: var(--pop-line) !important;
  box-shadow: 0 4px 0 rgba(48,42,56,.12) !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

body.pop2d-ready button,
body.pop2d-ready .btn,
body.pop2d-ready [role="button"] {
  border-radius: 999px !important;
}

body.pop2d-ready input,
body.pop2d-ready textarea,
body.pop2d-ready select {
  border: 1.6px solid rgba(48,42,56,.25) !important;
  border-radius: 16px !important;
  background: #fffdfb !important;
  color: var(--pop-ink) !important;
  box-shadow: 2px 3px 0 rgba(48,42,56,.08) !important;
}

/* Header/nav automatically tagged by JS */
.pop2d-header {
  position: relative;
  overflow: hidden;
}

.pop2d-header::after {
  content: "";
  position: absolute;
  right: -35px;
  top: -42px;
  width: 105px;
  height: 105px;
  border-radius: 50%;
  background: linear-gradient(135deg, rgba(184,168,200,.34), rgba(203,168,177,.28));
  pointer-events: none;
}

.pop2d-header strong,
.pop2d-header h1,
.pop2d-header h2 {
  letter-spacing: .14em !important;
}

/* + ADD */
.pop2d-add-btn {
  color: #fff !important;
  border: 2px solid var(--pop-ink) !important;
  background: var(--pop-grad) !important;
  box-shadow: 4px 4px 0 rgba(48,42,56,.22) !important;
  transition: transform .14s ease, box-shadow .14s ease !important;
}

.pop2d-add-btn:hover {
  transform: translate(-1px, -1px) !important;
  box-shadow: 5px 5px 0 rgba(48,42,56,.22) !important;
}

/* ALL / FOLLOWING etc. */
.pop2d-tab {
  border-radius: 999px !important;
  padding: 8px 13px !important;
  border: 1.5px solid transparent !important;
}

.pop2d-tab.is-pop-active,
.pop2d-tab[aria-selected="true"] {
  border-color: var(--pop-ink) !important;
  background: linear-gradient(135deg, var(--pop-lav-2), var(--pop-sage-2)) !important;
  box-shadow: 3px 3px 0 rgba(48,42,56,.12) !important;
}

/* Date/filter panel */
.pop2d-filter-panel {
  border: 2px solid rgba(48,42,56,.86) !important;
  border-radius: 20px !important;
  background:
    linear-gradient(90deg, rgba(234,209,214,.72), rgba(255,250,247,.96) 45%, rgba(208,219,205,.72)) !important;
  box-shadow: 5px 5px 0 rgba(48,42,56,.11) !important;
}

/* Post */
.pop2d-post-card {
  position: relative !important;
  overflow: hidden !important;
  border: 2px solid var(--pop-ink) !important;
  border-radius: 24px !important;
  background: #fffaf7 !important;
  box-shadow: 6px 7px 0 rgba(88,75,95,.18) !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

.pop2d-post-card::before {
  content: "";
  position: absolute;
  z-index: 2;
  left: 0;
  top: 0;
  width: 100%;
  height: 5px;
  background: var(--pop-grad);
  pointer-events: none;
}

.pop2d-post-card img {
  filter: saturate(.94) contrast(.98);
}

.pop2d-post-card button,
.pop2d-post-card a[role="button"] {
  border: 1.5px solid var(--pop-ink) !important;
  background: #fffaf7 !important;
  color: var(--pop-ink) !important;
  box-shadow: 2px 2px 0 rgba(48,42,56,.12) !important;
}

.pop2d-post-card .pop2d-map-btn {
  background: linear-gradient(135deg, #e8dfed, #dce6d9) !important;
}

/* Small sticker decor on posts */
.pop2d-post-sticker {
  position: absolute;
  z-index: 5;
  right: 14px;
  top: 62px;
  width: 13px;
  height: 13px;
  border-radius: 4px;
  background: var(--pop-rose);
  border: 1.5px solid var(--pop-ink);
  transform: rotate(10deg);
  pointer-events: none;
}

/* Music bar attached to each post */
.pop2d-music-wrap {
  margin: 12px 13px 14px;
  border: 2px solid var(--pop-ink);
  border-radius: 18px;
  overflow: hidden;
  background:
    linear-gradient(135deg, #ebe3ef 0%, #e1e9df 50%, #efdfe3 100%);
  box-shadow: 4px 4px 0 rgba(48,42,56,.13);
}

.pop2d-music-row {
  min-width: 0;
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) auto;
  align-items: center;
  gap: 11px;
  padding: 10px;
}

.pop2d-music-thumb {
  width: 72px;
  height: 48px;
  object-fit: cover;
  border-radius: 11px;
  border: 1.5px solid var(--pop-ink);
  background: #d9d1db;
}

.pop2d-music-info {
  min-width: 0;
}

.pop2d-music-kicker {
  display: block;
  margin-bottom: 3px;
  color: #84758d;
  font-size: 9px;
  font-weight: 900;
  letter-spacing: .16em;
}

.pop2d-music-title {
  display: block;
  overflow: hidden;
  color: var(--pop-ink);
  font-size: 12px;
  font-weight: 900;
  line-height: 1.35;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.pop2d-music-artist {
  display: block;
  overflow: hidden;
  margin-top: 3px;
  color: var(--pop-sub);
  font-size: 10px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.pop2d-play-btn {
  width: 44px !important;
  height: 44px !important;
  display: grid !important;
  place-items: center !important;
  padding: 0 !important;
  border: 2px solid var(--pop-ink) !important;
  border-radius: 50% !important;
  background: linear-gradient(135deg, var(--pop-rose), var(--pop-lav)) !important;
  color: #fff !important;
  box-shadow: 3px 3px 0 rgba(48,42,56,.18) !important;
  font-size: 17px !important;
  font-weight: 900 !important;
}

.pop2d-play-btn.is-playing {
  background: linear-gradient(135deg, var(--pop-sage), var(--pop-sky)) !important;
}

.pop2d-inline-player {
  display: none;
  border-top: 2px solid var(--pop-ink);
  background: #27232a;
}

.pop2d-inline-player.is-open {
  display: block;
}

.pop2d-player-ratio {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #111;
}

.pop2d-player-ratio iframe {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
}

.pop2d-player-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 9px;
  padding: 8px 10px;
  color: #efe9ef;
  font-size: 10px;
}

.pop2d-player-bottom a {
  color: #efe9ef !important;
  text-decoration: underline;
  text-underline-offset: 3px;
}

@media (max-width: 560px) {
  .pop2d-post-card {
    border-radius: 20px !important;
    box-shadow: 4px 5px 0 rgba(88,75,95,.16) !important;
  }

  .pop2d-music-wrap {
    margin: 10px 10px 13px;
    border-radius: 16px;
  }

  .pop2d-music-row {
    grid-template-columns: 62px minmax(0, 1fr) 42px;
    gap: 8px;
    padding: 9px;
  }

  .pop2d-music-thumb {
    width: 62px;
    height: 42px;
  }

  .pop2d-play-btn {
    width: 40px !important;
    height: 40px !important;
  }
}

@media (prefers-reduced-motion: reduce) {
  .pop2d-add-btn,
  .pop2d-post-card button {
    transition: none !important;
  }
}
</style>

<script id="pop2d-home-music-script">
(() => {
  if (window.__travelLogPop2dMusicV2) return;
  window.__travelLogPop2dMusicV2 = true;

  const YT_RE = /(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/watch\?(?:[^#\s]*&)?v=|youtu\.be\/|youtube\.com\/shorts\/)([A-Za-z0-9_-]{11})/i;

  function cleanText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function tagHeaderAndControls() {
    const all = Array.from(document.querySelectorAll("body *"));

    // Header containing TRAVEL LOG.
    const brand = all.find(el => cleanText(el.textContent) === "TRAVEL LOG");
    if (brand) {
      let node = brand;
      for (let i = 0; i < 5 && node; i++, node = node.parentElement) {
        const rect = node.getBoundingClientRect();
        if (rect.width > 300 && rect.height >= 55 && rect.height < 190) {
          node.classList.add("pop2d-header");
          break;
        }
      }
    }

    // + / ADD button.
    document.querySelectorAll("button,a,[role='button']").forEach(el => {
      const text = cleanText(el.textContent).toUpperCase();
      if (
        text === "+" ||
        text === "ADD" ||
        text === "+ ADD" ||
        text === "+ADD"
      ) {
        el.classList.add("pop2d-add-btn");
      }

      if (text === "ALL" || text === "FOLLOWING") {
        el.classList.add("pop2d-tab");
        if (
          el.classList.contains("active") ||
          el.getAttribute("aria-selected") === "true"
        ) {
          el.classList.add("is-pop-active");
        }
      }

      if (/^MAP(?:\s|↗|$)/i.test(text)) {
        el.classList.add("pop2d-map-btn");
      }
    });

    // Date/filter box.
    const dateInput = document.querySelector('input[type="date"]');
    if (dateInput) {
      let node = dateInput.parentElement;
      for (let i = 0; i < 4 && node; i++, node = node.parentElement) {
        const rect = node.getBoundingClientRect();
        if (rect.width > 250 && rect.height >= 45 && rect.height <= 150) {
          node.classList.add("pop2d-filter-panel");
          break;
        }
      }
    }
  }

  function findPostRoot(mapButton) {
    let node = mapButton;
    let fallback = null;

    for (let i = 0; i < 9 && node; i++, node = node.parentElement) {
      if (!(node instanceof HTMLElement)) continue;

      const rect = node.getBoundingClientRect();
      const images = node.querySelectorAll("img");

      if (images.length && rect.width > 260 && rect.height > 180) {
        fallback = node;
      }

      if (
        node.matches("article,.spot-card,.post-card,.log-card,.card") &&
        images.length
      ) {
        return node;
      }
    }

    return fallback;
  }

  function parseMusic(card) {
    const text = card.innerText || card.textContent || "";
    const match = text.match(YT_RE);
    if (!match) return null;

    const id = match[1];
    const urlMatch = text.match(/https?:\/\/[^\s]+(?:youtube\.com|youtu\.be)[^\s]*/i);
    const externalUrl = urlMatch
      ? urlMatch[0].replace(/[),.;]+$/, "")
      : `https://www.youtube.com/watch?v=${id}`;

    let musicLine = "";
    const lines = String(text)
      .split(/\r?\n/)
      .map(v => v.trim())
      .filter(Boolean);

    const emojiLine = lines.find(line => line.includes("🎵"));
    if (emojiLine) musicLine = emojiLine.replace(/^.*?🎵\s*/, "").trim();

    let title = musicLine || "この投稿の1曲";
    let artist = "YouTube";

    const separator = title.includes(" — ")
      ? " — "
      : title.includes(" - ")
        ? " - "
        : null;

    if (separator) {
      const parts = title.split(separator);
      title = parts.shift()?.trim() || "この投稿の1曲";
      artist = parts.join(separator).trim() || "YouTube";
    }

    return { id, title, artist, externalUrl };
  }

  function closeAllPlayers(exceptWrap) {
    document.querySelectorAll(".pop2d-music-wrap").forEach(wrap => {
      if (wrap === exceptWrap) return;

      const player = wrap.querySelector(".pop2d-inline-player");
      const iframe = wrap.querySelector("iframe");
      const button = wrap.querySelector(".pop2d-play-btn");

      if (player) player.classList.remove("is-open");
      if (iframe) iframe.src = "";
      if (button) {
        button.classList.remove("is-playing");
        button.textContent = "▶";
        button.setAttribute("aria-label", "音楽を再生");
      }
    });
  }

  function hideRawMusicMetadata(card) {
    card.querySelectorAll("p,span,div").forEach(el => {
      if (el.classList.contains("pop2d-music-wrap")) return;
      if (el.closest(".pop2d-music-wrap")) return;

      if (el.children.length > 2) return;

      const text = el.innerText || "";
      if (!text.includes("🎵") || !YT_RE.test(text)) return;

      const before = text.split("🎵")[0].trim();

      if (el.children.length === 0) {
        if (before) {
          el.textContent = before;
        } else {
          el.style.display = "none";
        }
      }
    });
  }

  function addMusicPlayer(card, music) {
    if (card.querySelector(".pop2d-music-wrap")) return;

    const wrap = document.createElement("div");
    wrap.className = "pop2d-music-wrap";

    const thumb = `https://i.ytimg.com/vi/${encodeURIComponent(music.id)}/mqdefault.jpg`;

    wrap.innerHTML = `
      <div class="pop2d-music-row">
        <img class="pop2d-music-thumb" src="${thumb}" alt="">
        <div class="pop2d-music-info">
          <span class="pop2d-music-kicker">THIS POST'S SONG</span>
          <strong class="pop2d-music-title"></strong>
          <span class="pop2d-music-artist"></span>
        </div>
        <button type="button" class="pop2d-play-btn" aria-label="音楽を再生">▶</button>
      </div>
      <div class="pop2d-inline-player">
        <div class="pop2d-player-ratio">
          <iframe
            title="YouTube player"
            src=""
            allow="autoplay; encrypted-media; picture-in-picture"
            referrerpolicy="strict-origin-when-cross-origin"
            allowfullscreen
          ></iframe>
        </div>
        <div class="pop2d-player-bottom">
          <span>この投稿の音楽</span>
          <a target="_blank" rel="noopener noreferrer">YouTubeで開く ↗</a>
        </div>
      </div>
    `;

    wrap.querySelector(".pop2d-music-title").textContent = music.title;
    wrap.querySelector(".pop2d-music-artist").textContent = music.artist;
    wrap.querySelector(".pop2d-player-bottom a").href = music.externalUrl;

    const button = wrap.querySelector(".pop2d-play-btn");
    const player = wrap.querySelector(".pop2d-inline-player");
    const iframe = wrap.querySelector("iframe");

    button.addEventListener("click", () => {
      const opening = !player.classList.contains("is-open");

      if (!opening) {
        player.classList.remove("is-open");
        iframe.src = "";
        button.classList.remove("is-playing");
        button.textContent = "▶";
        button.setAttribute("aria-label", "音楽を再生");
        return;
      }

      closeAllPlayers(wrap);

      iframe.src =
        `https://www.youtube.com/embed/${encodeURIComponent(music.id)}` +
        "?autoplay=1&playsinline=1&rel=0";

      player.classList.add("is-open");
      button.classList.add("is-playing");
      button.textContent = "■";
      button.setAttribute("aria-label", "音楽を停止");
    });

    // Put it after the main post image if possible.
    const images = Array.from(card.querySelectorAll("img"));
    let mainImage = null;
    let maxArea = 0;

    images.forEach(img => {
      const rect = img.getBoundingClientRect();
      const area = rect.width * rect.height;
      if (rect.width > 180 && rect.height > 120 && area > maxArea) {
        mainImage = img;
        maxArea = area;
      }
    });

    if (mainImage) {
      const imageBlock = mainImage.parentElement || mainImage;
      imageBlock.insertAdjacentElement("afterend", wrap);
    } else {
      card.appendChild(wrap);
    }

    hideRawMusicMetadata(card);
  }

  function decoratePosts() {
    const mapButtons = Array.from(
      document.querySelectorAll("button,a,[role='button']")
    ).filter(el => /^MAP(?:\s|↗|$)/i.test(cleanText(el.textContent)));

    mapButtons.forEach(mapButton => {
      const card = findPostRoot(mapButton);
      if (!card) return;

      card.classList.add("pop2d-post-card");
      mapButton.classList.add("pop2d-map-btn");

      if (!card.querySelector(".pop2d-post-sticker")) {
        const sticker = document.createElement("span");
        sticker.className = "pop2d-post-sticker";
        sticker.setAttribute("aria-hidden", "true");
        card.appendChild(sticker);
      }

      const music = parseMusic(card);
      if (music) addMusicPlayer(card, music);
    });
  }

  let scheduled = false;
  function refreshPopUi() {
    if (scheduled) return;
    scheduled = true;

    requestAnimationFrame(() => {
      scheduled = false;
      document.body.classList.add("pop2d-ready");
      tagHeaderAndControls();
      decoratePosts();
    });
  }

  refreshPopUi();

  const observer = new MutationObserver(refreshPopUi);
  observer.observe(document.body, {
    childList: true,
    subtree: true
  });

  window.addEventListener("resize", refreshPopUi, { passive: true });
})();
</script>
<!-- POP2D_HOME_MUSIC_V2_END -->
'@

if ($html -match '</body>') {
    $html = $html -replace '</body>', ($patch + "`r`n</body>")
} else {
    $html += "`r`n" + $patch
}

[IO.File]::WriteAllText($homePath, $html, [Text.UTF8Encoding]::new($false))

Write-Host ''
Write-Host 'DONE' -ForegroundColor Green
Write-Host 'Applied:' -ForegroundColor Cyan
Write-Host '  - POP / 2D muted-gradient home UI'
Write-Host '  - Flat outlined post cards'
Write-Host '  - Muted lavender / sage / dusty-rose colors'
Write-Host '  - Music play bar on posts containing a YouTube music URL'
Write-Host '  - Inline YouTube player; opening another post stops the previous player'
Write-Host ''
Write-Host 'Open http://localhost:8000 and press Ctrl+F5.' -ForegroundColor Yellow
Write-Host 'Docker rebuild is normally NOT required.' -ForegroundColor Yellow
