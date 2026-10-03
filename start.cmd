@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import fastapi,uvicorn,numpy,scipy,pydantic_settings" >nul 2>&1
  if not errorlevel 1 (
    .venv\Scripts\python.exe launch.py
    goto done
  )
)
python launch.py
:done
pause
