@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ===========================================================================
REM  QR File Share - one-click launcher
REM
REM    start.cmd          start the app and open it in the browser
REM    start.cmd 9000     use a different port
REM
REM  The app listens on this laptop only (127.0.0.1). Nothing on the network can
REM  connect to it. QR codes are served by Google Drive, not by this laptop.
REM
REM  Safe to run repeatedly: it reuses the existing .venv and never overwrites
REM  an existing .env.
REM ===========================================================================

set "PORT=8000"
if not "%~1"=="" set "PORT=%~1"

echo.
echo  ====================================================
echo    QR File Share
echo  ====================================================
echo.

set "VENV_PY=.venv\Scripts\python.exe"

REM --- 1. virtual environment -------------------------------------------------
if exist "%VENV_PY%" (
    echo [1/4] Virtual environment found.
) else (
    echo [1/4] Creating virtual environment...
    set "BOOTPY="
    where py >nul 2>&1 && set "BOOTPY=py -3"
    if not defined BOOTPY (
        where python >nul 2>&1 && set "BOOTPY=python"
    )
    if not defined BOOTPY (
        echo.
        echo  ERROR: Python was not found on PATH.
        echo  Install Python 3.11 or newer from https://www.python.org/downloads/
        echo  and tick "Add python.exe to PATH" during setup.
        echo.
        pause
        exit /b 1
    )
    !BOOTPY! -m venv .venv
    if not exist "%VENV_PY%" (
        echo.
        echo  ERROR: could not create the virtual environment.
        echo.
        pause
        exit /b 1
    )
)

REM --- 2. dependencies --------------------------------------------------------
"%VENV_PY%" -c "import fastapi, uvicorn, qrcode, jinja2, pydantic_settings, google_auth_oauthlib, keyring, googleapiclient" >nul 2>&1
if errorlevel 1 (
    echo [2/4] Installing dependencies. This takes a minute the first time...
    "%VENV_PY%" -m pip install --quiet --upgrade pip
    "%VENV_PY%" -m pip install --quiet -r requirements.txt
    if errorlevel 1 (
        echo.
        echo  ERROR: dependency installation failed. Check your internet connection.
        echo.
        pause
        exit /b 1
    )
    echo       Done.
) else (
    echo [2/4] Dependencies OK.
)

REM --- 3. configuration -------------------------------------------------------
"%VENV_PY%" tools\setup_helper.py bootstrap
if errorlevel 1 (
    echo  ERROR: could not prepare .env
    pause
    exit /b 1
)

REM --- 4. launch --------------------------------------------------------------
echo [4/4] Starting...
"%VENV_PY%" tools\setup_helper.py summary %PORT%

echo  ----------------------------------------------------
echo   The app opens in your browser in a moment.
echo   Keep this window open while you use it.
echo   Press CTRL+C here to stop.
echo  ----------------------------------------------------
echo.

REM Opens the browser once the server answers, without holding up the launch.
start "" /b "%VENV_PY%" tools\setup_helper.py openwhenready %PORT%

"%VENV_PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%

echo.
echo  Server stopped.
pause
