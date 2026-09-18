@echo off
echo ========================================================
echo   SPIT! Real-Time Arcade Multiplayer Card Game Server
echo ========================================================
echo Starting server on http://localhost:5000 ...

if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" app.py
) else (
    py -3.13 app.py
)
pause
