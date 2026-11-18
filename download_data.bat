@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run run.bat once first, close it, and then run this file again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\fetch_hub_data.py
pause
