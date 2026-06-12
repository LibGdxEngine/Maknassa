# Build the Maknassa desktop app (Windows): Electron shell + frozen Python backend.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Output: dist\Maknassa-Setup.exe (NSIS installer via electron-builder)
$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = Split-Path -Parent $Here
Set-Location $Repo

function Assert-FileExists($Path, $Description) {
	if (-not (Test-Path $Path -PathType Leaf)) {
		throw "$Description missing: $Path"
	}
}

function Invoke-BackendSmokeTest($BackendExe) {
	Write-Host ">> Smoke-testing frozen backend handshake"
	$SmokeDir = Join-Path ([System.IO.Path]::GetTempPath()) ("maknassa-backend-smoke-" + [System.Guid]::NewGuid().ToString("N"))
	New-Item -ItemType Directory -Force -Path $SmokeDir | Out-Null

	$psi = New-Object System.Diagnostics.ProcessStartInfo
	$psi.FileName = $BackendExe
	$psi.Arguments = "--parent-pid $PID"
	$psi.UseShellExecute = $false
	$psi.RedirectStandardOutput = $true
	$psi.RedirectStandardError = $true
	$psi.CreateNoWindow = $true
	$psi.EnvironmentVariables["MAKNASSA_BACKEND_TOKEN"] = "build-smoke-token"
	$psi.EnvironmentVariables["MAKNASSA_DATA_DIR"] = $SmokeDir

	$proc = New-Object System.Diagnostics.Process
	$proc.StartInfo = $psi
	$handshake = @{}
	$started = $false

	try {
		$started = $proc.Start()
		if (-not $started) {
			throw "Failed to start backend smoke test process"
		}

		$readTask = $proc.StandardOutput.ReadLineAsync()
		$deadline = [DateTime]::UtcNow.AddSeconds(25)
		while ($handshake.Count -lt 2 -and [DateTime]::UtcNow -lt $deadline) {
			if ($readTask.Wait(250)) {
				$line = $readTask.Result
				if ($null -eq $line) {
					break
				}
				Write-Host "   $line"
				if ($line.StartsWith("MAKNASSA_BACKEND_") -and $line.Contains("=")) {
					$equals = $line.IndexOf("=")
					$key = $line.Substring(0, $equals)
					$value = $line.Substring($equals + 1)
					$handshake[$key] = $value
				}
				$readTask = $proc.StandardOutput.ReadLineAsync()
			} elseif ($proc.HasExited) {
				break
			}
		}
	} finally {
		if ($started -and -not $proc.HasExited) {
			$proc.Kill()
			$proc.WaitForExit(5000) | Out-Null
		}
		if (Test-Path $SmokeDir) {
			Remove-Item $SmokeDir -Recurse -Force
		}
	}

	$stderr = if ($started) { $proc.StandardError.ReadToEnd() } else { "" }
	if (-not $handshake.ContainsKey("MAKNASSA_BACKEND_PORT") -or $handshake["MAKNASSA_BACKEND_TOKEN"] -ne "build-smoke-token") {
		throw "Frozen backend did not emit a valid handshake. Stderr:`n$stderr"
	}
}

Write-Host ">> Installing the app and build deps"
python -m pip install -e ".[build]"

Write-Host ">> Installing Chromium into the bundle ($Here\ms-playwright)"
$env:PLAYWRIGHT_BROWSERS_PATH = "$Here\ms-playwright"
python -m playwright install chromium

Write-Host ">> Freezing the backend with PyInstaller"
python -m PyInstaller --noconfirm --clean packaging\backend.spec
$BackendExe = Join-Path $Repo "dist\maknassa-backend\maknassa-backend.exe"
Assert-FileExists $BackendExe "Frozen backend executable"
Invoke-BackendSmokeTest $BackendExe

Write-Host ">> Building the Electron app"
Set-Location "$Repo\app"
npm.cmd ci
npm.cmd run build
$MainBundle = Join-Path $Repo "app\out\main\index.js"
$PreloadBundle = Join-Path $Repo "app\out\preload\index.js"
$RendererHtml = Join-Path $Repo "app\out\renderer\index.html"
Assert-FileExists $MainBundle "Electron main bundle"
Assert-FileExists $PreloadBundle "Electron preload bundle"
Assert-FileExists $RendererHtml "Renderer HTML"
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
npx.cmd electron-builder --win nsis --publish never

$UnpackedBackendExe = Join-Path $Repo "dist\electron\win-unpacked\resources\backend\maknassa-backend.exe"
$Installer = Join-Path $Repo "dist\electron\Maknassa-Setup.exe"
Assert-FileExists $UnpackedBackendExe "Packaged Electron backend resource"
Assert-FileExists $Installer "Electron installer"

Copy-Item $Installer "$Repo\dist\Maknassa-Setup.exe" -Force
Write-Host ">> Done: $Repo\dist\Maknassa-Setup.exe"
