@echo off
REM Sword Forge - run or resume a queue without any AI.  Usage: run_forge.bat <queue.json>
REM BLENDER_PY = Blender's own python.exe (default: python on PATH)
set QUEUE=%~1
if "%QUEUE%"=="" (echo usage: run_forge.bat queue.json & pause & exit /b 1)
if "%BLENDER_PY%"=="" set BLENDER_PY=python
if "%FORGE_AGENT%"=="" set FORGE_AGENT=user
"%BLENDER_PY%" "%~dp0forge_orch.py" run "%QUEUE%"
pause
