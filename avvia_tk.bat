@echo off
cd /d "%~dp0"

:: Find a working Python -- test each candidate actually runs
set "PY="
py --version >nul 2>&1 && set "PY=py"
if not defined PY (python --version >nul 2>&1 && set "PY=python")
if not defined PY (python3 --version >nul 2>&1 && set "PY=python3")
if not defined PY (
    echo [ERROR] Python not found. Install Python 3.10+ from https://www.python.org
    echo         Make sure to tick "Add Python to PATH" during the installation.
    pause
    exit /b 1
)

echo Python found: %PY%

%PY% -c "import aiohttp, playwright, curl_cffi, PIL" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    %PY% -m pip install -r requirements.txt || goto :err
    %PY% -m playwright install chromium || goto :err
)

if not exist "%LOCALAPPDATA%\ms-playwright" (
    echo Installing the Chromium browser...
    %PY% -m playwright install chromium || goto :err
)

:: Launch GUI without console window
pyw gen_1.py >nul 2>&1 && exit /b 0
pythonw gen_1.py >nul 2>&1 && exit /b 0
start "" %PY% gen_1.py
exit /b 0

:err
echo [ERROR] Installation failed.
pause
exit /b 1
