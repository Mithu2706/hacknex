@echo off
REM One-time setup for ArchNext on Windows (Python 3.10 + Node.js 18+ required)
cd /d "%~dp0backend"
py -3.10 -m venv .venv || python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
cd /d "%~dp0frontend"
call npm install
echo.
echo Setup complete. Run start_backend.bat and start_frontend.bat (or start_demo.bat).
pause
