@echo off
setlocal
cd /d "%~dp0"

echo ====================================
echo    WELL Downloader - Clear Cache
echo ====================================
echo.
echo Make sure the WELL Downloader server is stopped.
echo Do not run this while a download is active.
echo.
pause

if not exist "temp\downloader" (
  echo [INFO] The cache folder does not exist. Nothing to clear.
  pause
  exit /b 0
)

for /d %%D in ("temp\downloader\*") do rd /s /q "%%D"
for %%F in ("temp\downloader\*") do del /q "%%F" 2>nul

echo.
echo [OK] All temporary cache and download files have been cleared.
pause
