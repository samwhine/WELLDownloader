@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0venv\Scripts\python.exe" (
  echo [ERROR] WELL Downloader virtual environment was not found.
  echo Run INSTALL.bat first.
  exit /b 1
)

set PYTHONUNBUFFERED=1
"%~dp0venv\Scripts\python.exe" "%~dp0main.py"
exit /b %ERRORLEVEL%
