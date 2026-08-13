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
