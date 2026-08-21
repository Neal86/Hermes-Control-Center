@echo off
setlocal
cd /d "%~dp0"
echo Hermes Control Center Setup is starting...
echo Loading the latest Setup runtime. This may take a few seconds.
echo.

rem Keep this console single-owner. Never run a background log tail that
rem inherits stdin, because it can consume Read-Host keystrokes.
set "HCC_LIVE_LOG_TAIL="

set "BOOTSTRAP=%~dp0Setup-Bootstrap.ps1"
if not exist "%BOOTSTRAP%" (
  echo Missing Setup-Bootstrap.ps1.
  echo Please download the latest Hermes Control Center Setup package once.
  pause
  exit /b 2
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%"
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" (
  echo Hermes Control Center Setup ended with exit code %EXITCODE%.
) else (
  echo Hermes Control Center Setup closed.
)
pause
exit /b %EXITCODE%
