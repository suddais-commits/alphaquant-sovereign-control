@echo off
setlocal
cd /d "C:\Users\HP\OneDrive\Desktop\CryptoBot"
set PYTHON_EXE="%~dp0.venv\Scripts\python.exe"
if not exist %PYTHON_EXE% (
    echo Virtual environment python not found: %PYTHON_EXE%
    pause
    exit /b 1
)
:start
%PYTHON_EXE% master_bot.py
echo Bot crash ho gaya ya ruk gaya -- 5 second mein restart ho raha hai...
timeout /t 5
goto start
