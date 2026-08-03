# Local development launcher.
# Steps:
# 1. Resolve the project root.
# 2. Prefer the virtual environment Python.
# 3. Load optional private local environment variables.
# 4. Set local development environment variables.
# 5. Run app.py directly.

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$localEnvFile = Join-Path $projectRoot ".env.local"

function Import-LocalEnvironmentFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }

        $parts = $line.Split("=", 2)
        $name = $parts[0].Trim()
        if ($parts.Count -ne 2 -or $name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            throw "Invalid environment entry in ${Path}: $rawLine"
        }

        $value = $parts[1].Trim()
        if (
            $value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or
             ($value.StartsWith("'") -and $value.EndsWith("'")))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

if (Test-Path $venvPython) {
    $pythonExe = $venvPython
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $pythonExe = if ($pythonCommand) { $pythonCommand.Path } else { $null }
    if (-not $pythonExe) {
        throw "Python was not found. Create .venv first or install Python, then try again."
    }
}

Import-LocalEnvironmentFile -Path $localEnvFile

$env:LOCAL_DEV = "1"
$env:FLASK_DEBUG = "true"
$env:FLASK_RUN_HOST = "127.0.0.1"
$env:FLASK_RUN_PORT = "5001"
$env:FLASK_AUTO_RELOAD = "true"
$env:PYTHONPATH = $projectRoot

Write-Host "Local development mode is enabled." -ForegroundColor Cyan
Write-Host "Project root: $projectRoot"
Write-Host "Python: $pythonExe"
Write-Host "Open: http://127.0.0.1:5001" -ForegroundColor Green
if ($env:HERMES_API_URL) {
    Write-Host "Hermes API: configured" -ForegroundColor Green
} else {
    Write-Host "Hermes API: mock mode (.env.local is not configured)" -ForegroundColor Yellow
}
Write-Host ""

Push-Location $projectRoot
& $pythonExe -m backend.core.app
Pop-Location
