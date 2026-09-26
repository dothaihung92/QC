@echo off
chcp 65001 >nul
REM Chay phan mem quang cao Fanpage tren Windows
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
where python >nul 2>nul || (echo Chua cai Python. Tai tai https://www.python.org/downloads/ va tick "Add Python to PATH". & pause & exit /b 1)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8787"
python -m app.server
pause
