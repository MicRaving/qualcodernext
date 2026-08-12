# QCnext - compile script (Windows)
#
# Builds the complete distributable:
#   1. Backend: PyInstaller onefile exe (dist/qualcoder-backend.exe)
#   2. Desktop: Tauri release app + NSIS/MSI installers with the backend
#      bundled as a resource.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File compile.ps1
#   powershell -ExecutionPolicy Bypass -File compile.ps1 -SkipBackend   # rebuild only the Tauri app
#   powershell -ExecutionPolicy Bypass -File compile.ps1 -SkipTauri     # rebuild only the backend onedir
#
# Artifacts (after a successful run):
#   backend\dist\qualcoder-backend\          PyInstaller onedir (copy of the resource below)
#   frontend\src-tauri\resources\backend\    backend onedir bundled into the Tauri resources
#   frontend\src-tauri\target\release\qualcoder-tauri.exe
#   frontend\src-tauri\target\release\bundle\nsis\QualCoder_*-setup.exe
#   frontend\src-tauri\target\release\bundle\msi\QualCoder_*.msi
#
# Prerequisites: backend\.venv (Python 3.11 + PyInstaller), Node.js + npm,
# Rust + cargo (rustup), the Tauri signing key at updater.key (required for
# updater artifacts; if missing the build still succeeds without them).

