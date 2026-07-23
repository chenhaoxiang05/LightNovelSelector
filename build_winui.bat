@echo off
call "%~dp0scripts\windows\build_winui.bat" %*
exit /b %ERRORLEVEL%
