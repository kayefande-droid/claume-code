# claume-code installer for Windows PowerShell
# Usage:  powershell -ExecutionPolicy Bypass -File install.ps1
# or:     irm <raw-url>/install.ps1 | iex
# NOTE: kept pure-ASCII on purpose - PowerShell 5.1 mis-reads UTF-8 files
#       without a BOM and mangles non-ASCII glyphs.

$ErrorActionPreference = "Stop"

$Banner = @"

  _____ __ _ _____ _  _ ___ ___  _  _ ___
 / __) \ / / __) \ / )\ ) )_ \ / )( \ __)
( (__ ) X ( __ )) X ( | | | | | | ) ) __)
 \___)_(_)_(___/)_(_)_(_)_| |_(_/ (_(__/

      pixel-grade CLI coding agent  -  free via NVIDIA NIM

"@

Write-Host $Banner -ForegroundColor Green

# ---------------------------------------------------------------- paths
$InstallRoot = Join-Path $env:USERPROFILE ".claume"
$AppDir      = Join-Path $InstallRoot "app"
$VenvDir     = Join-Path $InstallRoot "venv"
$BinDir      = Join-Path $InstallRoot "bin"

Write-Host "* install location: $InstallRoot" -ForegroundColor Cyan

# ---------------------------------------------------------------- python
# Robust detection: the 'python' alias can be a broken WindowsApps stub,
# so try the py launcher first, then python3/python with real probes.
$PythonCmd = $null
$ver = ""
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $v = & py -3 --version 2>$null
    if ($LASTEXITCODE -eq 0 -and $v) { $PythonCmd = "py"; $ver = ($v | Select-Object -First 1) }
}
if (-not $PythonCmd) {
    foreach ($cand in @("python3", "python")) {
        $c = Get-Command $cand -ErrorAction SilentlyContinue
        if ($c) {
            try {
                $v = & $cand --version 2>$null
                if ($LASTEXITCODE -eq 0 -and $v) { $PythonCmd = $cand; $ver = ($v | Select-Object -First 1); break }
            } catch { }
        }
    }
}
if (-not $PythonCmd) {
    Write-Host "X Python not found. Install Python 3.10+ from python.org first." -ForegroundColor Red
    exit 1
}
Write-Host "* found $ver" -ForegroundColor Gray

# ---------------------------------------------------------------- copy app
# IMPORTANT: when run via 'irm ... | iex' there is NO script file, so
# $PSScriptRoot is an empty string and Join-Path would throw
# "Cannot bind argument to parameter 'Path' because it is an empty string".
# Guard it, and fall back to downloading the repo zip.
$SrcRoot = $null
if ($PSScriptRoot) { $SrcRoot = $PSScriptRoot }

$sourceApp = $null
if ($SrcRoot -and (Test-Path (Join-Path $SrcRoot "claume"))) {
    $sourceApp = Join-Path $SrcRoot "claume"
} else {
    Write-Host "* fetching claume-code from GitHub..." -ForegroundColor Cyan
    $zip = Join-Path $env:TEMP "claume-code.zip"
    Invoke-WebRequest -Uri "https://github.com/kayefande-droid/claume-code/archive/refs/heads/main.zip" -OutFile $zip
    $extractRoot = Join-Path $env:TEMP "claume-code-extract"
    if (Test-Path $extractRoot) { Remove-Item $extractRoot -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $extractRoot -Force
    $SrcRoot = Join-Path $extractRoot "claume-code-main"
    $sourceApp = Join-Path $SrcRoot "claume"
}
if (-not $sourceApp -or -not (Test-Path $sourceApp)) {
    Write-Host "X could not locate the 'claume' package (looked in $SrcRoot)." -ForegroundColor Red
    exit 1
}

# Fresh copy every time (idempotent reinstalls)
# NOTE: create $AppDir BEFORE Copy-Item - if it doesn't exist, Copy-Item
# renames the source folder instead of nesting it, breaking the layout.
if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
Copy-Item -Path $sourceApp -Destination $AppDir -Recurse -Force
foreach ($f in @("pyproject.toml", "README.md", "LICENSE")) {
    if (Test-Path (Join-Path $SrcRoot $f)) {
        Copy-Item (Join-Path $SrcRoot $f) $AppDir -Force
    }
}
# Ship bundled skills (ui-ux-pro-max design pack) so they seed on first run
if (Test-Path (Join-Path $SrcRoot "skills")) {
    Copy-Item (Join-Path $SrcRoot "skills") $AppDir -Recurse -Force
    Write-Host "[OK] bundled skills staged (ui-ux-pro-max)" -ForegroundColor Green
}
Write-Host "[OK] copied agent core" -ForegroundColor Green

# ---------------------------------------------------------------- venv + deps
if (-not (Test-Path $VenvDir)) {
    Write-Host "* creating virtual environment..." -ForegroundColor Cyan
    & $PythonCmd -m venv $VenvDir
}
$pyExe = Join-Path $VenvDir "Scripts\python.exe"
& $pyExe -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Host "X pip upgrade failed" -ForegroundColor Red; exit 1 }
& $pyExe -m pip install --quiet $AppDir
if ($LASTEXITCODE -ne 0) { Write-Host "X package install failed" -ForegroundColor Red; exit 1 }
Write-Host "[OK] dependencies installed (stdlib-only - nothing heavy)" -ForegroundColor Green

# ---------------------------------------------------------------- shims
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

$ps1Shim = Join-Path $BinDir "claume.ps1"
$ps1Body = '& "' + $VenvDir + '\Scripts\python.exe" -m claume.cli @args' + "`r`n" + 'exit $LASTEXITCODE'
Set-Content -Path $ps1Shim -Value $ps1Body -Encoding ASCII

$cmdShim = Join-Path $BinDir "claume.cmd"
$cmdBody = '@echo off' + "`r`n" + '"' + $VenvDir + '\Scripts\python.exe" -m claume.cli %*'
Set-Content -Path $cmdShim -Value $cmdBody -Encoding ASCII

Write-Host "[OK] created 'claume' command shims" -ForegroundColor Green

# jarvis desktop-assistant shims (same venv, own entrypoint)
$jarvisPs1 = Join-Path $BinDir "jarvis.ps1"
$jarvisBody = '& "' + $VenvDir + '\Scripts\python.exe" -m claume.jarvis_app @args' + "`r`n" + 'exit $LASTEXITCODE'
Set-Content -Path $jarvisPs1 -Value $jarvisBody -Encoding ASCII
$jarvisCmd = Join-Path $BinDir "jarvis.cmd"
$jarvisCmdBody = '@echo off' + "`r`n" + '"' + $VenvDir + '\Scripts\python.exe" -m claume.jarvis_app %*'
Set-Content -Path $jarvisCmd -Value $jarvisCmdBody -Encoding ASCII

# Desktop shortcut with the jarvis arc-reactor icon
try {
    $iconSrc = Join-Path $AppDir "claume\assets\jarvis.ico"
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnk = Join-Path $desktop "jarvis (claume).lnk"
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = $jarvisCmd
    $sc.WorkingDirectory = $env:USERPROFILE
    $sc.Description = "jarvis - claume voice assistant"
    if ($iconSrc -and (Test-Path $iconSrc)) { $sc.IconLocation = $iconSrc }
    $sc.Save()
    Write-Host "[OK] desktop shortcut 'jarvis (claume)' created (arc-reactor icon)" -ForegroundColor Green
} catch {
    Write-Host "[~~] desktop shortcut skipped ($($_.Exception.Message))" -ForegroundColor DarkYellow
}

# ---------------------------------------------------------------- PATH
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if ($userPath -notlike "*$BinDir*") {
    $newPath = $userPath.TrimEnd(";") + ";" + $BinDir
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    $env:Path += ";$BinDir"
    Write-Host "[OK] added $BinDir to your user PATH" -ForegroundColor Green
}

# ---------------------------------------------------------------- done
Write-Host ""
Write-Host "  +----------------------------------------------+" -ForegroundColor DarkGray
Write-Host "  |  claume-code installed                       |" -ForegroundColor Green
Write-Host "  |  open a NEW PowerShell tab and run:          |" -ForegroundColor Gray
Write-Host "  |                                              |" -ForegroundColor Gray
Write-Host "  |       claume                                 |" -ForegroundColor White
Write-Host "  |                                              |" -ForegroundColor Gray
Write-Host "  +----------------------------------------------+" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  first run asks for your free NVIDIA API key (build.nvidia.com)" -ForegroundColor DarkCyan
Write-Host ""
