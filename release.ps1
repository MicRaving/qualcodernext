# QCnext - Release pipeline
#
# Builds, tags, force-pushes, and optionally uploads a GitHub Release with a
# self-generated changelog (conventional-commit style, grouped by prefix).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File release.ps1                       # patch bump, compile + push + release
#   powershell -ExecutionPolicy Bypass -File release.ps1 -Bump minor           # minor version bump
#   powershell -ExecutionPolicy Bypass -File release.ps1 -Bump major           # major version bump
#   powershell -ExecutionPolicy Bypass -File release.ps1 -Version 1.2.3        # explicit version
#   powershell -ExecutionPolicy Bypass -File release.ps1 -SkipCompile          # skip compile.ps1 (already built)
#   powershell -ExecutionPolicy Bypass -File release.ps1 -NoRelease            # tag + push only, no GitHub release
#   powershell -ExecutionPolicy Bypass -File release.ps1 -DryRun               # preview everything, change nothing
#
# Pipeline:
#   1. Preflight (clean tree, gh auth unless -NoRelease)
#   2. Compute the next version (semver bump or explicit)
#   3. Build a changelog from git log since the last tag
#   4. Bump version in frontend/src-tauri/tauri.conf.json
#   5. Commit "chore(release): vX.Y.Z" + create annotated tag vX.Y.Z
#   6. Run compile.ps1 (full release build) unless -SkipCompile
#   7. Force push main + the tag
#   8. `gh release create` with the changelog as release notes (unless -NoRelease)
#
# Prerequisites:
#   - backend/.venv (for compile.ps1)
#   - Node.js + npm, Rust + cargo (for compile.ps1)
#   - GitHub CLI (`gh`) authenticated - only needed when creating a release
#   - git configured with push access to origin/main

param(
    [ValidateSet("patch", "minor", "major")]
    [string]$Bump = "patch",
    [string]$Version,       # explicit version overrides -Bump
    [switch]$SkipCompile,
    [switch]$NoRelease,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$confPath = Join-Path $root "frontend\src-tauri\tauri.conf.json"
$repoSlug = "MicRaving/qualcodernext"

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
Write-Host "=============================================" -ForegroundColor Cyan

# --- 1. Preflight checks ----------------------------------------------------
Step "1/8  Preflight checks"

# Clean working tree (allow only untracked files)
$dirty = git status --porcelain | Where-Object { $_ -notmatch '^\?\?' }
if ($dirty) {
    Warn "Working tree has uncommitted changes. Commit or stash them first:"
    $dirty | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
    Fail "Cannot release with a dirty working tree."
}
Ok "Working tree clean"

# On main branch?
$branch = git branch --show-current
if ($branch -ne "main") {
    Warn "On branch '$branch' - releases should usually come from main."
}
Ok "Branch: $branch"

# gh CLI available + authenticated (skip for -NoRelease / -DryRun)
if (-not $NoRelease -and -not $DryRun) {
    $ghPath = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $ghPath) { Fail "GitHub CLI (gh) not found. Install from https://cli.github.com/ or pass -NoRelease." }
    $ghAuth = gh auth status 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "GitHub CLI not authenticated. Run 'gh auth login' first." }
    Ok "gh CLI authenticated"
} else {
    Ok "gh check skipped (NoRelease or DryRun)"
}

# --- 2. Determine the next version ------------------------------------------
Step "2/8  Determine version"

$conf = Get-Content $confPath -Raw | ConvertFrom-Json
$currentVersion = $conf.version
Ok "Current version: $currentVersion"

if ($Version) {
    $newVersion = $Version
} else {
    $parts = $currentVersion -split '\.'
    if ($parts.Length -ne 3) {
        Fail "Cannot parse version '$currentVersion' - expected MAJOR.MINOR.PATCH."
    }
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    $patch = [int]$parts[2]

    switch ($Bump) {
        "major" { $major++; $minor = 0; $patch = 0 }
        "minor" { $minor++; $patch = 0 }
        "patch" { $patch++ }
    }
    $newVersion = "$major.$minor.$patch"
}

if ($newVersion -eq $currentVersion) {
    Fail "New version ($newVersion) equals current. Use -Bump or -Version."
}
Ok "New version: $newVersion (was $currentVersion)"

# --- 3. Build the changelog since the last tag ------------------------------
Step "3/8  Generate changelog"

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

