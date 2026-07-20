@echo off
call "%~dp0scripts\windows\build_exe.bat" %*
exit /b %ERRORLEVEL%
