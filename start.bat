@echo off
REM Top-level launcher redirector for DevMate
setlocal
if exist "%~dp0devmate\start.bat" (
    call "%~dp0devmate\start.bat" %*
) else (
    echo Error: Could not find devmate\start.bat
    exit /b 1
)
exit /b %ERRORLEVEL%
