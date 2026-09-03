# ──────────────────────────────────────────────────────────────
# build_and_prepare.ps1
# Build the React frontend and copy into static/ for Databricks
# Run from the project root (capstone-FleetGuardAI-main\)
# ──────────────────────────────────────────────────────────────
$ErrorActionPreference = "Stop"

$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$DatabricksDir = Split-Path -Parent $ScriptDir
$ProjectRoot   = Split-Path -Parent $DatabricksDir
$FrontendDir   = Join-Path $ProjectRoot "fleetguard-frontend"
$StaticDir     = Join-Path $DatabricksDir "static"

Write-Host "==> Installing frontend dependencies..." -ForegroundColor Cyan
Set-Location $FrontendDir
npm install

Write-Host "==> Building frontend..." -ForegroundColor Cyan
npm run build

Write-Host "==> Cleaning old static files..." -ForegroundColor Cyan
if (Test-Path $StaticDir) {
    Get-ChildItem -Path $StaticDir -Recurse | Remove-Item -Force -Recurse
}

Write-Host "==> Copying build output to static/..." -ForegroundColor Cyan
Copy-Item -Path (Join-Path $FrontendDir "dist\*") -Destination $StaticDir -Recurse -Force

Write-Host ""
Write-Host "BUILD COMPLETE!" -ForegroundColor Green
Write-Host "Static files: $StaticDir" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Edit app.yaml with your env vars (MYSQL_HOST, MYSQL_PASSWORD, etc.)"
Write-Host "  2. Deploy:  databricks apps deploy <app-name> --source-code-path $DatabricksDir"
