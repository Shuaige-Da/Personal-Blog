# Local development launcher.
# Steps:
# 1. Resolve the project root.
# 2. Prefer the virtual environment Python.
# 3. Set local development environment variables.
# 4. Run app.py directly.

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (Test-Path $venvPython) {
    $pythonExe = $venvPython
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $pythonExe = if ($pythonCommand) { $pythonCommand.Path } else { $null }
    if (-not $pythonExe) {
        throw "Python was not found. Create .venv first or install Python, then try again."
    }
}

$env:LOCAL_DEV = "1"
$env:FLASK_DEBUG = "true"
$env:FLASK_RUN_HOST = "127.0.0.1"
$env:FLASK_RUN_PORT = "5000"
$env:FLASK_AUTO_RELOAD = "true"
$env:PYTHONPATH = $projectRoot

Write-Host "Local development mode is enabled." -ForegroundColor Cyan
Write-Host "Project root: $projectRoot"
Write-Host "Python: $pythonExe"
Write-Host "Open: http://127.0.0.1:5000" -ForegroundColor Green
Write-Host ""

Push-Location $projectRoot
& $pythonExe -m backend.core.app
Pop-Location
