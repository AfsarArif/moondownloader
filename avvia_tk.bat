@echo off
cd /d "%~dp0"

:: Find a working Python — test each candidate actually runs
set "PY="
py --version >nul 2>&1 && set "PY=py"
if not defined PY (python --version >nul 2>&1 && set "PY=python")
if not defined PY (python3 --version >nul 2>&1 && set "PY=python3")
if not defined PY (
    echo [ERRORE] Python non trovato. Installa Python 3.10+ da https://www.python.org
    echo          Assicurati di spuntare "Add Python to PATH" durante l'installazione.
    pause
    exit /b 1
)

echo Python trovato: %PY%

%PY% -c "import aiohttp, playwright, curl_cffi, PIL" >nul 2>&1
if errorlevel 1 (
    echo Installazione dipendenze...
    %PY% -m pip install -r requirements.txt || goto :err
    %PY% -m playwright install chromium || goto :err
)

if not exist "%LOCALAPPDATA%\ms-playwright" (
    echo Installazione browser Chromium...
    %PY% -m playwright install chromium || goto :err
)

:: Launch GUI without console window
pyw gen_1.py >nul 2>&1 && exit /b 0
pythonw gen_1.py >nul 2>&1 && exit /b 0
start "" %PY% gen_1.py
exit /b 0

:err
echo [ERRORE] Installazione fallita.
pause
exit /b 1
