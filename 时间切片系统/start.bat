@echo off
cd /d "%~dp0"

py -m pip install -r requirements.txt --quiet 2>nul

py -c "import flask,psutil,win32gui,webview,pystray,plyer" 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Missing modules. Run: py -m pip install -r requirements.txt
    pause
    exit /b 1
)

start /min "" py desktop.py
