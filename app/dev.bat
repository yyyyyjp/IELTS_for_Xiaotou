@echo off
chcp 65001 >nul
cd /d "%~dp0"

start "tifo-api" cmd /k "cd /d %~dp0server && .venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000"
start "tifo-web" cmd /k "cd /d %~dp0web && npm run dev"

echo  后端 http://127.0.0.1:8000/docs
echo  前端 http://127.0.0.1:5173
echo.
echo  关闭两个新开的命令行窗口即可停止。
pause
