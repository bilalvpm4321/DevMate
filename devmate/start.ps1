# ==============================================================================
# DevMate - One-Command Launcher (Windows / PowerShell)
# Starts FastAPI backend, React+Vite frontend, and optional community bots.
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$bots = $false
)

# Also support raw --bots argument passed from batch files or PowerShell
if ($args -contains "--bots" -or $args -contains "-bots") {
    $bots = $true
}

# Ensure script runs from the repository root directory
$rootDir = $PSScriptRoot
if (-not $rootDir) { $rootDir = (Get-Location).Path }
Set-Location -LiteralPath $rootDir

# Track spawned background processes for clean termination on exit
$processes = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
$script:isCleaningUp = $false

# ------------------------------------------------------------------------------
# Process cleanup handler: kills all processes and their child trees
# ------------------------------------------------------------------------------
function Invoke-Cleanup {
    if ($script:isCleaningUp) { return }
    $script:isCleaningUp = $true

    Write-Host "`n[DevMate] Stopping all services cleanly..." -ForegroundColor Yellow
    foreach ($p in $processes) {
        try {
            if ($p -and -not $p.HasExited) {
                # taskkill /F /T terminates the target process and its full process tree
                taskkill.exe /F /T /PID $p.Id 2>$null | Out-Null
            }
        } catch {}
    }
    Write-Host "[DevMate] All processes stopped. Goodbye!" -ForegroundColor Green
}

# Register Ctrl+C / break handler if supported by host console
try {
    [Console]::TreatControlCAsInput = $false
    $cancelHandler = [ConsoleCancelEventHandler]{
        param($sender, $eventArgs)
        $eventArgs.Cancel = $true
        Invoke-Cleanup
        exit 0
    }
    [Console]::add_CancelKeyPress($cancelHandler)
} catch {}

# ------------------------------------------------------------------------------
# 1. Check Python (>= 3.10)
# ------------------------------------------------------------------------------
function Find-Python {
    $candidates = @("python", "python3", "py -3")
    foreach ($cand in $candidates) {
        try {
            $parts = $cand -split " "
            $exe = $parts[0]
            $argsList = if ($parts.Length -gt 1) { "$($parts[1]) --version" } else { "--version" }
            $psi = New-Object System.Diagnostics.ProcessStartInfo
            $psi.FileName = $exe
            $psi.Arguments = $argsList
            $psi.RedirectStandardOutput = $true
            $psi.RedirectStandardError = $true
            $psi.UseShellExecute = $false
            $psi.CreateNoWindow = $true

            $proc = [System.Diagnostics.Process]::Start($psi)
            $out = ($proc.StandardOutput.ReadToEnd() + " " + $proc.StandardError.ReadToEnd()).Trim()
            $proc.WaitForExit(3000) | Out-Null

            if ($proc.ExitCode -eq 0 -and $out -match "Python\s+(\d+)\.(\d+)") {
                $major = [int]$matches[1]
                $minor = [int]$matches[2]
                if ($major -eq 3 -and $minor -ge 10) {
                    return $cand
                }
            }
        } catch {}
    }
    return $null
}

$pythonCmd = Find-Python
if (-not $pythonCmd) {
    Write-Host "`n[ERROR] Python 3.10+ is required, but was not found." -ForegroundColor Red
    Write-Host "Please download and install Python 3.10+ from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "NOTE: During installation, be sure to check 'Add python.exe to PATH'." -ForegroundColor Yellow
    Write-Host "If already installed, make sure Windows App Execution Aliases for python.exe are disabled.`n" -ForegroundColor DarkGray
    exit 1
}

# ------------------------------------------------------------------------------
# 2. Check Node.js (>= 18)
# ------------------------------------------------------------------------------
function Check-Node {
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "node"
        $psi.Arguments = "-v"
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true

        $proc = [System.Diagnostics.Process]::Start($psi)
        $out = ($proc.StandardOutput.ReadToEnd() + " " + $proc.StandardError.ReadToEnd()).Trim()
        $proc.WaitForExit(3000) | Out-Null

        if ($proc.ExitCode -eq 0 -and $out -match "^v(\d+)\.") {
            $major = [int]$matches[1]
            if ($major -ge 18) {
                return $out
            }
        }
    } catch {}
    return $null
}

$nodeVersion = Check-Node
if (-not $nodeVersion) {
    Write-Host "`n[ERROR] Node.js 18+ is required, but was not found." -ForegroundColor Red
    Write-Host "Please download and install Node.js (LTS recommended) from: https://nodejs.org/`n" -ForegroundColor Yellow
    exit 1
}

