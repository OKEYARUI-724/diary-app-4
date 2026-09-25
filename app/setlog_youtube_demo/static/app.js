const postForm = document.getElementById("postForm");
const imageInput = document.getElementById("image");
const imagePreview = document.getElementById("imagePreview");
const previewWrap = document.getElementById("previewWrap");
const musicOverlay = document.getElementById("musicOverlay");
const musicQuery = document.getElementById("musicQuery");
const searchMusicButton = document.getElementById("searchMusic");
const musicResults = document.getElementById("musicResults");
const musicMessage = document.getElementById("musicMessage");
const clearMusicButton = document.getElementById("clearMusic");
const feed = document.getElementById("feed");
const playerModal = document.getElementById("playerModal");
const youtubePlayer = document.getElementById("youtubePlayer");
const closePlayerButton = document.getElementById("closePlayer");
const playerTitle = document.getElementById("playerTitle");
const openYouTube = document.getElementById("openYouTube");

let selectedVideo = null;
let currentPreviewUrl = null;

imageInput.addEventListener("change", () => {
  const file = imageInput.files?.[0];
  if (!file) return;

  if (currentPreviewUrl) URL.revokeObjectURL(currentPreviewUrl);
  currentPreviewUrl = URL.createObjectURL(file);
  imagePreview.src = currentPreviewUrl;
  previewWrap.classList.remove("hidden");
  renderSelectedMusic();
});

searchMusicButton.addEventListener("click", searchMusic);
musicQuery.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    searchMusic();
  }
});

clearMusicButton.addEventListener("click", () => {
  selectedVideo = null;
  clearMusicButton.classList.add("hidden");
  musicMessage.textContent = "音楽の選択を解除しました。";
  renderSelectedMusic();
});

closePlayerButton.addEventListener("click", closePlayer);
playerModal.addEventListener("click", (event) => {
  if (event.target === playerModal) closePlayer();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !playerModal.classList.contains("hidden")) {
    closePlayer();
  }
});

async function searchMusic() {
  const q = musicQuery.value.trim();
  if (!q) {
    musicMessage.textContent = "曲名かアーティスト名を入力してください。";
    return;
  }

  searchMusicButton.disabled = true;
  musicMessage.textContent = "YouTubeで検索中...";
  musicResults.innerHTML = "";

  try {
    const response = await fetch(`/api/music/search?q=${encodeURIComponent(q)}&limit=10`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "検索に失敗しました。");

    musicMessage.textContent = data.items.length
      ? `${data.items.length}件見つかりました。動画を確認して1曲選んでください。`
      : "見つかりませんでした。別の曲名やアーティスト名で試してください。";

    data.items.forEach((video) => {
      const row = document.createElement("div");
      row.className = "track";
      row.innerHTML = `
        ${video.cover_url ? `<img src="${escapeHtml(video.cover_url)}" alt="">` : `<div class="thumb-placeholder"></div>`}
        <div class="track-meta">
          <div class="track-title">${escapeHtml(video.title || "")}</div>
          <div class="track-artist">${escapeHtml(video.artist || "")}</div>
          <a class="track-link" href="${escapeHtml(video.external_url || "#")}" target="_blank" rel="noopener noreferrer">YouTubeで確認 ↗</a>
        </div>
        <button type="button">この曲を選ぶ</button>
      `;
      row.querySelector("button").addEventListener("click", () => {
        selectedVideo = video;
        musicMessage.textContent = `選択中：${decodeEntities(video.title || "")} — ${decodeEntities(video.artist || "")}`;
        clearMusicButton.classList.remove("hidden");
        renderSelectedMusic();
      });
      musicResults.appendChild(row);
    });
  } catch (error) {
    musicMessage.textContent = error.message;
  } finally {
    searchMusicButton.disabled = false;
  }
}

