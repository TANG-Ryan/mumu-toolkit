@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Start.ps1"
set "task_exit=%errorlevel%"
if not "%task_exit%"=="0" pause
exit /b %task_exit%