# ------------------------------------------------------------------------------
# 3. Check or create .env file
# ------------------------------------------------------------------------------
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "[DevMate] Created .env from .env.example" -ForegroundColor Cyan
        Write-Host "[DevMate] Please add your GEMINI_API_KEY in .env (get a free key at https://aistudio.google.com/apikey)" -ForegroundColor Yellow
    } else {
        Write-Host "[WARN] Neither .env nor .env.example found." -ForegroundColor Yellow
    }
}

# Helper to read values from .env file
function Get-EnvConfigValue([string]$key) {
    if (Test-Path ".env") {
        foreach ($line in (Get-Content ".env")) {
            $trimmed = $line.Trim()
            if ($trimmed.StartsWith("#") -or -not ($trimmed -match "^\s*$key\s*=\s*(.*)$")) { continue }
            $val = $matches[1].Trim()
            if (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'"))) {
                $val = $val.Substring(1, $val.Length - 2)
            }
            return $val
        }
    }
    return ""
}

# ------------------------------------------------------------------------------
# 4. Backend setup: virtualenv & requirements.txt
# ------------------------------------------------------------------------------
$venvDir = Join-Path $rootDir "backend\.venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "[backend] Creating virtual environment in backend/.venv..." -ForegroundColor Cyan
    $parts = $pythonCmd -split " "
    $pyExe = $parts[0]
    $pyArgs = if ($parts.Length -gt 1) { "$($parts[1]) -m venv backend\.venv" } else { "-m venv backend\.venv" }
    $p = Start-Process -FilePath $pyExe -ArgumentList $pyArgs -WorkingDirectory $rootDir -NoNewWindow -Wait -PassThru
    if ($p.ExitCode -ne 0) {
        Write-Host "[ERROR] Failed to create Python virtual environment in backend/.venv" -ForegroundColor Red
        exit 1
    }
}

$backendStamp = Join-Path $venvDir ".requirements_installed"
$reqFile = Join-Path $rootDir "backend\requirements.txt"
$needInstall = $true

if (Test-Path $backendStamp) {
    $stampTime = (Get-Item $backendStamp).LastWriteTimeUtc
    $reqTime = (Get-Item $reqFile).LastWriteTimeUtc
    if ($stampTime -ge $reqTime) {
        $needInstall = $false
    }
}

if ($needInstall) {
    Write-Host "[backend] Installing backend dependencies from requirements.txt..." -ForegroundColor Cyan
    $p = Start-Process -FilePath $venvPython -ArgumentList "-m pip install -r backend\requirements.txt" -WorkingDirectory $rootDir -NoNewWindow -Wait -PassThru
    if ($p.ExitCode -ne 0) {
        Write-Host "[ERROR] Failed to install backend requirements." -ForegroundColor Red
        exit 1
    }
    Set-Content -Path $backendStamp -Value (Get-Date).ToString("o")
}

# ------------------------------------------------------------------------------
# 5. Frontend setup: npm install if node_modules missing
# ------------------------------------------------------------------------------
$frontendDir = Join-Path $rootDir "frontend"
$nodeModulesDir = Join-Path $frontendDir "node_modules"

if (-not (Test-Path $nodeModulesDir)) {
    Write-Host "[frontend] Installing frontend dependencies (npm install)..." -ForegroundColor Green
    $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm install" -WorkingDirectory $frontendDir -NoNewWindow -Wait -PassThru
    if ($p.ExitCode -ne 0) {
        Write-Host "[ERROR] Failed to install frontend npm packages." -ForegroundColor Red
        exit 1
    }
}

# ------------------------------------------------------------------------------
# 6. Bots setup (optional --bots flag)
# ------------------------------------------------------------------------------
$startDiscordBot = $false
$startTelegramBot = $false

