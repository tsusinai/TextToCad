@echo off
title TextToCad Frontend
echo ========================================================
echo   Starting TextToCad Frontend (Port 8000)
echo ========================================================
cd /d "%~dp0"
start http://localhost:8000
"%~dp0backend\.venv\Scripts\python.exe" -m http.server 8000
pause
