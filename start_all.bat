@echo off
title TextToCad Launcher
echo ========================================================
echo   Starting TextToCad (Backend + Frontend)
echo ========================================================
cd /d "%~dp0"

echo [1/2] Starting Backend service on port 8787...
start "TextToCad Backend" cmd /k "cd /d "%~dp0backend" && call .venv\Scripts\activate.bat && python -m uvicorn app:app --host 0.0.0.0 --port 8787 --env-file .env --reload"

timeout /t 3 /nobreak >nul

echo [2/2] Starting FORMA React Studio on port 5173...
start "FORMA Frontend" cmd /k "cd /d "%~dp0frontend" && if not exist node_modules call npm install && start http://localhost:5173 && npm run dev -- --host 0.0.0.0"

echo ========================================================
echo Both services started!
echo Frontend: http://localhost:5173
echo Backend:  http://localhost:8787
echo ========================================================
