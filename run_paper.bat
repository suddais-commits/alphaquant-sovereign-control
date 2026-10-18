@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" daily_trend_paper.py --force
pause
