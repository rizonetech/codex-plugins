@echo off
REM Self-elevating wrapper for Setup-WSL-Portproxy.ps1.
REM Usage:
REM   Setup-Bridge.cmd           - install the bridge (idempotent; cleans up any stale entries)
REM   Setup-Bridge.cmd /refresh  - explicit drift-recovery; logs detected drift
REM   Setup-Bridge.cmd /remove   - tear it down
REM
REM For non-default ports, invoke the script directly:
REM   powershell -ExecutionPolicy Bypass -File launcher\Setup-WSL-Portproxy.ps1 -Port 9333

setlocal EnableExtensions

set "PS_ARGS="
if /I "%~1"=="/remove"  set "PS_ARGS=-Remove"
if /I "%~1"=="/refresh" set "PS_ARGS=-Refresh"

REM Are we admin?
NET SESSION >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Requesting administrator privileges...
    powershell.exe -NoProfile -Command "Start-Process -Verb RunAs -FilePath cmd.exe -ArgumentList '/c %~dpnx0 %*'"
    exit /b
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher\Setup-WSL-Portproxy.ps1" %PS_ARGS%
echo.
echo Press any key to close this window . . .
pause >nul
