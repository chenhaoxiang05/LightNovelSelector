@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE="
set "BASE_PYTHON="

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
)

if not defined PYTHON_EXE (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "BASE_PYTHON=py -3"
)

if not defined PYTHON_EXE if not defined BASE_PYTHON (
    python --version >nul 2>nul
    if not errorlevel 1 set "BASE_PYTHON=python"
)

if not defined PYTHON_EXE if not defined BASE_PYTHON (
    echo 未找到 Python。请先安装 Python 3.10 或更高版本。
    pause
    exit /b 1
)

if not defined PYTHON_EXE if exist "%~dp0.venv" (
    if not exist "%~dp0archive_old_code" mkdir "%~dp0archive_old_code"
    for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BROKEN_STAMP=%%T"
    echo 检测到损坏的运行环境，正在移入 archive_old_code...
    move "%~dp0.venv" "%~dp0archive_old_code\.venv-broken-%BROKEN_STAMP%" >nul
    if errorlevel 1 exit /b 1
)

if not defined PYTHON_EXE (
    echo 正在创建项目运行环境...
    %BASE_PYTHON% -m venv "%~dp0.venv"
    if errorlevel 1 exit /b 1
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
)

"%PYTHON_EXE%" -c "import importlib.metadata as m; assert m.version('pywebview') == '6.2.1'" >nul 2>nul
if errorlevel 1 (
    echo 正在安装桌面界面依赖，请稍候...
    "%PYTHON_EXE%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo 依赖安装失败，请检查网络连接后重试。
        pause
        exit /b 1
    )
)

"%PYTHON_EXE%" "%~dp0lightnovel_classifier.py"
if errorlevel 1 (
    echo.
    echo 程序未能正常启动，请保留此窗口中的错误信息。
    pause
)

