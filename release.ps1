# QCnext - unified release pipeline (compile + release)
#
# Versioning: Bugfixes bump 0.0.1 (e.g. 0.1.0 → 0.1.1), only major new
# features justify a 0.1 bump (e.g. 0.1.x → 0.2.0), and +1.0 releases are
# manually administered by the owner.
#
# Single script that REPLACES the old compile.ps1 + release.ps1 +
# release-all.ps1. Compile and release can be run together (default) or
# separately:
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File release.ps1                     # compile + release (patch bump)
#   powershell -ExecutionPolicy Bypass -File release.ps1 -Compile             # build artifacts only (no version bump, no git ops)
#   powershell -ExecutionPolicy Bypass -File release.ps1 -ReleaseOnly         # release only (no compile; uses existing artifacts)
#   powershell -ExecutionPolicy Bypass -File release.ps1 -Bump minor          # minor version bump
#   powershell -ExecutionPolicy Bypass -File release.ps1 -Version 1.2.3       # explicit version
#   powershell -ExecutionPolicy Bypass -File release.ps1 -SkipBackend         # compile step: rebuild only the Tauri app
#   powershell -ExecutionPolicy Bypass -File release.ps1 -SkipTauri           # compile step: rebuild only the backend onedir
#   powershell -ExecutionPolicy Bypass -File release.ps1 -NoRelease           # compile + tag + push, but no GitHub release
#   powershell -ExecutionPolicy Bypass -File release.ps1 -DryRun              # preview everything, change nothing
#   powershell -ExecutionPolicy Bypass -File release.ps1 -ForceTag            # replace an existing tag of the same name
#
# Compile step:
#   1. Backend: PyInstaller onedir (dist/qualcoder-backend.exe) copied into
#      src-tauri/resources/backend.
#   2. Desktop: Tauri release build (portable qcnext.exe, NSIS setup, MSI) +
#      the signed update manifest (qcnext-latest.json).
#
# Release step:
#   1. Preflight (clean tree, gh auth unless -NoRelease)
#   2. Compute the next version (semver bump or explicit)
#   3. Build a changelog from git log since the last tag
#   4. Bump version in tauri.conf.json + append the CHANGELOG.md section
#   5. Commit "chore(release): vX.Y.Z"
#   6. Compile (unless -ReleaseOnly or -DryRun)
#   7. Tag + force push main + the tag
#   8. `gh release create` with the changelog as release notes and the
#      GENERATED ARTIFACTS attached: portable qcnext.exe, NSIS setup + .sig,
#      and the update manifest (qcnext-latest.json). The MSI is never uploaded.
#
# Prerequisites:
#   - backend/.venv (for the compile step)
#   - Node.js + npm, Rust + cargo (for the compile step)
#   - GitHub CLI (`gh`) authenticated - only needed when creating a release
#   - git configured with push access to origin/main

