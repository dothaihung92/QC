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
  echo Tao thu muc .venv that bai. Xoa thu muc .venv roi chay lai file nay.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat

echo Dang cai thu vien (lan dau hoi lau, cac lan sau nhanh)...
python -m pip install -q --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo ============================================================
  echo  CAI THU VIEN THAT BAI - xem loi mau do phia tren.
  echo  Neu thay loi lien quan pydantic-core, Rust, hoac
  echo  metadata-generation-failed: ban Python dang dung qua moi,
  echo  chua co san goi cai dat.
  echo  Hay cai them Python 3.12 tai dia chi duoi day, nho tick o
  echo  "Add python.exe to PATH" luc cai:
  echo  https://www.python.org/downloads/release/python-3120/
  echo  Sau do xoa thu muc .venv va chay lai file nay.
  echo ============================================================
  pause
  exit /b 1
)

REM Mo cua so may chu rieng bang file run_server.bat, "cmd /k" giu cua so
REM nay khong tu tat du chay loi hay dung.
start "May chu - dung Ctrl+C hoac dong cua so nay de tat" cmd /k run_server.bat
timeout /t 3 >nul
start "" http://127.0.0.1:8787

echo.
echo Da mo cua so may chu o mot cua so khac, tieu de bat dau bang "May chu".
echo Trinh duyet se tu mo tai http://127.0.0.1:8787
echo Neu trinh duyet bao khong ket noi duoc, doi vai giay roi bam F5.
echo Cua so nay dong lai cung khong sao, may chu van chay o cua so kia.
pause
