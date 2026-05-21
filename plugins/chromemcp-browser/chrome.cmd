@echo off
REM Windows wrapper: double-click or run from cmd/Explorer.
REM Forwards any args (e.g. -Port 9333) to the PowerShell launcher.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher\Launch-Chrome.ps1" %*
if errorlevel 1 pause
