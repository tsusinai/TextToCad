@echo off
title TextToCad Launcher
echo ========================================================
echo   Starting TextToCad (Backend + Frontend)
echo ========================================================
cd /d "%~dp0"

echo [1/2] Starting Backend service on port 8787...
start "TextToCad Backend" cmd /k "cd /d "%~dp0backend" && call .venv\Scripts\activate.bat && python -m uvicorn app:app --host 0.0.0.0 --port 8787 --env-file .env --reload"

timeout /t 3 /nobreak >nul

echo [2/2] Starting Frontend static server on port 8000...
start "TextToCad Frontend" cmd /k "cd /d "%~dp0" && start http://localhost:8000 && backend\.venv\Scripts\python.exe -m http.server 8000"

echo ========================================================
echo Both services started!
echo Frontend: http://localhost:8000
echo Backend:  http://localhost:8787
echo ========================================================
