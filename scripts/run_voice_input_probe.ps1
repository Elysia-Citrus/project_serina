$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptRoot
Set-Location $projectRoot

$env:PYTHONUTF8 = "1"

py -3.12 .\scripts\voice_input_probe.py @Args
