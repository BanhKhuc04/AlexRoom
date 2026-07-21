$ErrorActionPreference = 'Stop'

if (-not $env:MQTT_PASSWORD) { throw 'Set MQTT_PASSWORD before preview.' }
if (-not $env:ALEX_API_KEY) { throw 'Set ALEX_API_KEY before preview.' }

$python = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Missing .venv. Create it and install requirements.txt.' }

& $python -m uvicorn app:app --host 127.0.0.1 --port 5173
