@echo off
setlocal
chcp 65001 >nul
for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

set "PYTHON_EXE="
set "BASE_PYTHON="

if exist "%PROJECT_ROOT%\.venv-build\Scripts\python.exe" (
    "%PROJECT_ROOT%\.venv-build\Scripts\python.exe" --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=%PROJECT_ROOT%\.venv-build\Scripts\python.exe"
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

if not defined PYTHON_EXE if exist "%PROJECT_ROOT%\.venv-build" (
    if not exist "%PROJECT_ROOT%\archive_old_code" mkdir "%PROJECT_ROOT%\archive_old_code"
    for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BROKEN_STAMP=%%T"
    echo 检测到损坏的构建环境，正在移入 archive_old_code...
    move "%PROJECT_ROOT%\.venv-build" "%PROJECT_ROOT%\archive_old_code\.venv-build-broken-%BROKEN_STAMP%" >nul
    if errorlevel 1 exit /b 1
)

if not defined PYTHON_EXE (
    echo 正在创建构建环境...
    %BASE_PYTHON% -m venv "%PROJECT_ROOT%\.venv-build"
    if errorlevel 1 exit /b 1
    set "PYTHON_EXE=%PROJECT_ROOT%\.venv-build\Scripts\python.exe"
)

echo 正在安装或更新构建依赖...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --upgrade pip -r "%PROJECT_ROOT%\requirements-dev.txt"
if errorlevel 1 exit /b 1

set "VERSION_FILE=%TEMP%\LightNovelSelector-version-%RANDOM%.txt"
"%PYTHON_EXE%" -c "from lightnovel_selector.constants import APP_VERSION; print(APP_VERSION)" > "%VERSION_FILE%"
if errorlevel 1 exit /b 1
set /p APP_VERSION=<"%VERSION_FILE%"
del "%VERSION_FILE%" >nul 2>nul
if not defined APP_VERSION set "APP_VERSION=0.0.0"

for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BUILD_STAMP=%%T"
set "APP_EXE_NAME=LightNovelSelector-v%APP_VERSION%-%BUILD_STAMP%"

if not exist "%PROJECT_ROOT%\build\spec" mkdir "%PROJECT_ROOT%\build\spec"

echo 正在构建 %APP_EXE_NAME%.exe...
"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --workpath "%PROJECT_ROOT%\build\pyinstaller" ^
  --specpath "%PROJECT_ROOT%\build\spec" ^
  --distpath "%PROJECT_ROOT%\dist" ^
  --add-data "%PROJECT_ROOT%\lightnovel_selector\web;lightnovel_selector\web" ^
  --hidden-import webview.platforms.edgechromium ^
  --name "%APP_EXE_NAME%" ^
  "%PROJECT_ROOT%\lightnovel_classifier.py"
if errorlevel 1 exit /b 1

echo.
echo 构建完成：%PROJECT_ROOT%\dist\%APP_EXE_NAME%.exe
if /i not "%LN_SELECTOR_NO_PAUSE%"=="1" pause

