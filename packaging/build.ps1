# Build the Maknassa desktop app (Windows).
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Output: dist\maknassa\  (run dist\maknassa\maknassa-gui.exe)
$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = Split-Path -Parent $Here
Set-Location $Repo

Write-Host ">> Installing the app and build deps"
python -m pip install -e ".[build]"

Write-Host ">> Installing Chromium into the bundle ($Here\ms-playwright)"
$env:PLAYWRIGHT_BROWSERS_PATH = "$Here\ms-playwright"
python -m playwright install chromium

Write-Host ">> Freezing with PyInstaller"
python -m PyInstaller --noconfirm --clean packaging\maknassa.spec

Write-Host ">> Done. Launch: dist\maknassa\maknassa-gui.exe"
