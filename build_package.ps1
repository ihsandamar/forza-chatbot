# build_package.ps1
# Self-contained chatbot-api deployment package builder.
# Output: dist\chatbot-api-package\  (zip and ship to customers)
#
# Usage:
#   .\build_package.ps1
#   .\build_package.ps1 -Version "2.1.0"
#   .\build_package.ps1 -SkipPackageInstall   (re-copy source only, fast)

param(
    [string]$Version             = "1.0.0",
    [string]$OutputDir           = "dist\chatbot-api-package",
    [switch]$SkipPackageInstall
)

$ErrorActionPreference = "Stop"

$PythonVersion  = "3.12.10"
$PythonEmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$GetPipUrl      = "https://bootstrap.pypa.io/get-pip.py"
$PythonDir      = "$OutputDir\python"
$PythonExe      = "$PythonDir\python.exe"

function Write-Step($n, $total, $msg) {
    Write-Host "[$n/$total] $msg" -ForegroundColor Cyan
}

$totalSteps = if ($SkipPackageInstall) { 3 } else { 7 }

# ── 1. Output directory ───────────────────────────────────────────────────────
Write-Step 1 $totalSteps "Preparing output directory: $OutputDir"

if (-not $SkipPackageInstall) {
    if (Test-Path $OutputDir) { Remove-Item $OutputDir -Recurse -Force }
    New-Item -ItemType Directory -Path $PythonDir -Force | Out-Null
}

# ── 2. Download Python embeddable ─────────────────────────────────────────────
if (-not $SkipPackageInstall) {
    Write-Step 2 $totalSteps "Downloading Python $PythonVersion embeddable..."
    $zipPath = "$OutputDir\python-embed.zip"
    Invoke-WebRequest -Uri $PythonEmbedUrl -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $PythonDir -Force
    Remove-Item $zipPath
    Write-Host "  OK: Python extracted"
}

# ── 3. Enable site-packages ───────────────────────────────────────────────────
if (-not $SkipPackageInstall) {
    Write-Step 3 $totalSteps "Enabling site-packages..."
    $pthFile = Get-ChildItem $PythonDir -Filter "python*._pth" | Select-Object -First 1
    if (-not $pthFile) { throw "._pth file not found. Python zip may not have extracted correctly." }

    $lines = Get-Content $pthFile.FullName
    $lines = $lines | ForEach-Object { $_ -replace "^#import site$", "import site" }
    if ($lines -notcontains "Lib\site-packages") { $lines += "Lib\site-packages" }
    # Write WITHOUT BOM — BOM corrupts the python312.zip path in sys.path
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllLines($pthFile.FullName, $lines, $utf8NoBom)
    Write-Host "  OK: $($pthFile.Name) updated"
}

# ── 4. Install pip ────────────────────────────────────────────────────────────
if (-not $SkipPackageInstall) {
    Write-Step 4 $totalSteps "Installing pip..."
    $getPipPath = "$OutputDir\get-pip.py"
    Invoke-WebRequest -Uri $GetPipUrl -OutFile $getPipPath -UseBasicParsing
    & $PythonExe $getPipPath --no-warn-script-location -q
    Remove-Item $getPipPath
    Write-Host "  OK: pip ready"

    # sitecustomize.py — adds package root to sys.path automatically at startup
    # This allows 'from src.launch import ...' to work without PYTHONPATH
    $sitecustomize = @'
import sys, os
# python\ parent is the package root (where src/, main.py live)
_package_root = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)
'@
    $scPath = "$PythonDir\Lib\site-packages\sitecustomize.py"
    New-Item -ItemType Directory -Path "$PythonDir\Lib\site-packages" -Force | Out-Null
    [System.IO.File]::WriteAllText($scPath, $sitecustomize, [System.Text.Encoding]::UTF8)
    Write-Host "  OK: sitecustomize.py created"
}

