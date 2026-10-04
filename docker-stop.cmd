@echo off
cd /d "%~dp0"

REM ===========================================================================
REM  QR File Share - stop the Docker app
REM
REM  Stops the app. Nothing is deleted: QR codes, settings and the Google sign-in
REM  are kept, and docker-start.cmd brings it all back.
REM
REM  While stopped, expired QR codes are not removed from Google Drive.
REM ===========================================================================

docker info >nul 2>&1
if errorlevel 1 (
    echo  Docker Desktop is not running, so the app is not running either.
    pause
    exit /b 0
)

docker compose stop
echo.
echo  Stopped. Your QR codes and settings are kept.
echo  Start again with docker-start.cmd
echo.
pause
