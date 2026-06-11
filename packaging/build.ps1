# Build the Maknassa desktop app (Windows): Electron shell + frozen Python backend.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Output: dist\Maknassa-Setup.exe (NSIS installer via electron-builder)
$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = Split-Path -Parent $Here
Set-Location $Repo

Write-Host ">> Installing the app and build deps"
python -m pip install -e ".[build]"

Write-Host ">> Installing Chromium into the bundle ($Here\ms-playwright)"
$env:PLAYWRIGHT_BROWSERS_PATH = "$Here\ms-playwright"
python -m playwright install chromium

Write-Host ">> Freezing the backend with PyInstaller"
python -m PyInstaller --noconfirm --clean packaging\backend.spec

Write-Host ">> Building the Electron app"
Set-Location "$Repo\app"
npm ci
npm run build
npx electron-builder --win nsis --publish never

Copy-Item "$Repo\dist\electron\Maknassa-Setup.exe" "$Repo\dist\Maknassa-Setup.exe" -Force
Write-Host ">> Done: $Repo\dist\Maknassa-Setup.exe"
