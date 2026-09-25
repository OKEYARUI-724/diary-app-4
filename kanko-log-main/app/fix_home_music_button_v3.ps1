$ErrorActionPreference = 'Stop'

Write-Host '=== Fix Home Music Play Button V3 ===' -ForegroundColor Cyan

# Locate the real project root.
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
    throw 'kanko-log-main could not be found.'
}

$homePath = Join-Path $root 'static\index.html'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupPath = "$homePath.before-music-button-v3-$stamp.bak"

Copy-Item $homePath $backupPath -Force
Write-Host "Project root: $root"
Write-Host "OK: backup created: $backupPath" -ForegroundColor Green

$html = Get-Content $homePath -Raw -Encoding UTF8

# Safe to run more than once.
$html = [regex]::Replace(
    $html,
    '(?s)<!-- HOME_MUSIC_BUTTON_V3_START -->.*?<!-- HOME_MUSIC_BUTTON_V3_END -->\s*',
    ''
)

$patch = @'
<!-- HOME_MUSIC_BUTTON_V3_START -->
<style id="home-music-button-v3-style">
.home-music-v3-wrap {
  margin: 12px 16px 15px;
  overflow: hidden;
  border: 2px solid #302a38;
  border-radius: 18px;
  background: linear-gradient(135deg, #eee5f0 0%, #e2ebe0 50%, #f0e0e4 100%);
  box-shadow: 4px 4px 0 rgba(48,42,56,.14);
}

.home-music-v3-row {
  display: grid;
  grid-template-columns: 70px minmax(0,1fr) 46px;
  align-items: center;
  gap: 11px;
  padding: 10px;
}

.home-music-v3-thumb {
  width: 70px;
  height: 46px;
  object-fit: cover;
  border: 1.5px solid #302a38;
  border-radius: 11px;
  background: #d8d0db;
}

.home-music-v3-meta {
  min-width: 0;
}

.home-music-v3-label {
  display: block;
  margin-bottom: 3px;
  color: #8b788f;
  font-size: 9px;
  font-weight: 900;
  letter-spacing: .15em;
}

.home-music-v3-title {
  display: block;
  overflow: hidden;
  color: #302a38;
  font-size: 12px;
  font-weight: 900;
  line-height: 1.35;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.home-music-v3-artist {
  display: block;
  overflow: hidden;
  margin-top: 3px;
  color: #766d7b;
  font-size: 10px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.home-music-v3-play {
  width: 44px !important;
  height: 44px !important;
  min-width: 44px !important;
  display: grid !important;
  place-items: center !important;
  margin: 0 !important;
  padding: 0 !important;
  border: 2px solid #302a38 !important;
  border-radius: 50% !important;
  background: linear-gradient(135deg,#cba8b1,#b8a8c8) !important;
  color: #fff !important;
  box-shadow: 3px 3px 0 rgba(48,42,56,.18) !important;
  font-size: 17px !important;
  font-weight: 900 !important;
  line-height: 1 !important;
}

.home-music-v3-play:hover {
  transform: translate(-1px,-1px) !important;
}

.home-music-v3-play.is-playing {
  background: linear-gradient(135deg,#adbea9,#aebdca) !important;
}

.home-music-v3-player {
  display: none;
  border-top: 2px solid #302a38;
  background: #252128;
}

.home-music-v3-player.is-open {
  display: block;
}

.home-music-v3-ratio {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #111;
}

.home-music-v3-ratio iframe {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
}

.home-music-v3-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 11px;
  color: #f3edf3;
  font-size: 10px;
}

.home-music-v3-bottom a {
  color: #f3edf3 !important;
  text-decoration: underline !important;
  text-underline-offset: 3px;
}

@media (max-width:560px) {
  .home-music-v3-wrap {
    margin: 10px 10px 13px;
    border-radius: 16px;
  }

  .home-music-v3-row {
    grid-template-columns: 60px minmax(0,1fr) 42px;
    gap: 8px;
    padding: 9px;
  }

  .home-music-v3-thumb {
    width: 60px;
    height: 40px;
  }

  .home-music-v3-play {
    width: 40px !important;
    height: 40px !important;
    min-width: 40px !important;
  }
}
</style>

<script id="home-music-button-v3-script">
(() => {
  if (window.__homeMusicButtonV3) return;
  window.__homeMusicButtonV3 = true;

  const YT_GLOBAL = /(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/watch\?[^\s]*?v=|youtu\.be\/|youtube\.com\/shorts\/)([A-Za-z0-9_-]{11})/ig;
  const YT_ONE = /(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/watch\?[^\s]*?v=|youtu\.be\/|youtube\.com\/shorts\/)([A-Za-z0-9_-]{11})/i;

  function getCandidateBlocks() {
    const blocks = [];
    const seen = new Set();

    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          const text = node.nodeValue || "";
          if (
            text.includes("youtube.com/watch") ||
            text.includes("youtu.be/") ||
            text.includes("youtube.com/shorts/")
          ) {
            return NodeFilter.FILTER_ACCEPT;
          }
          return NodeFilter.FILTER_REJECT;
        }
      }
    );

    let node;
    while ((node = walker.nextNode())) {
      let el = node.parentElement;
      if (!el) continue;

      // Find the smallest nearby block that contains both the music marker
      // and the YouTube URL. This works even when the post card class changes.
      let chosen = el;
      for (let i = 0; i < 5 && el; i++, el = el.parentElement) {
        const text = el.innerText || el.textContent || "";
        if (text.includes("🎵") && YT_ONE.test(text)) {
          chosen = el;
          if (text.length < 700) break;
        }
      }

      if (chosen && !seen.has(chosen)) {
        seen.add(chosen);
        blocks.push(chosen);
      }
    }

    return blocks;
  }

  function parseMusic(block) {
    const text = block.innerText || block.textContent || "";
    const match = text.match(YT_ONE);
    if (!match) return null;

    const id = match[1];

    const urlMatch = text.match(/https?:\/\/[^\s]+(?:youtube\.com|youtu\.be)[^\s]*/i);
    let url = urlMatch
      ? urlMatch[0].replace(/[),.;]+$/, "")
      : `https://www.youtube.com/watch?v=${id}`;

    const lines = text
      .split(/\r?\n/)
      .map(v => v.trim())
      .filter(Boolean);

    let musicLine = lines.find(line => line.includes("🎵")) || "";
    musicLine = musicLine.replace(/^.*?🎵\s*/, "").trim();

    let title = musicLine || "この投稿の1曲";
    let artist = "YouTube";

    // Prefer the last em dash as artist separator.
    const emIndex = title.lastIndexOf(" — ");
    if (emIndex > 0) {
      artist = title.slice(emIndex + 3).trim() || "YouTube";
      title = title.slice(0, emIndex).trim() || "この投稿の1曲";
    }

    return { id, url, title, artist };
  }

  function closeOtherPlayers(except) {
    document.querySelectorAll(".home-music-v3-wrap").forEach(wrap => {
      if (wrap === except) return;

      const panel = wrap.querySelector(".home-music-v3-player");
      const iframe = wrap.querySelector("iframe");
      const button = wrap.querySelector(".home-music-v3-play");

      panel?.classList.remove("is-open");
      if (iframe) iframe.src = "";

      if (button) {
        button.classList.remove("is-playing");
        button.textContent = "▶";
        button.setAttribute("aria-label", "この投稿の音楽を再生");
      }
    });
  }

  function enhance(block) {
    if (block.dataset.homeMusicV3 === "1") return;

    const music = parseMusic(block);
    if (!music) return;

    block.dataset.homeMusicV3 = "1";

    const wrap = document.createElement("div");
    wrap.className = "home-music-v3-wrap";
    wrap.innerHTML = `
      <div class="home-music-v3-row">
        <img class="home-music-v3-thumb"
             src="https://i.ytimg.com/vi/${encodeURIComponent(music.id)}/mqdefault.jpg"
             alt="">
        <div class="home-music-v3-meta">
          <span class="home-music-v3-label">THIS POST'S SONG</span>
          <strong class="home-music-v3-title"></strong>
          <span class="home-music-v3-artist"></span>
        </div>
        <button type="button"
                class="home-music-v3-play"
                aria-label="この投稿の音楽を再生">▶</button>
      </div>
      <div class="home-music-v3-player">
        <div class="home-music-v3-ratio">
          <iframe
            title="YouTube player"
            src=""
            allow="autoplay; encrypted-media; picture-in-picture"
            referrerpolicy="strict-origin-when-cross-origin"
            allowfullscreen>
          </iframe>
        </div>
        <div class="home-music-v3-bottom">
          <span>この投稿の音楽</span>
          <a target="_blank" rel="noopener noreferrer">YouTubeで開く ↗</a>
        </div>
      </div>
    `;

    wrap.querySelector(".home-music-v3-title").textContent = music.title;
    wrap.querySelector(".home-music-v3-artist").textContent = music.artist;
    wrap.querySelector(".home-music-v3-bottom a").href = music.url;

    const button = wrap.querySelector(".home-music-v3-play");
    const panel = wrap.querySelector(".home-music-v3-player");
    const iframe = wrap.querySelector("iframe");

    button.addEventListener("click", () => {
      const opening = !panel.classList.contains("is-open");

      if (!opening) {
        panel.classList.remove("is-open");
        iframe.src = "";
        button.classList.remove("is-playing");
        button.textContent = "▶";
        button.setAttribute("aria-label", "この投稿の音楽を再生");
        return;
      }

      closeOtherPlayers(wrap);

      iframe.src =
        `https://www.youtube.com/embed/${encodeURIComponent(music.id)}` +
        "?autoplay=1&playsinline=1&rel=0";

      panel.classList.add("is-open");
      button.classList.add("is-playing");
      button.textContent = "■";
      button.setAttribute("aria-label", "音楽を停止");
    });

    // Put the player immediately after the raw music text.
    block.insertAdjacentElement("afterend", wrap);
  }

  let scheduled = false;

  function scan() {
    if (scheduled) return;
    scheduled = true;

    requestAnimationFrame(() => {
      scheduled = false;
      getCandidateBlocks().forEach(enhance);
    });
  }

  scan();

  const observer = new MutationObserver(scan);
  observer.observe(document.body, {
    childList: true,
    subtree: true
  });
})();
</script>
<!-- HOME_MUSIC_BUTTON_V3_END -->
'@

if ($html -match '</body>') {
    $html = $html -replace '</body>', ($patch + "`r`n</body>")
} else {
    $html += "`r`n" + $patch
}

[IO.File]::WriteAllText($homePath, $html, [Text.UTF8Encoding]::new($false))

Write-Host ''
Write-Host 'DONE' -ForegroundColor Green
Write-Host 'The home page now scans the actual YouTube URL text and adds a large play button directly below it.'
Write-Host ''
Write-Host 'Open http://localhost:8000 and press Ctrl+F5.' -ForegroundColor Yellow
Write-Host 'Docker rebuild is normally NOT required.' -ForegroundColor Yellow
