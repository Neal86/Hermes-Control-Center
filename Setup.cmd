@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-Hermes-Control-Center.ps1"
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo Hermes Control Center Setup failed with exit code %EXITCODE%.
  pause
)
exit /b %EXITCODE%
