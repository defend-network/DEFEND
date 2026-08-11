@echo off
set "DEFEND_REPO=%~dp0"
if /I not "%~1"=="--check" goto launch_gui
"%DEFEND_REPO%.venv\Scripts\python.exe" -m tools.defend_control_center --check
set "DEFEND_CHECK_EXIT=%ERRORLEVEL%"
pause
exit /b %DEFEND_CHECK_EXIT%

:launch_gui
"%DEFEND_REPO%.venv\Scripts\pythonw.exe" -m tools.defend_control_center
