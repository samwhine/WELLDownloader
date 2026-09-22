@echo off
setlocal
cd /d "%~dp0"

echo ====================================
echo      WELL Downloader - yt-dlp Update
echo ====================================
echo.
echo IMPORTANT: Stop the WELL Downloader server first.
echo Close the server window or press Ctrl+C, then continue this script.
echo.
pause

if not exist "venv\Scripts\python.exe" (
  echo [ERROR] venv was not found in this project folder.
  echo Run INSTALL.bat first.
  pause
  exit /b 1
)

call "venv\Scripts\activate.bat"
echo.
echo Current yt-dlp version:
python -m yt_dlp --version
echo.
echo Updating yt-dlp inside this project's venv...
python -m pip install --upgrade yt-dlp
if errorlevel 1 (
  echo.
  echo [ERROR] Update failed. Check your internet connection and try again.
  pause
  exit /b 1
)
echo.
echo Updated yt-dlp version:
python -m yt_dlp --version
echo.
echo [OK] yt-dlp has been updated in the WELL Downloader venv.
echo Start the server again with WELL_DOWNLOADER_START.bat.
pause
