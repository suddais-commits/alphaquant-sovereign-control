@echo off
title Push CryptoBot to GitHub
cd /d "%~dp0"
echo ===================================================
echo   Pushing AlphaQuant Sovereign Control to GitHub
echo ===================================================
echo.
echo Agar browser popup aye, to bas 'Sign in with your browser' par click karein.
echo.
tools\git\cmd\git.exe push -u origin main
echo.
if %ERRORLEVEL% EQU 0 (
    echo ===================================================
    echo  SUCCESS! Code GitHub par push ho chuka hai!
    echo  GitHub Actions ab rozana 00:05 UTC cloud par chalega.
    echo ===================================================
) else (
    echo.
    echo [!] Push fail hua. Agar authentication error aye, to GitHub login check karein.
)
echo.
pause
