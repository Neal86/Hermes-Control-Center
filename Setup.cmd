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
set "LIVE_STOP=%TEMP%\hermes-control-center-live-%RANDOM%%RANDOM%.stop"
if exist "%LIVE_STOP%" del /q "%LIVE_STOP%" >nul 2>&1
start "" /b powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Live-Log-Tail.ps1" -StopFile "%LIVE_STOP%"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-Loop-v7.ps1"
set "EXITCODE=%ERRORLEVEL%"
type nul > "%LIVE_STOP%"
timeout /t 1 /nobreak >nul
del /q "%LIVE_STOP%" >nul 2>&1
echo.
if not "%EXITCODE%"=="0" (
  echo Hermes Control Center Setup ended with exit code %EXITCODE%.
) else (
  echo Hermes Control Center Setup closed.
)
pause
exit /b %EXITCODE%
