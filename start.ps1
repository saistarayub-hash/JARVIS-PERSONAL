# JARVIS — run it now (Windows PowerShell).
#
#   powershell -ExecutionPolicy Bypass -File start.ps1
#   $env:JARVIS_KEY="thk_live_..."; powershell -ExecutionPolicy Bypass -File start.ps1
#
# Clones the repo to %USERPROFILE%\jarvis, makes a venv, installs deps,
# sets up the Token Harbor brain if a key is given, starts the core.
# Autostart afterwards:  .venv\Scripts\python -m jarvis.cli install
$ErrorActionPreference = "Stop"
$Repo   = if ($env:JARVIS_REPO)   { $env:JARVIS_REPO }   else { "https://github.com/saistarayub-hash/JARVIS-PERSONAL" }
$Branch = if ($env:JARVIS_BRANCH) { $env:JARVIS_BRANCH } else { "main" }
$Dir    = if ($env:JARVIS_DIR)    { $env:JARVIS_DIR }    else { "$env:USERPROFILE\jarvis" }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "git is required — install from git-scm.com and re-run." -ForegroundColor Red; exit 1 }
if (Test-Path "$Dir\.git") {
    Write-Host "jarvis-setup: updating $Dir" -ForegroundColor Cyan
    git -C $Dir fetch origin $Branch | Out-Null
    git -C $Dir checkout $Branch | Out-Null
    git -C $Dir merge --ff-only FETCH_HEAD | Out-Null
} else {
    Write-Host "jarvis-setup: cloning $Repo -> $Dir" -ForegroundColor Cyan
    git clone -b $Branch $Repo $Dir
}
Set-Location $Dir

$Py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $Py) { $Py = (Get-Command py -ErrorAction SilentlyContinue) }
if (-not $Py) { Write-Host "Python 3.10+ required (python.org — tick 'add to PATH')" -ForegroundColor Red; exit 1 }

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "jarvis-setup: creating venv + installing deps" -ForegroundColor Cyan
    & $Py.Source -m venv .venv
}
$VPY = ".venv\Scripts\python.exe"
& $VPY -m pip install -q --upgrade pip
& $VPY -m pip install -q -r requirements.txt

if (-not (Test-Path "config.yaml")) { Copy-Item "config.example.yaml" "config.yaml" }
if ($env:JARVIS_KEY) {
    & $VPY scripts\set_llm_key.py $env:JARVIS_KEY
} else {
    Write-Host "jarvis-setup: no JARVIS_KEY — rule brain (set one any time: .venv\Scripts\python scripts\set_llm_key.py thk_live_...)" -ForegroundColor Yellow
}

Write-Host "jarvis-setup: starting core — UI at http://127.0.0.1:8595" -ForegroundColor Cyan
& $VPY run.py --no-voice
