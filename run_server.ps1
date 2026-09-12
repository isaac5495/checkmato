# CheckMato supervised server: restarts uvicorn automatically if it ever exits.
# URL for the browser: http://127.0.0.1:8000  (localhost can resolve to IPv6 ::1
# and get refused while the server is fine — always use 127.0.0.1)
Set-Location "C:\Users\user\Desktop\CheckMato"
if (-not (Test-Path logs)) { New-Item -ItemType Directory logs | Out-Null }
while ($true) {
    & ".venv\Scripts\python.exe" -X utf8 -m uvicorn app.server:app `
        --port 8000 --host 127.0.0.1 --reload --reload-dir app 2>> logs\server.err
    Add-Content logs\server.log ("[{0}] server exited - restarting in 3s" -f (Get-Date))
    Start-Sleep 3
}