$breaking = @()
$features = @()
$fixes    = @()
$other    = @()

foreach ($line in $commits) {
    $sep = $line.IndexOf('|')
    if ($sep -le 0) { continue }
    $subject = $line.Substring(0, $sep).Trim()
    $hash    = $line.Substring($sep + 1).Trim()

    # Skip version-bump commits made by this script itself
    if ($subject -match '^chore\(release\):') { continue }

    if ($subject -match '^breaking[:(]' -or $subject -match '^BREAKING CHANGE') {
        $breaking += "- $subject ($hash)"
    } elseif ($subject -match '^feat[:(]') {
        $clean = ($subject -replace '^feat[\(]([^)]*)\):\s*', '[feature-scope] ') -replace '^feat:\s*', ''
        $features += "- $clean ($hash)"
    } elseif ($subject -match '^fix[:(]') {
        $clean = ($subject -replace '^fix[\(]([^)]*)\):\s*', '[fix-scope] ') -replace '^fix:\s*', ''
        $fixes += "- $clean ($hash)"
    } else {
        $other += "- $subject ($hash)"
    }
}

$body = "## What's Changed in v$newVersion`n`n"
if ($breaking.Count -gt 0) {
    $body += "### Breaking Changes`n" + ($breaking -join "`n") + "`n`n"
}
if ($features.Count -gt 0) {
    $body += "### Features`n" + ($features -join "`n") + "`n`n"
}
if ($fixes.Count -gt 0) {
    $body += "### Bug Fixes`n" + ($fixes -join "`n") + "`n`n"
}
if ($other.Count -gt 0) {
    $body += "### Other Changes`n" + ($other -join "`n") + "`n`n"
}
if (-not ($breaking.Count + $features.Count + $fixes.Count + $other.Count)) {
    $body += "_No commits recorded since the last tag._`n`n"
}
if ($lastTag) { $compareFrom = $lastTag } else { $compareFrom = "v0.0.0" }
$body += "---`n**Full changelog**: https://github.com/$repoSlug/compare/$compareFrom...v$newVersion"

$commitCount = $breaking.Count + $features.Count + $fixes.Count + $other.Count
if ($lastTag) {
    Ok "Changelog ready: $commitCount commits since $lastTag"
} else {
    Ok "Changelog ready: $commitCount commits (no previous tag)"
}

# --- 4. Bump version in tauri.conf.json + append CHANGELOG.md ---------------
Step "4/8  Bump version + record changelog"

$changelogPath = Join-Path $root "CHANGELOG.md"

Invoke-OrDryRun {
    # 4a. tauri.conf.json
    $raw = Get-Content $confPath -Raw
    $pattern = '"version"\s*:\s*"' + [regex]::Escape($currentVersion) + '"'
    $replacement = '"version": "' + $newVersion + '"'
    $patched = $raw -replace $pattern, $replacement
    if ($patched -eq $raw) {
        Fail "Version pattern not found in $confPath"
    }
    Set-Content $confPath $patched -Encoding utf8 -NoNewline
    Ok "tauri.conf.json version set to $newVersion"

    # 4b. Prepend the release section to CHANGELOG.md (right after the header
    #     separator, before the historical "Major changes" content).
    if (Test-Path $changelogPath) {
        $today = (Get-Date).ToString("yyyy-MM-dd")
        $section = "## v$newVersion ($today)`n`n$body`n`n---`n"
        $cl = Get-Content $changelogPath -Raw -Encoding UTF8
        $headerPattern = '(?ms)^# QCnext.*?^---\s*$'
        if ($cl -match $headerPattern) {
            # Insert after the FIRST --- separator that closes the intro block.
            # MatchEvaluator keeps '$section' literal (no '$1' substitution).
            $cl = [regex]::Replace($cl, $headerPattern, { param($m) $section }, 1)
        } else {
            # Fallback: prepend at the very top.
            $cl = $section + $cl
        }
        Set-Content $changelogPath $cl -Encoding UTF8
        Ok "CHANGELOG.md updated with v$newVersion section"
    } else {
        Warn "CHANGELOG.md not found - skipped"
    }
} "Would bump tauri.conf.json to $newVersion and prepend the changelog to CHANGELOG.md"

# --- 5. Commit + tag --------------------------------------------------------
Step "5/8  Commit version bump + create tag"

