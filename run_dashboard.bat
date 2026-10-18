@echo off
cd /d "%~dp0"
echo ========================================================
echo   Starting AlphaQuant Sovereign Fund Dashboard Server...
echo ========================================================
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8000/dashboard"
".venv\Scripts\python.exe" bot_api_server.py
pause
