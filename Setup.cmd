@echo off
setlocal
cd /d "%~dp0"
echo Hermes Control Center Setup is starting...
echo Checking local installation and latest versions. This may take a few seconds.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Normalize-Dashboard-Manifest.ps1"
if not "%ERRORLEVEL%"=="0" (
  echo Failed to normalize Dashboard manifest.
  pause
  exit /b %ERRORLEVEL%
)

rem IMPORTANT: do not start Live-Log-Tail.ps1 with `start /b` here.
rem A background PowerShell sharing this console also inherits the console input
rem handle and can race with Read-Host in Setup-Loop-v7.ps1. That caused the
rem menu to receive an empty choice immediately after Dashboard launch and then
rem treat the user's `5` as input for the following pause prompt.
rem Setup-Loop already prints each operation log itself when HCC_LIVE_LOG_TAIL
rem is not set, so keep the interactive console single-owner and deterministic.
set "HCC_LIVE_LOG_TAIL="

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-Loop-v7.ps1"
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" (
  echo Hermes Control Center Setup ended with exit code %EXITCODE%.
) else (
  echo Hermes Control Center Setup closed.
)
pause
exit /b %EXITCODE%
