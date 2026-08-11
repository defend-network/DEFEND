@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Bootstrap-DEFEND.ps1" %*
exit /b %ERRORLEVEL%
