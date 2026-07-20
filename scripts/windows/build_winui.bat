@echo off
setlocal EnableExtensions
chcp 65001 >nul
for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

set "DOTNET_EXE=%ProgramFiles%\dotnet\dotnet.exe"
if not exist "%DOTNET_EXE%" (
    for /f "delims=" %%D in ('where dotnet 2^>nul') do if not defined DOTNET_FOUND set "DOTNET_FOUND=%%D"
    if defined DOTNET_FOUND set "DOTNET_EXE=%DOTNET_FOUND%"
)
if not exist "%DOTNET_EXE%" (
    echo 未找到 .NET 10 SDK。请先运行：winget install Microsoft.DotNet.SDK.10
    exit /b 1
)

set "PYTHON_EXE="
if exist "%PROJECT_ROOT%\.venv-build\Scripts\python.exe" (
    "%PROJECT_ROOT%\.venv-build\Scripts\python.exe" -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=%PROJECT_ROOT%\.venv-build\Scripts\python.exe"
)
if not defined PYTHON_EXE (
    py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul
    if not errorlevel 1 set "BASE_PYTHON=py -3"
)
if not defined PYTHON_EXE if not defined BASE_PYTHON (
    python -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul
    if not errorlevel 1 set "BASE_PYTHON=python"
)
if not defined PYTHON_EXE if not defined BASE_PYTHON (
    echo 未找到 Python 3.10 或更高版本，无法构建分类核心。
    exit /b 1
)
if not defined PYTHON_EXE (
    echo 正在创建 Python 构建环境...
    %BASE_PYTHON% -m venv "%PROJECT_ROOT%\.venv-build"
    if errorlevel 1 exit /b 1
    set "PYTHON_EXE=%PROJECT_ROOT%\.venv-build\Scripts\python.exe"
)

echo [1/7] 安装构建依赖...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check -r "%PROJECT_ROOT%\requirements-dev.txt"
if errorlevel 1 exit /b 1

echo [2/7] 生成原生应用图标...
"%PYTHON_EXE%" "%PROJECT_ROOT%\tools\generate_native_assets.py"
if errorlevel 1 exit /b 1

if not exist "%PROJECT_ROOT%\build\native-sidecar" mkdir "%PROJECT_ROOT%\build\native-sidecar"
if not exist "%PROJECT_ROOT%\build\pyinstaller-sidecar" mkdir "%PROJECT_ROOT%\build\pyinstaller-sidecar"
if not exist "%PROJECT_ROOT%\build\spec" mkdir "%PROJECT_ROOT%\build\spec"

echo [3/7] 构建 Python Sidecar...
"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --console ^
  --workpath "%PROJECT_ROOT%\build\pyinstaller-sidecar" ^
  --specpath "%PROJECT_ROOT%\build\spec" ^
  --distpath "%PROJECT_ROOT%\build\native-sidecar" ^
  --name "LightNovelSelector.Sidecar" ^
  "%PROJECT_ROOT%\lightnovel_sidecar.py"
if errorlevel 1 exit /b 1

set "SIDECAR_EXE=%PROJECT_ROOT%\build\native-sidecar\LightNovelSelector.Sidecar.exe"
echo [4/7] 验证 Sidecar 协议...
"%PYTHON_EXE%" -c "import json,subprocess,sys; data='{""id"":1,""method"":""ping""}\n{""id"":2,""method"":""shutdown""}\n'; p=subprocess.run([sys.argv[1]],input=data,text=True,encoding='utf-8',capture_output=True,timeout=30); rows=[json.loads(x) for x in p.stdout.splitlines()]; assert p.returncode==0 and not p.stderr and rows[0]['result']['protocol_version']==1 and rows[1]['result']['accepted']" "%SIDECAR_EXE%"
if errorlevel 1 exit /b 1

