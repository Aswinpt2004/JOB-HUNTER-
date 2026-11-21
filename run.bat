@echo off
REM ========================================================
REM  JobPilot v2: Multi-Source Application Assistant
REM  Local-first server & background scheduler runner
REM ========================================================

echo [JobPilot v2] Checking virtual environment...
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found in .\venv. Please create one with: python -m venv venv
    pause
    exit /b 1
)

echo [JobPilot v2] Starting FastAPI server on http://127.0.0.1:8000 ...
.\venv\Scripts\python.exe -m jobpilot run --host 127.0.0.1 --port 8000
pause

