@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "BUILT_EXE="
for /f "delims=" %%D in ('dir /b /ad /o:-n "%~dp0dist\WorldRelay-v*" 2^>nul') do (
    if not defined BUILT_EXE if exist "%~dp0dist\%%D\WorldRelay.exe" set "BUILT_EXE=%~dp0dist\%%D\WorldRelay.exe"
)

if defined BUILT_EXE (
    start "" "%BUILT_EXE%"
    exit /b 0
) else if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" desktop.py
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3.11 desktop.py
    ) else (
        where python >nul 2>nul
        if not errorlevel 1 (
            python desktop.py
        ) else (
            echo 启动失败：未找到已构建的 EXE 或可用的 Python。
            echo 请安装 Python 3.11，或先运行 build_folder.bat 构建文件夹版。
            pause
            exit /b 1
        )
    )
)
