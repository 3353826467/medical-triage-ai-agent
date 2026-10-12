@echo off
chcp 65001 >nul
title 智能问诊 AI 客服系统 - 开发启动器

echo ============================================================
echo  智能问诊 AI 客服系统
echo ============================================================
echo.

cd /d "%~dp0"

REM ---- 检查虚拟环境 ----
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 未找到虚拟环境，正在创建...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败，请确认已安装 Python 3.10+ 并加入 PATH
        pause
        exit /b 1
    )
) else (
    echo [1/3] 虚拟环境已存在
)

echo [2/3] 安装后端依赖...
".venv\Scripts\python.exe" -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r backend\requirements.txt
if errorlevel 1 (
    echo [警告] 后端依赖安装可能不完整，请查看上方输出
)

echo [3/3] 安装前端依赖...
cd frontend
if not exist "node_modules" (
    call npm install --registry=https://registry.npmmirror.com
)
cd ..

echo.
echo 正在启动服务...
echo   - 后端 API:  http://127.0.0.1:8000/docs
echo   - 前端界面:  http://127.0.0.1:5173
echo.

start "MedicalAI-Backend" cmd /k "cd /d "%~dp0backend" && "..\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
timeout /t 3 >nul
start "MedicalAI-Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo 服务已在新窗口中启动。
echo 提示：未配置 OPENAI_API_KEY 时将使用本地规则引擎，系统仍可正常对话。
pause
