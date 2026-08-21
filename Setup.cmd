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

rem Keep the interactive console single-owner. Live-Log-Tail.ps1 previously
rem inherited this console input handle and could consume Read-Host keystrokes.
set "HCC_LIVE_LOG_TAIL="

set "SETUP_LOOP=%~dp0Setup-Loop-v8.ps1"
if not exist "%SETUP_LOOP%" set "SETUP_LOOP=%~dp0Setup-Loop-v7.ps1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SETUP_LOOP%"
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" (
  echo Hermes Control Center Setup ended with exit code %EXITCODE%.
) else (
  echo Hermes Control Center Setup closed.
)
pause
exit /b %EXITCODE%
