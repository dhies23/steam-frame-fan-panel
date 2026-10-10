# sf.ps1 - run a local bash script on the Steam Frame devkit (ssh alias: frame).
#
#   .\sf.ps1 <script.sh>      run a local .sh file on the device
#   .\sf.ps1 -                read the script from stdin
#
# Notes:
#   * Windows PowerShell 5.1 normalizes newlines to CRLF when piping text to a
#     native command, which makes remote bash choke on stray '\r'. So we
#     normalize to LF ourselves and hand the file to ssh via cmd's stdin
#     redirection instead of the PowerShell pipeline.
#   * Run with: powershell -NoProfile -ExecutionPolicy Bypass -File .\sf.ps1 x.sh
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Script
)

$ErrorActionPreference = 'Stop'

if ($Script -eq '-') {
    $text = [Console]::In.ReadToEnd()
} else {
    $text = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $Script).Path)
}

$text = $text -replace "`r`n", "`n"

$tmp = Join-Path $env:TEMP ("sf_" + [guid]::NewGuid().ToString('N') + ".sh")
[System.IO.File]::WriteAllText($tmp, $text, (New-Object System.Text.UTF8Encoding($false)))

try {
    cmd /c "ssh -o BatchMode=yes -o ConnectTimeout=10 frame bash -s < `"$tmp`""
    exit $LASTEXITCODE
}
finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}
