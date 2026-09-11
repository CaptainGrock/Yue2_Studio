@echo off
cd /d "%~dp0"
if not exist "..\.venv\Scripts\python.exe" (
  echo Install YuE2 first. Expected its Python at ..\.venv\Scripts\python.exe
  echo See README.md for other environment locations.
  pause
  exit /b 1
)
"..\.venv\Scripts\python.exe" "install_studio.py"
if errorlevel 1 (
  pause
  exit /b 1
)
"..\.venv\Scripts\python.exe" "..\launch_studio.py" %*
if errorlevel 1 pause
