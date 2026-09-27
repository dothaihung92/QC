@echo off
chcp 65001 >nul
REM Chay phan mem quang cao Fanpage tren Windows
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul

REM Tim trinh chay Python: PHAI thu goi thuc su (khong chi dung "where"), vi
REM Windows co san mot "python.exe" gia (App Execution Alias, dan toi Microsoft
REM Store) nam san trong PATH - "where python" van bao "tim thay" du may chua
REM cai Python that, khien buoc sau chay "python ..." bao loi "not recognized".
set "PY="
python --version >nul 2>nul && set "PY=python"
if not defined PY (
  py -3 --version >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  echo Chua tim thay Python that su tren may ^(chi thay "python" gia cua Windows,
  echo dan toi Microsoft Store^). Tai va cai tai https://www.python.org/downloads/
  echo va nho TICK vao o "Add python.exe to PATH" luc cai.
  pause
  exit /b 1
)
echo Da tim thay Python: %PY%

REM Tu dong cap nhat phan mem tu GitHub (neu co ban moi) - chi dung thu vien
REM co san cua Python, khong can moi truong ao nen chay duoc ngay tai day.
REM Chi khoi dong lai khi update.py bao DUNG ma 10 (khong phai bat ky loi nao
REM khac - vi du loi "khong goi duoc python" tra ve ma loi rat lon nhu 9009,
REM neu chi kiem tra "errorlevel 10" ^(nghia la >= 10^) se hieu nham va gay
REM vong lap mo lai vo tan). "%QC_DA_KHOI_DONG_LAI%" chan vong lap du co gi.
if exist update.py if not defined QC_DA_KHOI_DONG_LAI (
  echo Dang kiem tra cap nhat phan mem...
  %PY% update.py
  REM "if errorlevel 10 if not errorlevel 11" nghia la ma loi DUNG BANG 10 -
  REM khong dung bien trung gian vi bien so trong cung 1 khoi ngoac chi duoc
  REM thay gia tri MOT LAN luc doc ca khoi, doc lai se ra gia tri cu.
  if errorlevel 10 if not errorlevel 11 (
    echo Da cap nhat file khoi dong - dang mo lai mot lan...
    set "QC_DA_KHOI_DONG_LAI=1"
    start "" "%~f0"
    exit /b
  )
  echo.
)

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
