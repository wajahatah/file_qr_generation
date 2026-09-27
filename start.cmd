@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ===========================================================================
REM  QR File Share - one-click launcher
REM
REM    start.cmd            run on localhost:8000
REM    start.cmd lan        bind to the LAN so a real phone can scan the QR
REM    start.cmd 9000       run on a different port
REM    start.cmd lan 9000   both
REM
REM  Safe to run repeatedly: it reuses the existing .venv and never overwrites
REM  an existing .env.
REM ===========================================================================

set "HOSTBIND=127.0.0.1"
set "PORT=8000"
set "LANMODE="

for %%A in (%1 %2) do (
    if /i "%%A"=="lan" (
        set "LANMODE=1"
    ) else (
        set "PORT=%%A"
    )
)

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
"%VENV_PY%" -c "import fastapi, uvicorn, qrcode, jinja2, pydantic_settings" >nul 2>&1
if errorlevel 1 (
    echo [2/4] Installing dependencies. First run only - this takes a minute...
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
"%VENV_PY%" tools\setup_helper.py bootstrap %PORT%
if errorlevel 1 (
    echo  ERROR: could not prepare .env
    pause
    exit /b 1
)

REM --- 4. launch --------------------------------------------------------------
REM BASE_URL is baked into every QR at generation time, so it must match the origin
REM the server is really reachable at. The helper keeps a production BASE_URL from
REM .env, but re-derives a local one from the port actually in use -- otherwise a QR
REM generated after "start.cmd 9000" would still encode yesterday's port.
if defined LANMODE (
    for /f "usebackq tokens=*" %%i in (`"%VENV_PY%" tools\setup_helper.py baseurl %PORT% lan`) do set "BASE_URL=%%i"
    set "HOSTBIND=0.0.0.0"
    echo [4/4] Starting on the local network...
    echo.
    echo       Your phone must be on the SAME Wi-Fi network.
    echo       Windows Firewall may ask for permission - click Allow.
) else (
    for /f "usebackq tokens=*" %%i in (`"%VENV_PY%" tools\setup_helper.py baseurl %PORT%`) do set "BASE_URL=%%i"
    echo [4/4] Starting on localhost...
)

"%VENV_PY%" tools\setup_helper.py summary "!BASE_URL!"

echo  ----------------------------------------------------
echo   Press CTRL+C to stop the server.
echo  ----------------------------------------------------
echo.

"%VENV_PY%" -m uvicorn app.main:app --host %HOSTBIND% --port %PORT%

echo.
echo  Server stopped.
pause
