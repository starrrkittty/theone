@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements-local.txt
if errorlevel 1 exit /b 1
cd frontend
call npm ci --cache ../.npm-cache --no-audit --no-fund
if errorlevel 1 exit /b 1
call npm run build
if errorlevel 1 exit /b 1
echo Setup complete. Fill coach\config.json and run start.cmd.
pause
