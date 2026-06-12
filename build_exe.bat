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
    if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
        "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" --version >nul 2>nul
        if not errorlevel 1 set "BASE_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    )
)

if not defined PYTHON_EXE if not defined BASE_PYTHON (
    echo Cannot find Python. Install Python 3.10+ on the build computer, then run this again.
    pause
    exit /b 1
)

if not defined PYTHON_EXE if exist "%~dp0.venv-build" (
    echo Existing build environment is broken. Moving it to archive_old_code...
    if not exist "%~dp0archive_old_code" mkdir "%~dp0archive_old_code"
    for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BROKEN_STAMP=%%T"
    move "%~dp0.venv-build" "%~dp0archive_old_code\.venv-build-broken-%BROKEN_STAMP%" >nul
    if errorlevel 1 exit /b 1
)

if not defined PYTHON_EXE if not exist "%~dp0.venv-build\Scripts\python.exe" (
    echo Creating build environment...
    %BASE_PYTHON% -m venv "%~dp0.venv-build"
    if errorlevel 1 exit /b 1
)

set "PYTHON_EXE=%~dp0.venv-build\Scripts\python.exe"

echo Installing/updating PyInstaller...
"%PYTHON_EXE%" -m pip install --upgrade pip pyinstaller pillow
if errorlevel 1 exit /b 1

for /f tokens^=2^ delims^=^" %%V in ('findstr /b "APP_VERSION" "%~dp0lightnovel_classifier.py"') do set "APP_VERSION=%%V"
if not defined APP_VERSION set "APP_VERSION=0.0.0"

for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BUILD_STAMP=%%T"
set "APP_EXE_NAME=LightNovelSelector-v%APP_VERSION%-%BUILD_STAMP%"

if not exist "%~dp0build\spec" mkdir "%~dp0build\spec"

echo Building %APP_EXE_NAME%.exe...
"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --workpath "%~dp0build\pyinstaller" ^
  --specpath "%~dp0build\spec" ^
  --distpath "%~dp0dist" ^
  --name "%APP_EXE_NAME%" ^
  "%~dp0lightnovel_classifier.py"
if errorlevel 1 exit /b 1

echo.
echo Done: %~dp0dist\%APP_EXE_NAME%.exe
if /i not "%LN_SELECTOR_NO_PAUSE%"=="1" pause
