@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo Python 3.12 or later is required. Install Python and run this file again.
  pause
  exit /b 1
)

:install
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Package installation failed. Check the internet connection and run this file again.
  pause
  exit /b 1
)

echo Starting the app at http://127.0.0.1:8501
".venv\Scripts\python.exe" -m src.server
pause
