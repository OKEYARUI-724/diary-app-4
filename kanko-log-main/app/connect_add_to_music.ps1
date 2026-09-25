$ErrorActionPreference = 'Stop'

Write-Host 'Travel Log: connect +ADD to music post screen' -ForegroundColor Cyan

$root = (Get-Location).Path
$homePath = Join-Path $root 'static\index.html'
$addPath  = Join-Path $root 'static\add.html'
$backupPath = Join-Path $root 'static\index.before-add-link.html'

if (-not (Test-Path $homePath)) {
  Write-Host 'ERROR: static\index.html was not found. Run this from kanko-log-main.' -ForegroundColor Red
  exit 1
}

if (-not (Test-Path $addPath)) {
  Write-Host 'ERROR: static\add.html was not found. The music post screen must exist first.' -ForegroundColor Red
  exit 1
}

if (-not (Test-Path $backupPath)) {
  Copy-Item $homePath $backupPath
  Write-Host 'OK: backup created: static\index.before-add-link.html' -ForegroundColor Green
}

$html = Get-Content $homePath -Raw -Encoding UTF8
$marker = 'MUSIC_ADD_REDIRECT_PATCH_V2'

if ($html.Contains($marker)) {
  Write-Host 'OK: +ADD is already connected to the music post screen.' -ForegroundColor Green
  exit 0
}

$patch = @'
<!-- MUSIC_ADD_REDIRECT_PATCH_V2 -->
<script>
(() => {
  const MUSIC_POST_URL = "/static/add.html";

  document.addEventListener("click", (event) => {
    const target = event.target.closest("button, a");
    if (!target) return;

    const text = (target.textContent || "")
      .replace(/\s+/g, "")
      .toUpperCase();

    const id = (target.id || "").toLowerCase();
    const aria = (target.getAttribute("aria-label") || "").toLowerCase();
    const title = (target.getAttribute("title") || "").toLowerCase();

    const isAddButton =
      text === "+" ||
      text === "+ADD" ||
      text === "ADD" ||
      id === "addbtn" ||
      id === "addbutton" ||
      aria === "add" ||
      aria.includes("add log") ||
      title === "add" ||
      title.includes("add log");

    if (!isAddButton) return;

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    window.location.assign(MUSIC_POST_URL);
  }, true);
})();
</script>
'@

if ($html -match '</body>') {
  $html = $html -replace '</body>', ($patch + "`r`n</body>")
} else {
  $html = $html + "`r`n" + $patch
}

Set-Content -Path $homePath -Value $html -Encoding UTF8

Write-Host 'OK: right-top +ADD now opens static/add.html' -ForegroundColor Green
Write-Host 'Home:      http://localhost:8000' -ForegroundColor Cyan
Write-Host 'Music ADD: http://localhost:8000/static/add.html' -ForegroundColor Cyan
Write-Host 'Reload the browser with Ctrl+F5.' -ForegroundColor Yellow