param(
    [switch]$SkipBackend,
    [switch]$SkipTauri
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
# App version (the updater compares it against the manifest's version field).
$tauriVersion = (Get-Content (Join-Path $frontendDir "src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json).version

# --- PATH setup -----------------------------------------------------------
# rustup installs cargo to %USERPROFILE%\.cargo\bin; it may not be on the
# PATH of shells started before the install.
if ((Test-Path (Join-Path $cargoBin "cargo.exe")) -and ($env:PATH -notlike "*$cargoBin*")) {
    $env:PATH = "$cargoBin;$env:PATH"
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " QCnext - compile" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# --- 1/2 Backend ----------------------------------------------------------
if (-not $SkipBackend) {
    Write-Host "`n[1/2] Packaging the backend (PyInstaller onedir)..." -ForegroundColor Yellow
    if (-not (Test-Path $venvPython)) {
        throw "Backend venv not found at $venvPython - create it first (see backend\pyproject.toml)."
    }
    Push-Location $backendDir
    try {
        & $venvPython -m PyInstaller --noconfirm qualcoder_backend.spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)." }
    } finally {
        Pop-Location
    }
    $backendDirOut = Join-Path $backendDir "dist\qualcoder-backend"
    if (-not (Test-Path (Join-Path $backendDirOut "qualcoder-backend.exe"))) {
        throw "PyInstaller completed but $backendDirOut\qualcoder-backend.exe is missing."
    }
    # Ship the onedir as a Tauri resource so nothing is unpacked at launch.
    $resourceTarget = Join-Path $frontendDir "src-tauri\resources\backend"
    Write-Host "Copying backend onedir to $resourceTarget" -ForegroundColor Yellow
    if (Test-Path $resourceTarget) { Remove-Item $resourceTarget -Recurse -Force }
    New-Item -ItemType Directory -Path $resourceTarget -Force | Out-Null
    Copy-Item (Join-Path $backendDirOut "*") $resourceTarget -Recurse -Force
    Write-Host "Backend onedir: $backendDirOut" -ForegroundColor Green
} else {
    Write-Host "`n[1/2] Skipping backend packaging (-SkipBackend)." -ForegroundColor DarkGray
}

# --- 2/2 Tauri ------------------------------------------------------------
if (-not $SkipTauri) {
    Write-Host "`n[2/2] Building the Tauri app + installers..." -ForegroundColor Yellow

    # Updater artifacts must be signed; point the build at the private key.
    # Without the key (fresh checkout — updater.key is gitignored) the tauri
    # CLI refuses to bundle, so updater artifacts are temporarily disabled in
    # tauri.conf.json and restored afterwards (text-level patch to keep the
    # file byte-identical afterwards).
    $updaterKey = Join-Path $root "updater.key"
    $confPath = Join-Path $frontendDir "src-tauri\tauri.conf.json"
    $disableArtifacts = $false
    if (Test-Path $updaterKey) {
        $env:TAURI_SIGNING_PRIVATE_KEY_PATH = $updaterKey
        $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
        # The CLI checks the key CONTENT in TAURI_SIGNING_PRIVATE_KEY; set it
        # too so signing works regardless of which variable the CLI reads.
        try {
            $keyContent = (Get-Content $updaterKey -Raw).Trim()
            if ($keyContent) { $env:TAURI_SIGNING_PRIVATE_KEY = $keyContent }
        } catch {
            Write-Host "WARNING: could not read updater.key - signing may fail." -ForegroundColor DarkYellow
        }
        Write-Host "Updater signing key found - updater artifacts will be created." -ForegroundColor DarkGray
    } elseif ((Get-Content $confPath -Raw) -match '"createUpdaterArtifacts"\s*:\s*true') {
        Write-Host "WARNING: updater.key not found - building WITHOUT updater artifacts." -ForegroundColor DarkYellow
        (Get-Content $confPath -Raw) -replace '"createUpdaterArtifacts"\s*:\s*true', '"createUpdaterArtifacts": false' |
            Set-Content $confPath -Encoding utf8 -NoNewline
        $disableArtifacts = $true
    } else {
        Write-Host "WARNING: updater.key not found - updater artifacts are disabled." -ForegroundColor DarkYellow
    }

    Push-Location $frontendDir
    try {
        & npx --yes @tauri-apps/cli@2 build
        if ($LASTEXITCODE -ne 0) { throw "Tauri build failed (exit $LASTEXITCODE)." }
    } finally {
        Pop-Location
        if ($disableArtifacts) {
            # Restore the canonical config (updater artifacts on for anyone
            # who has the signing key).
            (Get-Content $confPath -Raw) -replace '"createUpdaterArtifacts"\s*:\s*false', '"createUpdaterArtifacts": true' |
                Set-Content $confPath -Encoding utf8 -NoNewline
        }
    }
} else {
    Write-Host "`n[2/2] Skipping Tauri build (-SkipTauri)." -ForegroundColor DarkGray
}

# --- Report ---------------------------------------------------------------
Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host " Build finished. Artifacts:" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
$report = @(
    (Join-Path $backendDir "dist\qualcoder-backend"),
    (Join-Path $frontendDir "src-tauri\resources\backend"),
    (Join-Path $frontendDir "src-tauri\target\release\qualcoder-tauri.exe"),
    (Join-Path $frontendDir "src-tauri\target\release\bundle\nsis"),
    (Join-Path $frontendDir "src-tauri\target\release\bundle\msi")
)
foreach ($path in $report) {
    if (Test-Path $path) { Write-Host "  $path" -ForegroundColor Green }
}

# --- Update manifest -------------------------------------------------------
# The static update manifest the app's updater endpoint points at
# (plugins.updater.endpoints). Upload it together with the installers and
# their .sig files to a GitHub release; the "latest" URL then always serves
# the newest build. Only emitted when signed updater artifacts exist.
Write-Host "`n[3/3] Generating the GitHub update manifest..." -ForegroundColor Yellow
$nsisDir = Join-Path $frontendDir "src-tauri\target\release\bundle\nsis"
$manifest = $null
$nsisExe = Get-ChildItem -Path $nsisDir -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -ne $nsisExe) {
    $sigFile = "$($nsisExe.FullName).sig"
    if (Test-Path $sigFile) {
        $signature = (Get-Content $sigFile -Raw).Trim()
        $name = [System.IO.Path]::GetFileName($nsisExe.FullName)
        $manifest = @{
            version  = $tauriVersion
            notes    = "QualCoder v$tauriVersion"
            pub_date = (Get-Date).ToUniversalTime().ToString("o")
            platforms = @{
                "windows-x86_64" = @{
                    signature = $signature
                    url       = "https://github.com/MicRaving/QCnext/releases/latest/download/$name"
                }
            }
        }
    }
}
if ($null -ne $manifest) {
    $manifestPath = Join-Path $nsisDir "qualcoder-latest.json"
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $manifestPath -Encoding utf8
    Write-Host "  $manifestPath" -ForegroundColor Green
} else {
    Write-Host "  skipped (no signed NSIS bundle found)" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "Run the app:  frontend\src-tauri\target\release\qualcoder-tauri.exe" -ForegroundColor White
Write-Host "Install:      the NSIS or MSI package from bundle\nsis or bundle\msi" -ForegroundColor White
Write-Host "Publish:      upload bundle\nsis\* , bundle\msi\* and qualcoder-latest.json to a GitHub release." -ForegroundColor White
