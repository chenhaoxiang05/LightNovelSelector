@echo off
setlocal EnableExtensions
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_winui.ps1" %*
exit /b %ERRORLEVEL%
