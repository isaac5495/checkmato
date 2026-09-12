@echo off
rem CheckMato dev server — run once; hot-reloads on any file change in app\.
rem Ctrl+C to stop. No restart loop needed while coding.
cd /d "%~dp0"
.venv\Scripts\python.exe -X utf8 -m uvicorn app.server:app --port 8000 --host 127.0.0.1 --reload --reload-dir app
