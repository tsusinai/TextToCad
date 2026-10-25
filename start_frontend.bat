@echo off
title FORMA Frontend
echo ========================================================
echo   Starting FORMA React Studio (Port 5173)
echo ========================================================
cd /d "%~dp0frontend"
where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js 22+ and npm are required for the React frontend.
  pause
  exit /b 1
)
if not exist node_modules (
  echo Installing frontend dependencies...
  call npm install
)
start http://localhost:5173
call npm run dev -- --host 0.0.0.0
pause
