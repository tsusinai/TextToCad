@echo off
title TextToCad Backend
echo ========================================================
echo   Starting TextToCad Geometry Backend (Port 8787)
echo ========================================================
cd /d "%~dp0backend"
call .venv\Scripts\activate.bat
python -m uvicorn app:app --host 0.0.0.0 --port 8787 --env-file .env --reload
pause
