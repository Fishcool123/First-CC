@echo off
chcp 65001 >nul
echo ============================================
echo   PC智能任务助理 — 启动中...
echo ============================================
echo.

cd /d "%~dp0"

:: 检查依赖
echo [1/2] 检查 Python 依赖...
py -m pip install flask --quiet 2>nul
if %errorlevel% neq 0 (
    echo  请确认 Python 已安装并能执行 py 命令
    pause
    exit /b 1
)

:: 启动服务
echo [2/2] 启动服务...
echo.
start "" /B py app.py

:: 等待 Flask 启动
timeout /t 3 /nobreak >nul

:: 打开浏览器
start "" http://127.0.0.1:5000

echo.
echo   服务已启动！浏览器将自动打开 http://127.0.0.1:5000
echo   关闭此窗口不会停止服务，请在终端按 Ctrl+C 停止
echo.
pause
