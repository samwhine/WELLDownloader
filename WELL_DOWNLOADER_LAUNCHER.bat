@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0venv\Scripts\python.exe" (
  echo [ERROR] WELL Downloader venv belum ditemukan.
  echo Jalankan INSTALL.bat terlebih dahulu.
  exit /b 1
)

set PYTHONUNBUFFERED=1
"%~dp0venv\Scripts\python.exe" "%~dp0main.py"
exit /b %ERRORLEVEL%
