@echo off
setlocal
chcp 65001 >nul
for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

set "PYTHON_EXE="
set "BASE_PYTHON="

if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    "%PROJECT_ROOT%\.venv\Scripts\python.exe" --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
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

if not defined PYTHON_EXE if exist "%PROJECT_ROOT%\.venv" (
    if not exist "%PROJECT_ROOT%\archive_old_code" mkdir "%PROJECT_ROOT%\archive_old_code"
    for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BROKEN_STAMP=%%T"
    echo 检测到损坏的运行环境，正在移入 archive_old_code...
    move "%PROJECT_ROOT%\.venv" "%PROJECT_ROOT%\archive_old_code\.venv-broken-%BROKEN_STAMP%" >nul
    if errorlevel 1 exit /b 1
)

if not defined PYTHON_EXE (
    echo 正在创建项目运行环境...
    %BASE_PYTHON% -m venv "%PROJECT_ROOT%\.venv"
    if errorlevel 1 exit /b 1
    set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
)

"%PYTHON_EXE%" -c "import importlib.metadata as m; assert m.version('pywebview') == '6.2.1'" >nul 2>nul
if errorlevel 1 (
    echo 正在安装桌面界面依赖，请稍候...
    "%PYTHON_EXE%" -m pip install --disable-pip-version-check -r "%PROJECT_ROOT%\requirements.txt"
    if errorlevel 1 (
        echo 依赖安装失败，请检查网络连接后重试。
        pause
        exit /b 1
    )
)

"%PYTHON_EXE%" "%PROJECT_ROOT%\lightnovel_classifier.py"
if errorlevel 1 (
    echo.
    echo 程序未能正常启动，请保留此窗口中的错误信息。
    pause
)

