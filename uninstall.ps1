# claume uninstaller
$InstallRoot = Join-Path $env:USERPROFILE ".claume"
$BinDir = Join-Path $InstallRoot "bin"

Write-Host "▸ removing $InstallRoot" -ForegroundColor Cyan
if (Test-Path $InstallRoot) { Remove-Item $InstallRoot -Recurse -Force }

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$cleaned = ($userPath -split ";" | Where-Object { $_ -ne $BinDir }) -join ";"
[Environment]::SetEnvironmentVariable("Path", $cleaned, "User")
Write-Host "✔ claume removed from PATH and disk" -ForegroundColor Green
