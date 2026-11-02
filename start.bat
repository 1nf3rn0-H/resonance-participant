@echo off
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo Install Node.js 22.18 or later first.
  exit /b 1
)
node -e "const [a,b]=process.versions.node.split('.').map(Number);if(a<22||(a===22&&b<18))process.exit(1)"
if errorlevel 1 exit /b 1
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
if not exist .venv\Scripts\python.exe exit /b 1
if not exist .venv\.participant-installed (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 exit /b 1
  .venv\Scripts\python.exe -m contracts.offline_bundle.v1.selftest
  if errorlevel 1 exit /b 1
  echo installed>.venv\.participant-installed
)
.venv\Scripts\python.exe -m participant.server %*