function renderSelectedMusic() {
  if (!selectedVideo || previewWrap.classList.contains("hidden")) {
    musicOverlay.classList.add("hidden");
    musicOverlay.innerHTML = "";
    return;
  }

  musicOverlay.classList.remove("hidden");
  musicOverlay.innerHTML = `
    ${selectedVideo.cover_url ? `<img src="${escapeHtml(selectedVideo.cover_url)}" alt="">` : ""}
    <div class="meta">
      <div class="title">▶ ${escapeHtml(decodeEntities(selectedVideo.title || ""))}</div>
      <div class="artist">${escapeHtml(decodeEntities(selectedVideo.artist || ""))} · YouTube</div>
    </div>
  `;
}

postForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = postForm.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  submitButton.textContent = "投稿中...";

  try {
    const formData = new FormData(postForm);
    if (selectedVideo) {
      formData.append("youtube_video_id", selectedVideo.youtube_video_id || "");
    }

    const response = await fetch("/api/posts", { method: "POST", body: formData });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "投稿に失敗しました。");

    postForm.reset();
    selectedVideo = null;
    previewWrap.classList.add("hidden");
    musicOverlay.classList.add("hidden");
    musicResults.innerHTML = "";
    clearMusicButton.classList.add("hidden");
    musicMessage.textContent = "投稿しました。次の思い出にも音楽を付けられます。";
    if (currentPreviewUrl) {
      URL.revokeObjectURL(currentPreviewUrl);
      currentPreviewUrl = null;
    }
    await loadPosts();
  } catch (error) {
    alert(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "投稿する";
  }
});

async function loadPosts() {
  try {
    const response = await fetch("/api/posts");
    const posts = await response.json();
    if (!response.ok) throw new Error(posts.detail || "投稿の取得に失敗しました。");

    feed.innerHTML = "";

    if (!posts.length) {
      feed.innerHTML = '<div class="empty">まだ投稿がありません。最初の1枚を残してみよう。</div>';
      return;
    }

    posts.forEach((post) => {
      const article = document.createElement("article");
      article.className = "post";
      const music = post.music;
      const musicMarkup = music ? `
        <button
          type="button"
          class="music-overlay music-play-button"
          data-video-id="${escapeHtml(music.youtube_video_id || "")}"
          data-title="${escapeHtml(music.title || "")}"
          data-url="${escapeHtml(music.external_url || "")}">
          ${music.cover_url ? `<img src="${escapeHtml(music.cover_url)}" alt="">` : ""}
          <span class="meta">
            <span class="title">▶ ${escapeHtml(decodeEntities(music.title || ""))}</span>
            <span class="artist">${escapeHtml(decodeEntities(music.artist || ""))} · YouTube</span>
          </span>
        </button>` : "";

      article.innerHTML = `
        <div class="post-image-wrap">
          <img class="post-image" src="${escapeHtml(post.image_url)}" alt="投稿画像">
          ${musicMarkup}
        </div>
        <div class="post-body">
          ${post.caption ? `<p class="post-caption">${escapeHtml(post.caption)}</p>` : ""}
          <p class="post-date">${formatDate(post.created_at)}</p>
        </div>
      `;

      const playButton = article.querySelector(".music-play-button");
      if (playButton) {
        playButton.addEventListener("click", () => {
          openPlayer(
            playButton.dataset.videoId,
            decodeEntities(playButton.dataset.title || "YouTube"),
            playButton.dataset.url
          );
        });
      }

      feed.appendChild(article);
    });
  } catch (error) {
    feed.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

function openPlayer(videoId, title, externalUrl) {
  if (!/^[A-Za-z0-9_-]{11}$/.test(videoId || "")) return;
  playerTitle.textContent = title || "YouTubeで再生";
  youtubePlayer.src = `https://www.youtube.com/embed/${encodeURIComponent(videoId)}?autoplay=1&rel=0`;
  openYouTube.href = externalUrl || `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`;
  playerModal.classList.remove("hidden");
  document.body.classList.add("modal-open");
}

function closePlayer() {
  youtubePlayer.src = "";
  playerModal.classList.add("hidden");
  document.body.classList.remove("modal-open");
}

function formatDate(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
  }).format(new Date(value));
}

function decodeEntities(value) {
  const textarea = document.createElement("textarea");
  textarea.innerHTML = String(value ?? "");
  return textarea.value;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

loadPosts();
