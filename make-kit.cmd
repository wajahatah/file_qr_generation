@echo off
cd /d "%~dp0"

REM ===========================================================================
REM  QR File Share - make the portable Docker kit
REM
REM  Run on THIS (development) laptop. Produces dist\qr-file-share-kit-<version>.zip:
REM  copy it to another laptop, unzip, add client_secret.json, double-click
REM  docker-start.cmd. See docs/planning/spec-docker-kit.md.
REM ===========================================================================

if not exist ".venv\Scripts\python.exe" (
    echo  Run start.cmd once first - it prepares Python for this tool.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" tools\make_kit.py
echo.
pause
