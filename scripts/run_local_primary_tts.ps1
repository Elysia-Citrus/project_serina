$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$env:PYTHONUTF8 = "1"
py -3.12 scripts/run_local_tts_sidecar.py --runtime primary
