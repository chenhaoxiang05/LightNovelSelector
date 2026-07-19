@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

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
for %%P in ("%~dp0.venv-build\Scripts\python.exe" "%~dp0.venv\Scripts\python.exe") do (
    if not defined PYTHON_EXE if exist "%%~P" (
        "%%~P" -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul
        if not errorlevel 1 set "PYTHON_EXE=%%~P"
    )
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
    echo 未找到 Python 3.10 或更高版本，无法启动分类核心。
    exit /b 1
)
if not defined PYTHON_EXE (
    echo 正在创建 Python 运行环境...
    %BASE_PYTHON% -m venv "%~dp0.venv"
    if errorlevel 1 exit /b 1
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
)

set "LN_SELECTOR_PYTHON=%PYTHON_EXE%"
echo 正在启动 WinUI 3 原生界面...
"%DOTNET_EXE%" restore "%~dp0native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj" -p:Platform=x64 -p:WindowsPackageType=None
if errorlevel 1 exit /b 1
"%DOTNET_EXE%" run --project "%~dp0native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj" -c Debug -p:Platform=x64 -p:WindowsPackageType=None --no-restore
