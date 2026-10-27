@echo off
title SepanViewer v2 - Setup
cd /d "%~dp0"
if exist .venv\Scripts\python.exe goto packages
py -3.12 -m venv .venv
if errorlevel 1 goto failed
:packages
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Installation complete. Run start.bat.
pause
exit /b 0
:failed
echo Installation failed. Install Python 3.12 x64 with Python Launcher and retry.
pause
exit /b 1
