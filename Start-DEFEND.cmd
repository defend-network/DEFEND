@echo off
set "DEFEND_REPO=%~dp0"
set "DEFEND_VENV=%DEFEND_REPO%.venv"
if not exist "%DEFEND_VENV%\Scripts\python.exe" set "DEFEND_VENV=%DEFEND_REPO%..\..\.venv"
if not exist "%DEFEND_VENV%\Scripts\python.exe" (
    echo DEFEND Control Center Python environment was not found.
    echo Run Bootstrap-DEFEND.cmd from this worktree first.
    exit /b 9009
)
if /I not "%~1"=="--check" goto launch_gui
"%DEFEND_VENV%\Scripts\python.exe" -m tools.defend_control_center --check
set "DEFEND_CHECK_EXIT=%ERRORLEVEL%"
pause
exit /b %DEFEND_CHECK_EXIT%

:launch_gui
if not exist "%DEFEND_VENV%\Scripts\pythonw.exe" (
    echo DEFEND Control Center GUI Python was not found.
    echo Run Bootstrap-DEFEND.cmd from this worktree first.
    exit /b 9009
)
"%DEFEND_VENV%\Scripts\pythonw.exe" -m tools.defend_control_center
exit /b %ERRORLEVEL%
