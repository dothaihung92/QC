@echo off
chcp 65001 >nul
REM Chay phan mem quang cao Fanpage tren Windows
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul

REM Tim trinh chay Python: uu tien lenh "python", khong co thi dung "py" (Python Launcher)
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  echo Chua tim thay Python. Tai tai https://www.python.org/downloads/ va tick "Add python.exe to PATH" khi cai.
  pause
  exit /b 1
)
echo Da tim thay Python: %PY%

if not exist .venv %PY% -m venv .venv
if not exist .venv\Scripts\python.exe (
  echo Tao moi truong ao Python (.venv) that bai. Xoa thu muc .venv roi chay lai file nay.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8787"
python -m app.server
pause
