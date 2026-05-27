$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$env:PYTHONUTF8 = "1"
py -3.12 scripts/voice_runtime_check.py
