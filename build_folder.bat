@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3.11"
    ) else (
        where python >nul 2>nul
        if not errorlevel 1 set "PYTHON_EXE=python"
    )
)

if not defined PYTHON_EXE (
    echo [错误] 未找到 Python。请安装 Python 3.11，或在 .venv 中创建虚拟环境。
    pause
    exit /b 1
)

for /f "usebackq delims=" %%V in (`"%PYTHON_EXE%" %PYTHON_ARGS% -c "import app_info; print(app_info.VERSION)"`) do set "APP_VERSION=%%V"
if not defined APP_VERSION (
    echo [错误] 无法从 app_info.py 读取版本号。
    pause
    exit /b 1
)

set "DIST_DIR=dist\WorldRelay-v%APP_VERSION%"
echo 正在构建 World Relay v%APP_VERSION% 文件夹版...
"%PYTHON_EXE%" %PYTHON_ARGS% -m PyInstaller --noconfirm --clean world_relay.spec
if errorlevel 1 (
    echo.
    echo [失败] 构建没有完成，请查看上方错误。
    pause
    exit /b 1
)

copy /Y "README.md" "%DIST_DIR%\README.md" >nul
if errorlevel 1 (
    echo.
    echo [失败] EXE 已生成，但 README.md 无法复制到发布目录。
    pause
    exit /b 1
)

echo.
echo [完成] 发布目录：%~dp0%DIST_DIR%
echo 双击其中的 WorldRelay.exe 即可启动。
pause
