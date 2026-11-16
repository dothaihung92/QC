@echo off
REM File nay duoc start.bat tu mo trong cua so rieng - khong chay truc tiep file nay.
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Chua co moi truong .venv - hay chay start.bat truoc.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m app.server
echo.
echo May chu da dung. Dong cua so nay hoac bam phim bat ky.
pause >nul
