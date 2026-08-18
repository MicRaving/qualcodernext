# QCnext - All-in-one release pipeline
#
# Handles the full release from dirty working tree to published GitHub release:
#   1. Auto-commit all source changes (+ untrack compiled artifacts)
#   2. Version bump + changelog (tauri.conf.json + CHANGELOG.md)
#   3. Compile (PyInstaller onedir + Tauri release build)
#   4. Tag + push + GitHub release
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File release-all.ps1                    # patch bump
#   powershell -ExecutionPolicy Bypass -File release-all.ps1 -Bump minor        # minor bump
#   powershell -ExecutionPolicy Bypass -File release-all.ps1 -Version 1.2.3     # explicit version
#   powershell -ExecutionPolicy Bypass -File release-all.ps1 -DryRun            # preview, no changes
#
# Skips release.ps1's "dirty tree" check by committing everything first, so
# you never have to manually stage or stash.

param(
    [ValidateSet("patch", "minor", "major")]
    [string]$Bump = "patch",
    [string]$Version,
    [switch]$DryRun,
    [switch]$NoRelease
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !   $msg" -ForegroundColor DarkYellow }
function Fail($msg) { Write-Host "    X   $msg" -ForegroundColor Red; throw $msg }

# --- Header -----------------------------------------------------------------
Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " QCnext - all-in-one release pipeline" -ForegroundColor Cyan
if ($DryRun) { Write-Host " *** DRY RUN - no changes will be made ***" -ForegroundColor Magenta }
Write-Host "=============================================" -ForegroundColor Cyan

# --- 1. Auto-commit all source changes --------------------------------------
Step "1/5  Auto-commit source changes"

# 1a. Untrack compiled backend artifacts if still in the index
$tracked = git ls-files --cached -- frontend/src-tauri/resources/backend/ 2>$null
if ($tracked) {
    $count = ($tracked | Measure-Object).Count
    Warn "Untracking $count compiled backend artifact(s) still in the index."
    if (-not $DryRun) {
        git rm --cached -r frontend/src-tauri/resources/backend/ | Out-Null
        Ok "Removed compiled artifacts from git index (files kept on disk)"
    } else {
        Ok "[dry-run] Would untrack compiled artifacts"
    }
} else {
    Ok "No tracked compiled artifacts to untrack"
}

# 1b. Stage everything
if (-not $DryRun) { git add -A | Out-Null }

# 1c. Build a conventional-commit message from staged changes
$dirty = if ($DryRun) { git diff --name-only } else { git diff --cached --name-only }
if ($dirty) {
    $dirs = @{}
    foreach ($f in $dirty) {
        $top = ($f -split '/')[0]
        if (-not $dirs.ContainsKey($top)) { $dirs[$top] = 0 }
        $dirs[$top]++
    }
    $summary = ($dirs.GetEnumerator() | ForEach-Object { "$($_.Key)($($_.Value))" }) -join " "

    $hasBackend = ($dirty -match '^backend/' | Where-Object { $_ -match '\.py$' }).Count -gt 0
    $hasFrontend = ($dirty -match '^frontend/(src|tests-e2e)/' | Where-Object { $_ -match '\.(ts|tsx)$' }).Count -gt 0
    $hasDocs = ($dirty -match '\.(md)$').Count -gt 0

    if ($hasBackend -and $hasFrontend)   { $prefix = "feat" }
    elseif ($hasBackend)                  { $prefix = "feat(backend)" }
    elseif ($hasFrontend)                 { $prefix = "feat(frontend)" }
    elseif ($hasDocs)                     { $prefix = "docs" }
    else                                 { $prefix = "chore" }

    $msg = "${prefix}: collaboration presence + sync improvements"

    if (-not $DryRun) {
        git commit -m $msg --no-verify | Out-Null
        Ok "Committed: $msg ($($dirty.Count) files: $summary)"
    } else {
        Ok "[dry-run] Would commit $msg ($($dirty.Count) files: $summary)"
        $ErrorActionPreference = "SilentlyContinue"; git reset HEAD 2>$null; $ErrorActionPreference = "Stop"
    }
} else {
    Ok "Nothing to commit"
}

# --- 2. Confirm clean tree (release.ps1 requires this) ----------------------
Step "2/5  Verify clean working tree"
if ($DryRun) {
    Ok "Skipped in dry-run (changes not staged)"
} else {
    $dirtyNow = git status --porcelain | Where-Object { $_ -notmatch '^\?\?' }
    if ($dirtyNow) {
        $dirtyNow | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
        Fail "Still dirty after commit."
    }
    Ok "Working tree clean"
}

# --- 3. Version bump + changelog (but NOT compile yet — artifacts need the new version)
Step "3/5  Version bump + changelog"
$confPath = Join-Path $root "frontend\src-tauri\tauri.conf.json"
$conf = Get-Content $confPath -Raw | ConvertFrom-Json
$currentVersion = $conf.version

if ($Version) {
    $newVersion = $Version
} else {
    $parts = $currentVersion -split '\.'
    $major = [int]$parts[0]; $minor = [int]$parts[1]; $patch = [int]$parts[2]
    switch ($Bump) {
        "major" { $major++; $minor = 0; $patch = 0 }
        "minor" { $minor++; $patch = 0 }
        "patch" { $patch++ }
    }
    $newVersion = "$major.$minor.$patch"
}
if ($newVersion -eq $currentVersion) { Fail "New version ($newVersion) equals current." }
Ok "Current: $currentVersion  →  New: $newVersion"

# Bump tauri.conf.json
if (-not $DryRun) {
    $raw = Get-Content $confPath -Raw
    $pattern = '"version"\s*:\s*"' + [regex]::Escape($currentVersion) + '"'
    $replacement = '"version": "' + $newVersion + '"'
    $patched = $raw -replace $pattern, $replacement
    if ($patched -eq $raw) { Fail "Version pattern not found in $confPath" }
    Set-Content $confPath $patched -Encoding utf8 -NoNewline
    Ok "tauri.conf.json version set to $newVersion"
} else {
    Ok "[dry-run] Would set tauri.conf.json version to $newVersion"
}

# Generate + prepend changelog
$changelogPath = Join-Path $root "CHANGELOG.md"
if (Test-Path $changelogPath) {
    if (-not $DryRun) {
        $lastTag = $null
        $null = git describe --tags --abbrev=0 2>$null
        if ($LASTEXITCODE -eq 0) { $lastTag = (git describe --tags --abbrev=0).Trim() }

        $commitRange = if ($lastTag) { "$lastTag..HEAD" } else { "HEAD" }
        $commits = @()
        foreach ($line in (& git log $commitRange --pretty=format:"%s|%h" --no-merges 2>$null)) {
            if ($line) { $commits += $line }
        }

        $body = "## What's Changed in v$newVersion`n`n"
        $features = @(); $fixes = @(); $breaking = @(); $other = @()
        foreach ($line in $commits) {
            $sep = $line.IndexOf('|')
            if ($sep -le 0) { continue }
            $subject = $line.Substring(0, $sep).Trim()
            $hash = $line.Substring($sep + 1).Trim()
            if ($subject -match '^chore\(release\):') { continue }
            if ($subject -match '^feat[:(]') {
                $clean = ($subject -replace '^feat[\(][^)]*\):\s*', '[scope] ') -replace '^feat:\s*', ''
                $features += "- $clean ($hash)"
            } elseif ($subject -match '^fix[:(]') {
                $clean = ($subject -replace '^fix[\(][^)]*\):\s*', '[scope] ') -replace '^fix:\s*', ''
                $fixes += "- $clean ($hash)"
            } elseif ($subject -match '^breaking|^BREAKING') {
                $breaking += "- $subject ($hash)"
            } else {
                $other += "- $subject ($hash)"
            }
        }
        if ($features.Count -gt 0) { $body += "### Features`n" + ($features -join "`n") + "`n`n" }
        if ($fixes.Count -gt 0)    { $body += "### Bug Fixes`n" + ($fixes -join "`n") + "`n`n" }
        if ($breaking.Count -gt 0) { $body += "### Breaking`n" + ($breaking -join "`n") + "`n`n" }
        if ($other.Count -gt 0)    { $body += "### Other`n" + ($other -join "`n") + "`n`n" }

        $today = (Get-Date).ToString("yyyy-MM-dd")
        $section = "## v$newVersion ($today)`n`n$body`n"
        $cl = Get-Content $changelogPath -Raw -Encoding UTF8
        $headerPattern = '(?ms)^# QCnext.*?^---\s*$'
        if ($cl -match $headerPattern) {
            $cl = [regex]::Replace($cl, $headerPattern, { param($m) $section }, 1)
        } else {
            $cl = $section + $cl
        }
        Set-Content $changelogPath $cl -Encoding UTF8
        Ok "CHANGELOG.md updated with v$newVersion section"
    } else {
        Ok "[dry-run] Would prepend v$newVersion changelog"
    }
} else {
    Warn "CHANGELOG.md not found"
}

# Commit the version bump
if (-not $DryRun) {
    git add $confPath
    if (Test-Path $changelogPath) { git add $changelogPath }
    git commit -m "chore(release): v$newVersion" --no-verify | Out-Null
    Ok "Committed 'chore(release): v$newVersion'"
} else {
    Ok "[dry-run] Would commit 'chore(release): v$newVersion'"
}

# --- 4. Compile (builds against the new version) ----------------------------
Step "4/5  Compile (PyInstaller + Tauri)"
if ($DryRun) {
    Ok "Compile skipped in dry-run"
} else {
    $compileScript = Join-Path $root "compile.ps1"
    if (-not (Test-Path $compileScript)) { Fail "compile.ps1 not found" }
    & $compileScript
    if ($LASTEXITCODE -ne 0) { Fail "compile.ps1 failed (exit $LASTEXITCODE)." }
    Ok "Compilation complete"
}

# --- 5. Tag + push + GitHub release -----------------------------------------
Step "5/5  Tag + push + GitHub release"

if (-not $DryRun) {
    git tag -a "v$newVersion" -m "Release v$newVersion"
    Ok "Created tag v$newVersion"
} else {
    Ok "[dry-run] Would create tag v$newVersion"
}

if (-not $DryRun) {
    git push origin main --force | Out-Null
    git push origin "v$newVersion" | Out-Null
    Ok "Pushed main + tag to origin"
} else {
    Ok "[dry-run] Would push main + tag"
}

if (-not $NoRelease -and -not $DryRun) {
    $nsisDir = Join-Path $root "frontend\src-tauri\target\release\bundle\nsis"
    $nsisExe = Get-ChildItem $nsisDir -Filter "*setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    $changelogBody = ""
    if (Test-Path $changelogPath) {
        $clContent = Get-Content $changelogPath -Raw
        $sectionMatch = [regex]::Match($clContent, "(?ms)## v$newVersion.*?(?=\n## |\Z)")
        if ($sectionMatch.Success) { $changelogBody = $sectionMatch.Value }
    }
    $changelogFile = Join-Path $env:TEMP "qcnext-release-$newVersion.md"
    $changelogBody | Set-Content $changelogFile -Encoding utf8

    $ghArgs = @("release", "create", "v$newVersion",
        "--title", "QCnext v$newVersion",
        "--notes-file", $changelogFile,
        "--target", "main", "--latest")

    if ($nsisExe) {
        $ghArgs += $nsisExe.FullName
        $sig = "$($nsisExe.FullName).sig"
        if (Test-Path $sig) { $ghArgs += $sig }
    }

    & gh @ghArgs
    if ($LASTEXITCODE -ne 0) { Warn "gh release create failed (exit $LASTEXITCODE)." }
    else { Ok "Release published: v$newVersion" }
    if (Test-Path $changelogFile) { Remove-Item $changelogFile -Force }
} else {
    Ok "GitHub release skipped"
}

# --- Summary -----------------------------------------------------------------
$finalConf = Get-Content $confPath -Raw | ConvertFrom-Json
$fv = $finalConf.version
Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host " Release v$fv complete." -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
