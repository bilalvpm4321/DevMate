@echo off
REM ==============================================================================
REM DevMate - One-command launcher for Windows
REM Usage:
REM   start.bat          Start Backend and Frontend
REM   start.bat --bots   Start Backend, Frontend, and Community Bots
REM ==============================================================================

setlocal
cd /d "%~dp0"

REM Launch PowerShell with execution policy bypass and forward all arguments
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
exit /b %ERRORLEVEL%