set "VERSION_FILE=%TEMP%\LightNovelSelector-winui-version-%RANDOM%.txt"
"%PYTHON_EXE%" -c "from lightnovel_selector.constants import APP_VERSION; print(APP_VERSION)" > "%VERSION_FILE%"
if errorlevel 1 exit /b 1
set /p APP_VERSION=<"%VERSION_FILE%"
del "%VERSION_FILE%" >nul 2>nul
if not defined APP_VERSION set "APP_VERSION=0.0.0"
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BUILD_STAMP=%%T"
set "APP_DIR_NAME=LightNovelSelector-v%APP_VERSION%-win-x64-%BUILD_STAMP%"
set "PUBLISH_DIR=%PROJECT_ROOT%\dist\winui\%APP_DIR_NAME%"
set "ZIP_PATH=%PROJECT_ROOT%\dist\winui\%APP_DIR_NAME%.zip"
if not exist "%PROJECT_ROOT%\dist\winui" mkdir "%PROJECT_ROOT%\dist\winui"

echo [5/7] 执行 C# 单元测试...
"%DOTNET_EXE%" restore "%PROJECT_ROOT%\native\LightNovelSelector.WinUI.Tests\LightNovelSelector.WinUI.Tests.csproj"
if errorlevel 1 exit /b 1
"%DOTNET_EXE%" test "%PROJECT_ROOT%\native\LightNovelSelector.WinUI.Tests\LightNovelSelector.WinUI.Tests.csproj" -c Release --no-restore --logger "console;verbosity=minimal"
if errorlevel 1 exit /b 1

echo [6/7] 发布自包含 WinUI 3 应用...
"%DOTNET_EXE%" restore "%PROJECT_ROOT%\native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj" -r win-x64 -p:Platform=x64 -p:WindowsPackageType=None
if errorlevel 1 exit /b 1
"%DOTNET_EXE%" publish "%PROJECT_ROOT%\native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj" ^
  -c Release ^
  -r win-x64 ^
  -p:Platform=x64 ^
  -p:WindowsPackageType=None ^
  -p:WindowsAppSDKSelfContained=true ^
  -p:SelfContained=true ^
  -p:PublishTrimmed=false ^
  --no-restore ^
  --output "%PUBLISH_DIR%"
if errorlevel 1 exit /b 1

if not exist "%PUBLISH_DIR%\LightNovelSelector.WinUI.exe" (
    echo WinUI 主程序未生成。
    exit /b 1
)
if not exist "%PUBLISH_DIR%\LightNovelSelector.Sidecar.exe" (
    echo Python Sidecar 未复制到发布目录。
    exit /b 1
)

echo [7/7] 执行发布版启动与外观回归测试并压缩...
set "LN_SELECTOR_WINUI_TEST_THEME=dark"
set "LN_SELECTOR_WINUI_TEST_MATERIAL=acrylic"
set "LN_SELECTOR_WINUI_SMOKE_TEST=1"
start "" /wait "%PUBLISH_DIR%\LightNovelSelector.WinUI.exe"
set "SMOKE_EXIT=%ERRORLEVEL%"
set "LN_SELECTOR_WINUI_SMOKE_TEST="
if not "%SMOKE_EXIT%"=="0" (
    set "LN_SELECTOR_WINUI_TEST_THEME="
    set "LN_SELECTOR_WINUI_TEST_MATERIAL="
    exit /b %SMOKE_EXIT%
)

set "LN_SELECTOR_WINUI_APPEARANCE_SMOKE_TEST=1"
start "" /wait "%PUBLISH_DIR%\LightNovelSelector.WinUI.exe"
set "APPEARANCE_SMOKE_EXIT=%ERRORLEVEL%"
set "LN_SELECTOR_WINUI_APPEARANCE_SMOKE_TEST="
set "LN_SELECTOR_WINUI_TEST_THEME="
set "LN_SELECTOR_WINUI_TEST_MATERIAL="
if not "%APPEARANCE_SMOKE_EXIT%"=="0" exit /b %APPEARANCE_SMOKE_EXIT%

powershell -NoProfile -Command "Compress-Archive -Path '%PUBLISH_DIR%\*' -DestinationPath '%ZIP_PATH%' -CompressionLevel Optimal"
if errorlevel 1 exit /b 1

echo.
echo 构建完成：
echo   便携目录：%PUBLISH_DIR%
echo   ZIP 包：%ZIP_PATH%
if /i not "%LN_SELECTOR_NO_PAUSE%"=="1" pause