param(
    [ValidateSet("patch", "minor", "major")]
    [string]$Bump = "patch",
    [string]$Version,          # explicit version overrides -Bump
    [switch]$Compile,          # compile only (no version bump, no git ops)
    [switch]$ReleaseOnly,      # release only (no compile, uses existing artifacts)
    [switch]$SkipBackend,      # compile step: skip the PyInstaller onedir
    [switch]$SkipTauri,        # compile step: skip the Tauri build
    [switch]$NoRelease,        # release step: tag + push but no GitHub release
    [switch]$NoBump,           # version already bumped (manual) - release at the current version
    [switch]$AutoCommit,       # commit all uncommitted source changes first
    [switch]$DryRun,           # preview everything, change nothing
    [switch]$ForceTag          # replace an existing tag of the same name
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
$confPath = Join-Path $frontendDir "src-tauri\tauri.conf.json"
$changelogPath = Join-Path $root "CHANGELOG.md"
$repoSlug = "MicRaving/qualcodernext"

# Mode resolution: default = full pipeline; -Compile and -ReleaseOnly select
# one half (-Compile wins if both are given).
$doCompile = -not $ReleaseOnly
$doRelease = -not $Compile

# --- Helpers ----------------------------------------------------------------
function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !   $msg" -ForegroundColor DarkYellow }
function Fail($msg) { Write-Host "    X   $msg" -ForegroundColor Red; throw $msg }

function Invoke-OrDryRun {
    param([scriptblock]$action, [string]$description)
    if ($DryRun) {
        Write-Host "    [dry-run] $description" -ForegroundColor DarkGray
        return
    }
    & $action
}

# --- Header -----------------------------------------------------------------
Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " QCnext - release pipeline" -ForegroundColor Cyan
if ($DryRun) { Write-Host " *** DRY RUN - no changes will be made ***" -ForegroundColor Magenta }
if ($doCompile -and $doRelease)   { Write-Host " Mode: compile + release" -ForegroundColor White }
elseif ($doCompile)                { Write-Host " Mode: compile only" -ForegroundColor White }
else                               { Write-Host " Mode: release only" -ForegroundColor White }
Write-Host "=============================================" -ForegroundColor Cyan

# =============================================================================
# PART A - COMPILE (backend onedir + Tauri app + update manifest)
# =============================================================================
if ($doCompile) {
    Step "A/2  Compile (PyInstaller + Tauri)"

    if ($DryRun) {
        Write-Host "    [dry-run] Would run the compile steps (backend onedir + Tauri build)." -ForegroundColor DarkGray
        Ok "Compile skipped in dry-run"
    } else {
        # --- PATH setup (rustup's cargo may not be on the PATH) -------------
        if ((Test-Path (Join-Path $cargoBin "cargo.exe")) -and ($env:PATH -notlike "*$cargoBin*")) {
            $env:PATH = "$cargoBin;$env:PATH"
        }

        # --- 1/2 Backend -----------------------------------------------------
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

        # --- 2/2 Tauri -------------------------------------------------------
        if (-not $SkipTauri) {
            Write-Host "`n[2/2] Building the Tauri app + installers..." -ForegroundColor Yellow

            # Updater artifacts must be signed; point the build at the private key.
            # Without the key (fresh checkout - updater.key is gitignored) the
            # tauri CLI refuses to bundle, so updater artifacts are temporarily
            # disabled in tauri.conf.json and restored afterwards.
            $updaterKey = Join-Path $root "updater.key"
            $disableArtifacts = $false
            if (Test-Path $updaterKey) {
                $env:TAURI_SIGNING_PRIVATE_KEY_PATH = $updaterKey
                $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
                try {
                    $keyContent = (Get-Content $updaterKey -Raw).Trim()
                    if ($keyContent) { $env:TAURI_SIGNING_PRIVATE_KEY = $keyContent }
                } catch {
                    Warn "could not read updater.key - signing may fail."
                }
                Write-Host "Updater signing key found - updater artifacts will be created." -ForegroundColor DarkGray
            } elseif ((Get-Content $confPath -Raw) -match '"createUpdaterArtifacts"\s*:\s*true') {
                Warn "updater.key not found - building WITHOUT updater artifacts."
                (Get-Content $confPath -Raw) -replace '"createUpdaterArtifacts"\s*:\s*true', '"createUpdaterArtifacts": false' |
                    Set-Content $confPath -Encoding utf8 -NoNewline
                $disableArtifacts = $true
            } else {
                Warn "updater.key not found - updater artifacts are disabled."
            }

            Push-Location $frontendDir
            try {
                & npx --yes @tauri-apps/cli@2 build
                if ($LASTEXITCODE -ne 0) { throw "Tauri build failed (exit $LASTEXITCODE)." }
            } finally {
                Pop-Location
                if ($disableArtifacts) {
                    (Get-Content $confPath -Raw) -replace '"createUpdaterArtifacts"\s*:\s*false', '"createUpdaterArtifacts": true' |
                        Set-Content $confPath -Encoding utf8 -NoNewline
                }
            }
        } else {
            Write-Host "`n[2/2] Skipping Tauri build (-SkipTauri)." -ForegroundColor DarkGray
        }

        # --- Report ----------------------------------------------------------
        Write-Host "`n==========================================" -ForegroundColor Cyan
        Write-Host " Compile finished. Artifacts:" -ForegroundColor Cyan
        Write-Host "==========================================" -ForegroundColor Cyan
        $report = @(
            (Join-Path $backendDir "dist\qualcoder-backend"),
            (Join-Path $frontendDir "src-tauri\resources\backend"),
            (Join-Path $frontendDir "src-tauri\target\release\qcnext.exe"),
            (Join-Path $frontendDir "src-tauri\target\release\bundle\nsis"),
            (Join-Path $frontendDir "src-tauri\target\release\bundle\msi")
        )
        foreach ($path in $report) {
            if (Test-Path $path) { Write-Host "  $path" -ForegroundColor Green }
        }

        # --- Update manifest ---------------------------------------------------
        # The static manifest the app's updater endpoint points at
        # (plugins.updater.endpoints). Only emitted when signed artifacts exist.
        Write-Host "`n[3/3] Generating the GitHub update manifest..." -ForegroundColor Yellow
        $tauriVersion = (Get-Content $confPath -Raw | ConvertFrom-Json).version
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
                    notes    = "QCnext v$tauriVersion"
                    pub_date = (Get-Date).ToUniversalTime().ToString("o")
                    platforms = @{
                        "windows-x86_64" = @{
                            signature = $signature
                            url       = "https://github.com/$repoSlug/releases/latest/download/$name"
                        }
                    }
                }
            }
        }
        if ($null -ne $manifest) {
            $manifestPath = Join-Path $nsisDir "qcnext-latest.json"
            $manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $manifestPath -Encoding utf8
            Write-Host "  $manifestPath" -ForegroundColor Green
        } else {
            Write-Host "  skipped (no signed NSIS bundle found)" -ForegroundColor DarkYellow
        }
    }
} else {
    Step "A/2  Compile"
    Ok "Skipped (-ReleaseOnly)"
}

