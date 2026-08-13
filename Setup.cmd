@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-Hermes-Control-Center.ps1"
set "EXITCODE=%ERRORLEVEL%"
echo.
if "%EXITCODE%"=="0" (
  echo Hermes Control Center Setup completed successfully.
) else (
  echo Hermes Control Center Setup failed with exit code %EXITCODE%.
)
echo.
pause
exit /b %EXITCODE%
