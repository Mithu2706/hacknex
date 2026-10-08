@echo off
REM Builds the interface once and serves everything from http://127.0.0.1:8000
cd /d "%~dp0frontend"
call npm run build
cd /d "%~dp0backend"
call .venv\Scripts\activate.bat
start "" http://127.0.0.1:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