Invoke-OrDryRun {
    git add $confPath
    if (Test-Path $changelogPath) { git add $changelogPath }
    git commit -m "chore(release): v$newVersion" | Out-Null
    Ok "Committed 'chore(release): v$newVersion'"
} "Would commit 'chore(release): v$newVersion'"

Invoke-OrDryRun {
    git tag -a "v$newVersion" -m "Release v$newVersion"
    Ok "Created annotated tag v$newVersion"
} "Would create annotated tag v$newVersion"

# --- 6. Compile -------------------------------------------------------------
if (-not $SkipCompile) {
    Step "6/8  Compile (compile.ps1)"
    $compileScript = Join-Path $root "compile.ps1"
    if (-not (Test-Path $compileScript)) { Fail "compile.ps1 not found at $compileScript" }

    if ($DryRun) {
        Write-Host "    [dry-run] Would run compile.ps1" -ForegroundColor DarkGray
        Ok "Compile skipped in dry-run"
    } else {
        & $compileScript
        if ($LASTEXITCODE -ne 0) { Fail "compile.ps1 failed (exit $LASTEXITCODE)." }
        Ok "Compilation complete"
    }
} else {
    Step "6/8  Compile"
    Ok "Skipped (-SkipCompile)"
}

# --- 7. Force push ----------------------------------------------------------
Step "7/8  Force push to origin"

Invoke-OrDryRun {
    git push --force origin main | Out-Null
    git push origin "v$newVersion" | Out-Null
    Ok "Pushed main + tag v$newVersion to origin"
} "Would force-push main and push tag v$newVersion"

# --- 8. GitHub Release ------------------------------------------------------
if (-not $NoRelease) {
    Step "8/8  Create GitHub Release v$newVersion"

    $nsisDir = Join-Path $root "frontend\src-tauri\target\release\bundle\nsis"
    $assets = @()

    $nsisExe = Get-ChildItem $nsisDir -Filter "*setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($nsisExe) {
        $assets += $nsisExe.FullName
        $sig = "$($nsisExe.FullName).sig"
        if (Test-Path $sig) { $assets += $sig }
        Ok "Asset: $($nsisExe.Name)"
    } else {
        Warn "No NSIS setup.exe found in $nsisDir"
    }

    $manifest = Join-Path $nsisDir "qualcoder-latest.json"
    if (Test-Path $manifest) {
        $assets += $manifest
        Ok "Asset: qualcoder-latest.json"
    }

    if ($assets.Count -eq 0) {
        Warn "No release assets found - creating a release without binaries."
    }

    $changelogFile = Join-Path $env:TEMP "qcnext-changelog-$newVersion.md"
    $body | Set-Content $changelogFile -Encoding utf8

    Invoke-OrDryRun {
        $ghArgs = @("release", "create", "v$newVersion",
            "--title", "QCnext v$newVersion",
            "--notes-file", $changelogFile,
            "--target", "main",
            "--latest")
        if ($newVersion -match '(alpha|beta|rc|pre)') {
            $ghArgs += "--prerelease"
        }
        foreach ($a in $assets) { $ghArgs += $a }

        Write-Host "    Running: gh $($ghArgs -join ' ')" -ForegroundColor DarkGray
        & gh @ghArgs
        if ($LASTEXITCODE -ne 0) { Fail "gh release create failed (exit $LASTEXITCODE)." }
        Ok "Release published: https://github.com/$repoSlug/releases/tag/v$newVersion"
    } "Would create GitHub release v$newVersion with $($assets.Count) asset(s)"

    if (Test-Path $changelogFile) { Remove-Item $changelogFile -Force }
} else {
    Step "8/8  GitHub Release"
    Ok "Skipped (-NoRelease)"
}

# --- Summary ----------------------------------------------------------------
Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host " Release v$newVersion complete." -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Version:    v$newVersion" -ForegroundColor White
Write-Host "  Tag:        v$newVersion" -ForegroundColor White
Write-Host "  Branch:     $branch" -ForegroundColor White
Write-Host "  Commits:    $commitCount in this changelog" -ForegroundColor White
if (-not $NoRelease -and -not $DryRun) {
    Write-Host "  Release:    https://github.com/$repoSlug/releases/tag/v$newVersion" -ForegroundColor White
}
Write-Host ""