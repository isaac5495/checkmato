@echo off
rem CheckMato START — runs windowless (nothing to close by accident).
rem Logs: logs\server.log .  Open http://localhost:8000
cd /d "%~dp0"
if not exist logs mkdir logs
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'uvicorn app.server:app' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
powershell -NoProfile -Command "Start-Process -FilePath '%~dp0.venv\Scripts\python.exe' -ArgumentList '-X','utf8','-m','uvicorn','app.server:app','--port','8000','--host','127.0.0.1' -WorkingDirectory '%~dp0' -WindowStyle Hidden -RedirectStandardOutput '%~dp0logs\server.log' -RedirectStandardError '%~dp0logs\server.err'"
timeout /t 3 /nobreak >nul
start http://localhost:8000
