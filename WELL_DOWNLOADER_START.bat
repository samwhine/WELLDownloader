@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo [INFO] venv was not found.
  echo Run INSTALL.bat first.
  pause
  exit /b 1
)

call "venv\Scripts\activate.bat"
python main.py
pause
