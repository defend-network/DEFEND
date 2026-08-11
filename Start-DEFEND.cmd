@echo off
set "DEFEND_REPO=%~dp0"
"%DEFEND_REPO%.venv\Scripts\pythonw.exe" -m tools.defend_control_center
