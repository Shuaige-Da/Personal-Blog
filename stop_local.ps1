# Local development stopper.
# The goal is to stop Python and helper shell processes that belong to this project
# without killing unrelated processes on the machine.

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$targetIds = [System.Collections.Generic.HashSet[int]]::new()
$projectStartTimes = [System.Collections.Generic.HashSet[string]]::new()
$projectStartMoments = New-Object System.Collections.Generic.List[datetime]

$projectPythonProcesses = Get-Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.ProcessName -like "python*" -and
        $_.Path -and
        $_.Path -ieq $venvPython
    }

foreach ($process in $projectPythonProcesses) {
    [void]$targetIds.Add($process.Id)
    [void]$projectStartTimes.Add($process.StartTime.ToString("yyyy-MM-dd HH:mm:ss"))
    $projectStartMoments.Add($process.StartTime)
}

$siblingPythonProcesses = Get-Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.ProcessName -like "python*" -and
        $_.Path -and
        $projectStartTimes.Contains($_.StartTime.ToString("yyyy-MM-dd HH:mm:ss"))
    }

foreach ($process in $siblingPythonProcesses) {
    [void]$targetIds.Add($process.Id)
}

$launcherProcesses = Get-Process -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.ProcessName -like "powershell*" -or $_.ProcessName -like "pwsh*") -and
        $_.Id -ne $PID
    }

foreach ($process in $launcherProcesses) {
    foreach ($startMoment in $projectStartMoments) {
        $secondsApart = [math]::Abs((New-TimeSpan -Start $process.StartTime -End $startMoment).TotalSeconds)
        if ($secondsApart -le 30) {
            [void]$targetIds.Add($process.Id)
            break
        }
    }
}

$listenerPids = netstat -ano |
    Select-String "127\.0\.0\.1:5001.*LISTENING|0\.0\.0\.0:5001.*LISTENING|\[::\]:5001.*LISTENING" |
    ForEach-Object {
        if ($_.Line -match "\s+(\d+)\s*$") {
            [int]$matches[1]
        }
    }

foreach ($listenerPid in $listenerPids) {
    try {
        $process = Get-Process -Id $listenerPid -ErrorAction Stop
        if ($process.ProcessName -like "python*") {
            [void]$targetIds.Add($listenerPid)
        }
    } catch {
    }
}

if ($targetIds.Count -eq 0) {
    Write-Host "No local project Python processes were found."
    exit 0
}

$stopped = @()
foreach ($targetId in $targetIds) {
    try {
        Stop-Process -Id $targetId -Force -ErrorAction Stop
        $stopped += $targetId
    } catch {
        Write-Warning "Failed to stop PID ${targetId}: $($_.Exception.Message)"
    }
}

if ($stopped.Count -gt 0) {
    Write-Host ("Stopped project processes: " + ($stopped -join ", ")) -ForegroundColor Green
} else {
    Write-Warning "No processes were stopped."
}
