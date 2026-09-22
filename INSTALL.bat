@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ====================================
echo      WELL Downloader - Installer
echo ====================================
echo.

where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON=py"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Python was not found.
    echo Install Python 3.10+ and enable Add Python to PATH.
    pause
    exit /b 1
  )
  set "PYTHON=python"
)

echo [1/3] Creating the virtual environment in venv...
if not exist "venv\Scripts\python.exe" (
  %PYTHON% -m venv venv
  if errorlevel 1 (
    echo [ERROR] Could not create the venv.
    pause
    exit /b 1
  )
) else (
  echo       venv already exists. Skipping.
)

echo [2/3] Activating the venv...
call "venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERROR] Could not activate the venv.
  pause
  exit /b 1
)

echo [3/3] Installing dependencies from requirements.txt...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [ERROR] Dependency installation failed.
  echo Check your internet connection and run INSTALL.bat again.
  pause
  exit /b 1
)

echo.
echo ====================================
echo [OK] WELL Downloader installation complete.
echo ====================================
echo Run WELL_DOWNLOADER_START.bat to start the server.
echo FFmpeg must be installed separately and available in PATH.
echo.
pause