# ── 5. Install packages ───────────────────────────────────────────────────────
if (-not $SkipPackageInstall) {
    Write-Step 5 $totalSteps "Installing packages from requirements.txt (may take 10-15 min)..."
    & $PythonExe -m pip install `
        -r requirements.txt `
        --no-deps `
        --no-warn-script-location `
        --no-compile `
        -q
    if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }
    Write-Host "  OK: All packages installed"
}

# ── 6. Copy source files ──────────────────────────────────────────────────────
$srcStep = if ($SkipPackageInstall) { 2 } else { 6 }
Write-Step $srcStep $totalSteps "Copying source files..."

$includeDirs  = @("src", "config", "assets", "embedding", "data")
$includeFiles = @("main.py", "api_app.py", "requirements.txt")

foreach ($d in $includeDirs) {
    if (Test-Path $d) {
        Copy-Item $d "$OutputDir\$d" -Recurse -Force
        Write-Host "  OK: $d/"
    }
}

foreach ($f in $includeFiles) {
    if (Test-Path $f) {
        Copy-Item $f "$OutputDir\$f" -Force
        Write-Host "  OK: $f"
    }
}

# .env: send example only, never send secrets
if (Test-Path ".env.example") {
    Copy-Item ".env.example" "$OutputDir\.env.example" -Force
    Write-Host "  OK: .env.example"
} elseif (Test-Path ".env") {
    $envContent = Get-Content ".env" | ForEach-Object {
        if ($_ -match "^([^#=][^=]*)=(.+)$") { "$($Matches[1])=" } else { $_ }
    }
    $envContent | Set-Content "$OutputDir\.env.example" -Encoding UTF8
    Write-Host "  OK: .env.example (values cleared)"
}

# logs directory
New-Item -ItemType Directory -Path "$OutputDir\logs" -Force | Out-Null

# ── 7. Create startup files ───────────────────────────────────────────────────
$startStep = if ($SkipPackageInstall) { 3 } else { 7 }
Write-Step $startStep $totalSteps "Creating startup files..."

# start.bat — manual test
$startBat = "@echo off`r`ncd /d `"%~dp0`"`r`nif not exist `".env`" (`r`n    echo ERROR: .env file not found. Copy .env.example to .env and fill in values.`r`n    pause`r`n    exit /b 1`r`n)`r`nset PYTHONPATH=%~dp0`r`necho Starting Chatbot API...`r`npython\python.exe main.py --interface api`r`npause`r`n"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText("$PWD\$OutputDir\start.bat", $startBat, $utf8NoBom)

# pm2-ecosystem.config.js
$pm2Config = @'
module.exports = {
  apps: [{
    name    : 'chatbot-api',
    script  : 'python\\python.exe',
    args    : 'main.py --interface api',
    cwd     : __dirname,
    interpreter: 'none',
    env: {
      PYTHONPATH       : __dirname,
      PYTHONIOENCODING : 'utf-8',
    },
    error_file     : 'logs\\pm2-error.log',
    out_file       : 'logs\\pm2-out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
  }]
}
'@
[System.IO.File]::WriteAllText("$PWD\$OutputDir\pm2-ecosystem.config.js", $pm2Config, [System.Text.Encoding]::UTF8)

# README.txt
$readme = @"
==============================
  Chatbot API v$Version
  Setup Guide
==============================

REQUIREMENTS
  - Windows 10/11 or Windows Server 2019+
  - Node.js + PM2  (npm install -g pm2)
  - ODBC Driver 17 or 18 for SQL Server

SETUP
  1. Copy this folder to the target server
     Example: C:\Program Files\chatbot-api\

  2. Copy .env.example to .env and fill in values:
       copy .env.example .env
       notepad .env

  3. Review config\config.yaml

  4. Start as a service with PM2:
       pm2 start pm2-ecosystem.config.js
       pm2 save
       pm2 startup

MANUAL TEST
  Run start.bat

UPDATING
  Replace only these folders/files (do NOT touch python\):
    src\
    config\
    main.py

LOGS
  logs\pm2-out.log
  logs\pm2-error.log
"@
[System.IO.File]::WriteAllText("$PWD\$OutputDir\README.txt", $readme, [System.Text.Encoding]::UTF8)

Write-Host "  OK: start.bat, pm2-ecosystem.config.js, README.txt"

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Build complete: $OutputDir"                -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green

$sizeMB = [math]::Round((Get-ChildItem $OutputDir -Recurse -ErrorAction SilentlyContinue |
    Measure-Object Length -Sum).Sum / 1MB, 0)
Write-Host "  Total size  : $sizeMB MB"
Write-Host "  Python      : $PythonVersion (embedded)"
Write-Host ""
Write-Host "Zip for delivery:" -ForegroundColor Yellow
Write-Host "  Compress-Archive -Path '$OutputDir\*' -DestinationPath 'chatbot-api-v$Version.zip'"
Write-Host ""
