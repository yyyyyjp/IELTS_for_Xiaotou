@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo  ============================================
echo    Tifo 雅思听写 - 启动
echo  ============================================
echo.

if not exist "server\.venv\Scripts\python.exe" (
  echo  [1/4] 创建 Python 虚拟环境...
  python -m venv server\.venv || goto :err
)

server\.venv\Scripts\python.exe -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo  [2/4] 安装后端依赖...
  server\.venv\Scripts\python.exe -m pip install -q -r server\requirements.txt || goto :err
) else (
  echo  [2/4] 后端依赖已就绪
)

if exist "web\dist\index.html" (
  echo  [3/4] 前端已构建，跳过
  echo  [4/4] 启动服务...
) else (
  echo  [3/4] 构建前端（首次较慢）...
  pushd web
  call npm install || goto :err
  call npm run build || goto :err
  popd
  echo  [4/4] 启动服务...
)

netstat -ano | findstr ":8000" | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo.
  echo  服务已经在运行，直接打开页面
  start "" http://127.0.0.1:8000
  goto :eof
)

echo.
echo  服务地址： http://127.0.0.1:8000
echo  接口文档： http://127.0.0.1:8000/docs
echo  按 Ctrl+C 停止
echo.

start "" /b cmd /c "timeout /t 3 >nul && start http://127.0.0.1:8000"

cd server
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
goto :eof

:err
echo.
echo  启动失败，请检查上面的报错信息。
pause
