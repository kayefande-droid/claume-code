# claume-code updater for Windows PowerShell
# Pulls the latest main from GitHub and reinstalls - run after every git push.
# Usage:  powershell -ExecutionPolicy Bypass -File update.ps1
# or:     irm https://raw.githubusercontent.com/kayefande-droid/claume-code/main/update.ps1 | iex
$ErrorActionPreference = "Stop"

$InstallRoot = Join-Path $env:USERPROFILE ".claume"
$AppDir      = Join-Path $InstallRoot "app"
$RepoDir     = Join-Path $InstallRoot "repo"
$VenvDir     = Join-Path $InstallRoot "venv"

Write-Host "* updating claume-code..." -ForegroundColor Cyan

# ---------------------------------------------------------------- python
$PythonCmd = $null
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $v = & py -3 --version 2>$null
    if ($LASTEXITCODE -eq 0 -and $v) { $PythonCmd = "py" }
}
if (-not $PythonCmd) {
    foreach ($cand in @("python3", "python")) {
        $c = Get-Command $cand -ErrorAction SilentlyContinue
        if ($c) { $PythonCmd = $cand; break }
    }
}
if (-not $PythonCmd) { Write-Host "X Python not found." -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- source
$SrcRoot = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "claume"))) {
    # running from a repo checkout - just git pull it
    $SrcRoot = $PSScriptRoot
    git -C $SrcRoot fetch origin 2>$null
    git -C $SrcRoot reset --hard origin/main 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host "X git pull failed (offline?)" -ForegroundColor Red; exit 1 }
} else {
    # fresh clone (or refresh) into ~/.claume/repo
    if (Test-Path $RepoDir) {
        git -C $RepoDir fetch origin 2>$null
        git -C $RepoDir reset --hard origin/main 2>$null | Out-Null
    } else {
        git clone --depth=1 https://github.com/kayefande-droid/claume-code.git $RepoDir
    }
    if ($LASTEXITCODE -ne 0) { Write-Host "X git fetch/clone failed (offline?)" -ForegroundColor Red; exit 1 }
    $SrcRoot = $RepoDir
}

Write-Host "* source at $SrcRoot (commit $((git -C $SrcRoot rev-parse --short HEAD)))" -ForegroundColor Gray

# ---------------------------------------------------------------- venv + reinstall
if (-not (Test-Path $VenvDir)) {
    & $PythonCmd -m venv $VenvDir
}
$pyExe = Join-Path $VenvDir "Scripts\python.exe"
& $pyExe -m pip install --quiet --upgrade pip
& $pyExe -m pip install --quiet --force-reinstall --no-deps --no-cache-dir $SrcRoot
if ($LASTEXITCODE -ne 0) { Write-Host "X reinstall failed" -ForegroundColor Red; exit 1 }
$installedVer = (& $pyExe -m pip show claume-code 2>$null | Select-String "^Version").ToString()
Write-Host "[OK] claume-code $installedVer installed (latest main)" -ForegroundColor Green

# keep the app dir fresh too (bundled skills etc.)
if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
Copy-Item -Path (Join-Path $SrcRoot "claume") -Destination $AppDir -Recurse -Force
foreach ($f in @("pyproject.toml", "README.md")) {
    if (Test-Path (Join-Path $SrcRoot $f)) { Copy-Item (Join-Path $SrcRoot $f) $AppDir -Force }
}
if (Test-Path (Join-Path $SrcRoot "skills")) {
    Copy-Item (Join-Path $SrcRoot "skills") $AppDir -Recurse -Force
}

Write-Host ""
Write-Host "  update complete - run:  claume" -ForegroundColor Green