if ($bots) {
    $botsDir = Join-Path $rootDir "bots"
    $botsStamp = Join-Path $venvDir ".bots_requirements_installed"
    $botsReqFile = Join-Path $botsDir "requirements.txt"
    $needBotsInstall = $true

    if (Test-Path $botsStamp) {
        $stampTime = (Get-Item $botsStamp).LastWriteTimeUtc
        $reqTime = (Get-Item $botsReqFile).LastWriteTimeUtc
        if ($stampTime -ge $reqTime) {
            $needBotsInstall = $false
        }
    }

    if ($needBotsInstall) {
        Write-Host "[bots] Installing bots dependencies from bots/requirements.txt..." -ForegroundColor Magenta
        $p = Start-Process -FilePath $venvPython -ArgumentList "-m pip install -r bots\requirements.txt" -WorkingDirectory $rootDir -NoNewWindow -Wait -PassThru
        if ($p.ExitCode -ne 0) {
            Write-Host "[ERROR] Failed to install bots requirements." -ForegroundColor Red
            exit 1
        }
        Set-Content -Path $botsStamp -Value (Get-Date).ToString("o")
    }

    $discordToken = Get-EnvConfigValue "DISCORD_TOKEN"
    if ($discordToken -and $discordToken -ne "change-me" -and $discordToken -ne "") {
        $startDiscordBot = $true
    } else {
        Write-Host "[WARN] DISCORD_TOKEN is empty in .env - skipping Discord bot." -ForegroundColor Yellow
    }

    $telegramToken = Get-EnvConfigValue "TELEGRAM_TOKEN"
    if ($telegramToken -and $telegramToken -ne "change-me" -and $telegramToken -ne "") {
        $startTelegramBot = $true
    } else {
        Write-Host "[WARN] TELEGRAM_TOKEN is empty in .env - skipping Telegram bot." -ForegroundColor Yellow
    }
}

# ------------------------------------------------------------------------------
# Helper: Start background process with prefixed console logs
# ------------------------------------------------------------------------------
function Start-PrefixedService {
    param(
        [string]$Prefix,
        [ConsoleColor]$Color,
        [string]$FileName,
        [string]$Arguments,
        [string]$WorkingDirectory
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FileName
    $psi.Arguments = $Arguments
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    $p.EnableRaisingEvents = $true

    $handler = {
        if ($EventArgs.Data) {
            Write-Host "[$($Event.MessageData.Prefix)] " -ForegroundColor $($Event.MessageData.Color) -NoNewline
            Write-Host $EventArgs.Data
        }
    }
    $meta = @{ Prefix = $Prefix; Color = $Color }
    Register-ObjectEvent -InputObject $p -EventName "OutputDataReceived" -Action $handler -MessageData $meta | Out-Null
    Register-ObjectEvent -InputObject $p -EventName "ErrorDataReceived" -Action $handler -MessageData $meta | Out-Null

    $p.Start() | Out-Null
    $p.BeginOutputReadLine()
    $p.BeginErrorReadLine()

    [void]$processes.Add($p)
    return $p
}

# ------------------------------------------------------------------------------
# 7. Start Backend, Frontend, and Bots
# ------------------------------------------------------------------------------
Write-Host "`n[DevMate] Starting backend and frontend services..." -ForegroundColor Cyan

# Backend (runs uvicorn from backend directory)
$backendDir = Join-Path $rootDir "backend"
Start-PrefixedService -Prefix "backend" -Color Cyan -FileName $venvPython -Arguments "-m uvicorn app.main:app --reload --port 8000" -WorkingDirectory $backendDir

# Frontend (runs npm run dev from frontend directory)
Start-PrefixedService -Prefix "frontend" -Color Green -FileName "cmd.exe" -Arguments "/c npm run dev" -WorkingDirectory $frontendDir

# Optional Community Bots
if ($startDiscordBot) {
    $botsDir = Join-Path $rootDir "bots"
    Start-PrefixedService -Prefix "discord" -Color Magenta -FileName $venvPython -Arguments "discord_bot.py" -WorkingDirectory $botsDir
}

if ($startTelegramBot) {
    $botsDir = Join-Path $rootDir "bots"
    Start-PrefixedService -Prefix "telegram" -Color DarkYellow -FileName $venvPython -Arguments "telegram_bot.py" -WorkingDirectory $botsDir
}

# ------------------------------------------------------------------------------
# 8. Ready banner with URLs
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "==============================================================" -ForegroundColor Green
Write-Host "  DevMate is running!" -ForegroundColor Green
Write-Host "  - App:      http://localhost:5173" -ForegroundColor White
Write-Host "  - API docs: http://localhost:8000/docs" -ForegroundColor White
if ($startDiscordBot) {  Write-Host "  - Bot:      Discord bot active" -ForegroundColor Magenta }
if ($startTelegramBot) { Write-Host "  - Bot:      Telegram bot active" -ForegroundColor DarkYellow }
Write-Host "  Press Ctrl+C to stop all services cleanly." -ForegroundColor Gray
Write-Host "==============================================================" -ForegroundColor Green
Write-Host ""

# ------------------------------------------------------------------------------
# 9. Main wait loop: keep running until Ctrl+C or all processes exit
# ------------------------------------------------------------------------------
try {
    while ($true) {
        Start-Sleep -Milliseconds 500
        $runningCount = 0
        foreach ($p in $processes) {
            if (-not $p.HasExited) { $runningCount++ }
        }
        if ($runningCount -eq 0) { break }
    }
} finally {
    Invoke-Cleanup
}