# =============================================================================
# PART B - RELEASE (preflight, version, changelog, tag, push, GitHub release)
# =============================================================================
if ($doRelease) {
    # --- B0. Optional auto-commit of uncommitted source changes ---------------
    if ($AutoCommit) {
        Step "B0/6  Auto-commit source changes (-AutoCommit)"
        if (-not $DryRun) {
            # Untrack compiled backend artifacts if still in the index (they
            # are regenerated by the compile step; committed on demand only).
            $tracked = git ls-files --cached -- frontend/src-tauri/resources/backend/ 2>$null
            if ($tracked) {
                git rm --cached -r frontend/src-tauri/resources/backend/ | Out-Null
                Ok "Removed compiled artifacts from the git index (files kept on disk)"
            }
            git add -A | Out-Null
            $dirty = git diff --cached --name-only
            if ($dirty) {
                $dirs = @{}
                foreach ($f in $dirty) {
                    $top = ($f -split '/')[0]
                    if (-not $dirs.ContainsKey($top)) { $dirs[$top] = 0 }
                    $dirs[$top]++
                }
                $summary = ($dirs.GetEnumerator() | ForEach-Object { "$($_.Key)($($_.Value))" }) -join " "
                $msg = "chore: release prep ($summary)"
                git commit -m $msg --no-verify | Out-Null
                Ok "Committed: $msg ($($dirty.Count) files)"
            } else {
                Ok "Nothing to commit"
            }
        } else {
            Ok "[dry-run] Would commit all uncommitted changes"
        }
    }

    # --- B1. Preflight --------------------------------------------------------
    Step "B1/6  Preflight checks"

    $dirty = git status --porcelain | Where-Object { $_ -notmatch '^\?\?' }
    if ($dirty) {
        Warn "Working tree has uncommitted changes. Commit or stash them first:"
        $dirty | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
        Fail "Cannot release with a dirty working tree."
    }
    Ok "Working tree clean"

    $branch = git branch --show-current
    if ($branch -ne "main") {
        Warn "On branch '$branch' - releases should usually come from main."
    }
    Ok "Branch: $branch"

    if (-not $NoRelease -and -not $DryRun) {
        $ghPath = Get-Command gh -ErrorAction SilentlyContinue
        if (-not $ghPath) { Fail "GitHub CLI (gh) not found. Install from https://cli.github.com/ or pass -NoRelease." }
        $ghAuth = gh auth status 2>&1
        if ($LASTEXITCODE -ne 0) { Fail "GitHub CLI not authenticated. Run 'gh auth login' first." }
        Ok "gh CLI authenticated"
    } else {
        Ok "gh check skipped (NoRelease or DryRun)"
    }

    # --- B2. Determine the next version ---------------------------------------
    Step "B2/6  Determine version"

    $conf = Get-Content $confPath -Raw | ConvertFrom-Json
    $currentVersion = $conf.version
    Ok "Current version: $currentVersion"

    if ($NoBump) {
        $newVersion = $currentVersion
        Ok "NoBump: releasing the current version $newVersion as-is"
    } elseif ($Version) {
        $newVersion = $Version
    } else {
        $parts = $currentVersion -split '\.'
        if ($parts.Length -ne 3) {
            Fail "Cannot parse version '$currentVersion' - expected MAJOR.MINOR.PATCH."
        }
        $major = [int]$parts[0]; $minor = [int]$parts[1]; $patch = [int]$parts[2]
        switch ($Bump) {
            "major" { $major++; $minor = 0; $patch = 0 }
            "minor" { $minor++; $patch = 0 }
            "patch" { $patch++ }
        }
        $newVersion = "$major.$minor.$patch"
    }

    if (-not $NoBump -and $newVersion -eq $currentVersion) {
        Fail "New version ($newVersion) equals current. Use -Bump, -Version or -NoBump."
    }
    Ok "New version: $newVersion (was $currentVersion)"

    # Existing tag? Releasing over it requires -ForceTag (e.g. when the
    # version history was reset and an old tag of the same name exists).
    $tagExists = (& git rev-parse -q --verify "refs/tags/v$newVersion" 2>$null) -and ($LASTEXITCODE -eq 0)
    if ($tagExists -and -not $ForceTag) {
        Fail "Tag v$newVersion already exists. Pass -ForceTag to replace it (and its remote counterpart) - this is destructive."
    }

    # --- B3. Build the changelog since the last tag --------------------------
    Step "B3/6  Generate changelog"

    $lastTag = $null
    $null = git describe --tags --abbrev=0 2>$null
    if ($LASTEXITCODE -eq 0) {
        $lastTag = (git describe --tags --abbrev=0).Trim()
    }
    if ($lastTag) {
        $commitRange = "$lastTag..HEAD"
        $tagDate = (git log -1 --format=%ai $lastTag).Trim()
        if ($tagDate.Length -ge 10) { $tagDate = $tagDate.Substring(0, 10) }
        Ok "Last tag: $lastTag ($tagDate)"
    } else {
        Warn "No tags found - changelog will include all commits."
        $commitRange = "HEAD"
    }

    $commits = @()
    foreach ($line in (& git log $commitRange --pretty=format:"%s|%h" --no-merges 2>$null)) {
        if ($line) { $commits += $line }
    }
    $commitCount = $commits.Count

    # The changelog stays SHORT: a one-line pointer plus the compare link.
    # GitHub lists every commit behind that link, so the section never
    # duplicates the detailed list. Edit it afterwards to add real
    # one-liners ("Improved animations.") when wanted.
    if ($lastTag) { $compareFrom = $lastTag } else { $compareFrom = "v0.0.0" }
    $body = "- See the full changelog below for a complete list of changes.`n`n**Full Changelog**: https://github.com/$repoSlug/compare/$compareFrom...v$newVersion"

    if ($lastTag) { Ok "Changelog ready: $commitCount commits since $lastTag (brief section)" }
    else { Ok "Changelog ready: $commitCount commits (no previous tag, brief section)" }

    # --- B4. Bump version + append the CHANGELOG section ---------------------
    Step "B4/6  Bump version + record changelog"

    if ($NoBump) {
        Ok "NoBump: version + changelog already set - skipping the bump"
    } else {
        Invoke-OrDryRun {
            $raw = Get-Content $confPath -Raw
            $pattern = '"version"\s*:\s*"' + [regex]::Escape($currentVersion) + '"'
            $replacement = '"version": "' + $newVersion + '"'
            $patched = $raw -replace $pattern, $replacement
            if ($patched -eq $raw) { Fail "Version pattern not found in $confPath" }
            Set-Content $confPath $patched -Encoding utf8 -NoNewline
            Ok "tauri.conf.json version set to $newVersion"
        } "Would set tauri.conf.json version to $newVersion"

        Invoke-OrDryRun {
            if (Test-Path $changelogPath) {
                # Append the release section at the END of CHANGELOG.md so the
                # manual "Summary" + "Full changelog" stay on top.
                $today = (Get-Date).ToString("yyyy-MM-dd")
                $section = "`n---`n## v$newVersion ($today)`n`n$body`n"
                Add-Content $changelogPath $section -Encoding UTF8
                Ok "CHANGELOG.md appended with v$newVersion section"
            } else {
                Warn "CHANGELOG.md not found - skipped"
            }
        } "Would append the v$newVersion changelog to CHANGELOG.md"
    }

    # --- B5. Commit + tag ----------------------------------------------------
    Step "B5/6  Commit version bump + create tag"

    Invoke-OrDryRun {
        git add $confPath
        if (Test-Path $changelogPath) { git add $changelogPath }
        $staged = git diff --cached --name-only
        if ($staged) {
            git commit -m "chore(release): v$newVersion" | Out-Null
            Ok "Committed 'chore(release): v$newVersion'"
        } else {
            Ok "Nothing to commit (version + changelog already committed)"
        }
    } "Would commit 'chore(release): v$newVersion' (if anything is staged)"

    Invoke-OrDryRun {
        if ($tagExists) {
            git tag -d "v$newVersion" | Out-Null
            Warn "Deleted the existing local tag v$newVersion (recreated below)."
        }
        git tag -a "v$newVersion" -m "Release v$newVersion"
        Ok "Created annotated tag v$newVersion"
    } "Would create annotated tag v$newVersion"

    # --- B6. Force push + GitHub release -------------------------------------
    Step "B6/6  Force push to origin + create GitHub Release"

    Invoke-OrDryRun {
        git push --force origin main | Out-Null
        if ($tagExists) {
            # A replaced tag needs the old remote one deleted first.
            git push origin ":refs/tags/v$newVersion" | Out-Null
        }
        git push origin "v$newVersion" | Out-Null
        Ok "Pushed main + tag v$newVersion to origin"
    } "Would force-push main and push tag v$newVersion"

    if (-not $NoRelease) {
        $nsisDir = Join-Path $frontendDir "src-tauri\target\release\bundle\nsis"
        $assets = @()

        # Generated artifacts (never the MSI - see AGENTS.md).
        $portable = Join-Path $frontendDir "src-tauri\target\release\qcnext.exe"
        if (Test-Path $portable) {
            $assets += $portable
            Ok "Asset: qcnext.exe"
        } else {
            Warn "No portable qcnext.exe found - run the compile step first."
        }

        $nsisExe = Get-ChildItem $nsisDir -Filter "*setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($nsisExe) {
            $assets += $nsisExe.FullName
            $sig = "$($nsisExe.FullName).sig"
            if (Test-Path $sig) { $assets += $sig }
            Ok "Asset: $($nsisExe.Name)"
        } else {
            Warn "No NSIS setup.exe found in $nsisDir - run the compile step first."
        }

        $manifest = Join-Path $nsisDir "qcnext-latest.json"
        if (Test-Path $manifest) {
            $assets += $manifest
            Ok "Asset: qcnext-latest.json"
        } else {
            Warn "No update manifest (qcnext-latest.json) found - signed artifacts only."
        }

        if ($assets.Count -eq 0) {
            Warn "No release assets found - creating a release without binaries."
        }

        $changelogFile = Join-Path $env:TEMP "qcnext-changelog-$newVersion.md"
        # Prefer the curated CHANGELOG.md section (Summary-first layout keeps
        # it at the bottom of the file); fall back to the generated body.
        $releaseNotes = $body
        if (Test-Path $changelogPath) {
            $clContent = Get-Content $changelogPath -Raw
            $sectionMatch = [regex]::Match($clContent, "(?ms)## v$([regex]::Escape($newVersion)).*?(?=\n## |\Z)")
            if ($sectionMatch.Success) { $releaseNotes = $sectionMatch.Value }
        }
        $releaseNotes | Set-Content $changelogFile -Encoding utf8

        Invoke-OrDryRun {
            $ghArgs = @("release", "create", "v$newVersion",
                "--title", "QCnext v$newVersion",
                "--notes-file", $changelogFile,
                "--target", "main",
                "--latest")
            if ($newVersion -match '(alpha|beta|rc|pre)') { $ghArgs += "--prerelease" }
            foreach ($a in $assets) { $ghArgs += $a }
            Write-Host "    Running: gh $($ghArgs -join ' ')" -ForegroundColor DarkGray
            & gh @ghArgs
            if ($LASTEXITCODE -ne 0) { Fail "gh release create failed (exit $LASTEXITCODE)." }
            Ok "Release published: https://github.com/$repoSlug/releases/tag/v$newVersion"
        } "Would create GitHub release v$newVersion with $($assets.Count) asset(s)"

        if (Test-Path $changelogFile) { Remove-Item $changelogFile -Force }
    } else {
        Ok "GitHub release skipped (-NoRelease)"
    }
} else {
    Step "B/6  Release"
    Ok "Skipped (-Compile)"
}

# --- Summary ----------------------------------------------------------------
Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
$finalConf = Get-Content $confPath -Raw | ConvertFrom-Json
Write-Host " Pipeline finished (version $($finalConf.version))." -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host ""