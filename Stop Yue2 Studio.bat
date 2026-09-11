@echo off
cd /d "%~dp0"
"..\.venv\Scripts\python.exe" "..\launch_studio.py" --stop %*
if errorlevel 1 pause
