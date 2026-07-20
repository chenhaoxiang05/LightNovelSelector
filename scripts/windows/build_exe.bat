@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE="
set "BASE_PYTHON="

if exist "%~dp0.venv-build\Scripts\python.exe" (
    "%~dp0.venv-build\Scripts\python.exe" --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=%~dp0.venv-build\Scripts\python.exe"
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
    echo 未找到 Python。请在构建电脑上安装 Python 3.10 或更高版本。
    pause
    exit /b 1
)

if not defined PYTHON_EXE if exist "%~dp0.venv-build" (
    if not exist "%~dp0archive_old_code" mkdir "%~dp0archive_old_code"
    for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BROKEN_STAMP=%%T"
    echo 检测到损坏的构建环境，正在移入 archive_old_code...
    move "%~dp0.venv-build" "%~dp0archive_old_code\.venv-build-broken-%BROKEN_STAMP%" >nul
    if errorlevel 1 exit /b 1
)

if not defined PYTHON_EXE (
    echo 正在创建构建环境...
    %BASE_PYTHON% -m venv "%~dp0.venv-build"
    if errorlevel 1 exit /b 1
    set "PYTHON_EXE=%~dp0.venv-build\Scripts\python.exe"
)

echo 正在安装或更新构建依赖...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --upgrade pip -r "%~dp0requirements-dev.txt"
if errorlevel 1 exit /b 1

set "VERSION_FILE=%TEMP%\LightNovelSelector-version-%RANDOM%.txt"
"%PYTHON_EXE%" -c "from lightnovel_selector.constants import APP_VERSION; print(APP_VERSION)" > "%VERSION_FILE%"
if errorlevel 1 exit /b 1
set /p APP_VERSION=<"%VERSION_FILE%"
del "%VERSION_FILE%" >nul 2>nul
if not defined APP_VERSION set "APP_VERSION=0.0.0"

for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BUILD_STAMP=%%T"
set "APP_EXE_NAME=LightNovelSelector-v%APP_VERSION%-%BUILD_STAMP%"

if not exist "%~dp0build\spec" mkdir "%~dp0build\spec"

echo 正在构建 %APP_EXE_NAME%.exe...
"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --workpath "%~dp0build\pyinstaller" ^
  --specpath "%~dp0build\spec" ^
  --distpath "%~dp0dist" ^
  --add-data "%~dp0lightnovel_selector\web;lightnovel_selector\web" ^
  --hidden-import webview.platforms.edgechromium ^
  --name "%APP_EXE_NAME%" ^
  "%~dp0lightnovel_classifier.py"
if errorlevel 1 exit /b 1

echo.
echo 构建完成：%~dp0dist\%APP_EXE_NAME%.exe
if /i not "%LN_SELECTOR_NO_PAUSE%"=="1" pause

