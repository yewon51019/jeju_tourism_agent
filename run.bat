@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "FOLDER=%~dp0"
if not "%FOLDER:~80%"=="" (
  echo The folder path is too long for package installation.
  echo Move this folder to a short path such as C:\jeju_tourism_agent and run this file again.
  pause
  exit /b 1
)
set "CHECK=import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "%CHECK%" >nul 2>nul
  if errorlevel 1 (
    echo The .venv folder uses an unsupported Python version.
    echo Delete the .venv folder, install Python 3.12 or later, and run this file again.
    pause
    exit /b 1
  )
  goto install
)

set "PY="
for %%V in (3.14 3.13 3.12) do (
  if not defined PY (
    py -%%V -c "%CHECK%" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "%CHECK%" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python 3.12 or later is required. Install Python and run this file again.
  pause
  exit /b 1
)
%PY% -m venv .venv
if errorlevel 1 (
  echo Could not create the virtual environment.
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
