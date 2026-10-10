# render.ps1 - render a local HTML file to PNG with headless Chrome.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\render.ps1 `
#       -Html shots\preview.html -Out shots\preview.png -Width 380 -Height 520
param(
    [Parameter(Mandatory = $true)][string]$Html,
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$Width = 380,
    [int]$Height = 520,
    [int]$Scale = 2
)

$ErrorActionPreference = 'Stop'

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) {
    $chrome = "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
}
if (-not (Test-Path $chrome)) { throw "chrome.exe not found" }

$htmlPath = (Resolve-Path -LiteralPath $Html).Path
$outPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Out))
$outDir = Split-Path -Parent $outPath
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
if (Test-Path $outPath) { Remove-Item -LiteralPath $outPath -Force }

$url = "file:///" + ($htmlPath -replace '\\', '/')
$profile = Join-Path $env:TEMP ("chrome-shot-" + [guid]::NewGuid().ToString('N'))

& $chrome --headless=new --disable-gpu --hide-scrollbars --no-first-run `
    --no-default-browser-check --force-device-scale-factor=$Scale `
    --user-data-dir="$profile" --window-size="$Width,$Height" `
    --virtual-time-budget=6000 --screenshot="$outPath" $url 2>$null | Out-Null

Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Path $outPath) {
    "OK $((Get-Item $outPath).Length) bytes -> $outPath"
} else {
    throw "screenshot failed"
}
