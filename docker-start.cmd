@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ===========================================================================
REM  QR File Share - start in Docker
REM
REM    docker-start.cmd          start (or update) the app, open it in the browser
REM    docker-start.cmd 9000     use a different port
REM
REM  Needs Docker Desktop running. Does NOT need Python on this laptop.
REM  The app keeps running in the background after this window closes, and comes
REM  back by itself whenever Docker Desktop starts. Stop it with docker-stop.cmd.
REM
REM  Run this again after changing the laptop's time zone (e.g. travelling): it
REM  passes the laptop's current zone to the app.
REM
REM  Works in two places:
REM    the project folder (has a Dockerfile)    builds the app from source
REM    a kit made by make-kit.cmd (has a .tar)   loads the ready-built app; never
REM                                              builds, never downloads
REM ===========================================================================

set "APP_PORT=8000"
if not "%~1"=="" set "APP_PORT=%~1"

echo.
echo  ====================================================
echo    QR File Share  (Docker)
echo  ====================================================
echo.

REM --- 1. Docker Desktop running? ---------------------------------------------
docker info >nul 2>&1
if errorlevel 1 (
    echo  Docker Desktop is not running.
    echo  Start Docker Desktop, wait until it says "Engine running", then run this again.
    echo.
    pause
    exit /b 1
)
echo [1/5] Docker Desktop is running.

REM --- 2. Google key file -----------------------------------------------------
if not exist "client_secret.json" (
    echo.
    echo  client_secret.json is missing.
    echo  Put the Google key file next to docker-start.cmd first.
    echo  See HOW-TO-RUN.md, Steps 2 and 3.
    echo.
    pause
    exit /b 1
)
echo [2/5] Google key file found.

REM --- 3. .env with an admin token ----------------------------------------------
if exist ".env" (
    echo [3/5] .env found - leaving your settings untouched.
) else (
    REM Windows' cryptographic random generator; 32 bytes, URL-safe text.
    for /f "usebackq delims=" %%t in (`powershell -NoProfile -Command "$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b).TrimEnd('=').Replace('+','-').Replace('/','_')"`) do set "NEWTOKEN=%%t"
    if not defined NEWTOKEN (
        echo  ERROR: could not generate an admin token.
        pause
        exit /b 1
    )
    powershell -NoProfile -Command "(Get-Content -Raw '.env.example') -replace '(?m)^ADMIN_TOKEN=.*$', ('ADMIN_TOKEN=' + $env:NEWTOKEN) | Set-Content -NoNewline -Encoding ascii '.env'"
    if not exist ".env" (
        echo  ERROR: could not create .env
        pause
        exit /b 1
    )
    echo [3/5] Created .env with a freshly generated admin token.
)

REM --- 4. The laptop's time zone ------------------------------------------------
for /f "usebackq delims=" %%z in (`powershell -NoProfile -Command "(Get-TimeZone).Id"`) do set "HOST_WINDOWS_TZ=%%z"
echo [4/5] Laptop time zone: !HOST_WINDOWS_TZ!

REM --- 5. Start -----------------------------------------------------------------------
if exist "Dockerfile" (
    echo [5/5] Starting. The first time this downloads and builds - a few minutes...
    docker compose up -d --build
) else (
    call :load_kit_image
    if errorlevel 1 (
        echo.
        pause
        exit /b 1
    )
    echo [5/5] Starting...
    docker compose up -d
)
if errorlevel 1 (
    echo.
    echo  ERROR: the app could not be started. The messages above say why.
    echo.
    pause
    exit /b 1
)

REM Wait on 127.0.0.1, not localhost: localhost tries IPv6 (::1) first, and Docker
REM Desktop's port forwarding takes ~2 s to reject IPv6 -- longer than each attempt's
REM timeout, so a localhost check never succeeds. Found in the real launcher test.
powershell -NoProfile -Command "for ($i = 0; $i -lt 90; $i++) { try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 ('http://127.0.0.1:' + $env:APP_PORT + '/healthz')).StatusCode -eq 200) { exit 0 } } catch {} ; Start-Sleep -Milliseconds 500 } ; exit 1"
if errorlevel 1 (
    echo.
    echo  The app did not answer. Recent log:
    docker compose logs --tail 30 app
    echo.
    pause
    exit /b 1
)

set "TOKEN="
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if /i "%%a"=="ADMIN_TOKEN" set "TOKEN=%%b"
)

start "" "http://localhost:%APP_PORT%/admin"

echo.
echo  ----------------------------------------------------
echo   App          :  http://localhost:%APP_PORT%/admin
echo   Admin token  :  !TOKEN!
echo  ----------------------------------------------------
echo   The app runs in the background. You can close this window.
echo   To stop it: double-click docker-stop.cmd
echo.
pause
exit /b 0


REM ===========================================================================
REM  Kit only: load the app image for this laptop's processor, unless this
REM  version is already loaded. The kit ships one image per processor type.
REM ===========================================================================
:load_kit_image
set "KIT_VERSION="
if exist "VERSION" set /p KIT_VERSION=<VERSION
if not defined KIT_VERSION (
    echo  ERROR: this folder has neither a Dockerfile nor a kit VERSION file.
    echo  Unzip the whole kit again, then run docker-start.cmd from that folder.
    exit /b 1
)

set "CPU="
if /i "%PROCESSOR_ARCHITECTURE%"=="AMD64" set "CPU=amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "CPU=arm64"
REM A 32-bit window on 64-bit Windows reports the real processor here.
if /i "%PROCESSOR_ARCHITEW6432%"=="AMD64" set "CPU=amd64"
if /i "%PROCESSOR_ARCHITEW6432%"=="ARM64" set "CPU=arm64"
if not defined CPU (
    echo  This laptop's processor is not supported: %PROCESSOR_ARCHITECTURE%.
    echo  The kit supports Intel, AMD and ARM 64-bit laptops.
    exit /b 1
)

docker image inspect qr-file-share:%KIT_VERSION% >nul 2>&1
if not errorlevel 1 (
    echo        App version %KIT_VERSION% is already loaded.
    exit /b 0
)
if not exist "qr-file-share-image-%CPU%.tar" (
    echo  ERROR: this kit has no app image for %CPU% laptops - qr-file-share-image-%CPU%.tar.
    echo  Use a kit made for %CPU%, or run docker-start.cmd from the project folder,
    echo  which builds the app on this laptop.
    exit /b 1
)
echo        Loading app version %KIT_VERSION% for this %CPU% laptop - about a minute...
docker load -i "qr-file-share-image-%CPU%.tar"
if errorlevel 1 (
    echo  ERROR: could not load the app into Docker.
    exit /b 1
)
exit /b 0
