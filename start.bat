@echo off
setlocal
cd /d "%~dp0"
title MoonDownloader v16

:: Find a working Python -- test each candidate actually runs
set "PY="
py --version >nul 2>&1 && set "PY=py"
if not defined PY (python --version >nul 2>&1 && set "PY=python")
if not defined PY (python3 --version >nul 2>&1 && set "PY=python3")
if not defined PY (
    echo [ERROR] Python not found. Install Python 3.10+ from https://www.python.org
    echo         Tick "Add Python to PATH" during the installation.
    pause
    exit /b 1
)

echo Python found: %PY%

:: Engine dependencies. The GUI has none: it runs in Edge/Chrome via --app.
%PY% -c "import aiohttp, playwright, curl_cffi" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    %PY% -m pip install -r requirements.txt || goto :err
)

:: Chromium is only the datanodes fallback (Playwright); fuckingfast is pure HTTP
if not exist "%LOCALAPPDATA%\ms-playwright" (
    echo Installing the Chromium browser...
    %PY% -m playwright install chromium || goto :err
)

:: moon_bridge opens a server on 127.0.0.1 and launches Edge in app mode.
:: pythonw = no console window behind the app.
pyw moon_bridge.py >nul 2>&1 && exit /b 0
pythonw moon_bridge.py >nul 2>&1 && exit /b 0
start "" %PY% moon_bridge.py
exit /b 0

:err
echo [ERROR] Installation failed.
pause
exit /b 1
