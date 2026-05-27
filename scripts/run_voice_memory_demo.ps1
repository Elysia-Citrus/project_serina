param(
    [switch]$AutoListen,
    [switch]$Manual,
    [switch]$SkipServices,
    [switch]$ResetMemory,
    [switch]$NoTTS,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Resolve-RequiredPath {
    param(
        [string]$Path,
        [string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Name not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Test-HttpReady {
    param(
        [string]$Url,
        [int]$TimeoutSec = 2
    )
    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Wait-HttpReady {
    param(
        [string]$Url,
        [int]$TimeoutSec = 90
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpReady -Url $Url -TimeoutSec 2) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Assert-UnderRoot {
    param(
        [string]$Root,
        [string]$Target
    )
    $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
    $resolvedTarget = (Resolve-Path -LiteralPath $Target).Path
    if ($resolvedTarget -ne $resolvedRoot -and -not $resolvedTarget.StartsWith($resolvedRoot + '\')) {
        throw "Refusing path outside project root: $resolvedTarget"
    }
    return $resolvedTarget
}

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$WorkspaceRoot = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot "..")).Path
$MyNeuroRoot = Join-Path $WorkspaceRoot "my-neuro"
$AsrRoot = Join-Path $MyNeuroRoot "full-hub"
$TtsRoot = Join-Path $MyNeuroRoot "full-hub\tts-hub\GPT-SoVITS-Bundle"
$AsrStatusUrl = "http://127.0.0.1:1000/vad/status"
$TtsDocsUrl = "http://127.0.0.1:5000/docs"
$TtsWeightsUrl = "http://127.0.0.1:5000/set_sovits_weights?weights_path=role_voice_api/neuro/merge.pth"
$StartedProcesses = New-Object System.Collections.Generic.List[System.Diagnostics.Process]

try {
    $ProjectRoot = Resolve-RequiredPath -Path $ProjectRoot -Name "project root"
    $MyNeuroRoot = Resolve-RequiredPath -Path $MyNeuroRoot -Name "my-neuro root"
    $AsrRoot = Resolve-RequiredPath -Path $AsrRoot -Name "my-neuro ASR root"
    $TtsRoot = Resolve-RequiredPath -Path $TtsRoot -Name "GPT-SoVITS v2 root"

    Push-Location $ProjectRoot

    Write-Host "Project_Serina voice memory demo"
    Write-Host "Project root: $ProjectRoot"
    Write-Host "my-neuro root: $MyNeuroRoot"
    Write-Host "ASR: my-neuro/full-hub/asr_api.py -> $AsrStatusUrl"
    Write-Host "TTS: GPT-SoVITS api_v2.py -> $TtsDocsUrl"
    Write-Host "SQLite: data/serina.db"
    Write-Host "Mode: $(if ($AutoListen -and -not $Manual) { 'auto-listen' } else { 'manual' })"
    Write-Host "TTS playback: $(if ($NoTTS) { 'disabled for this run' } else { 'enabled' })"

    if ($ResetMemory) {
        $DataDir = Join-Path $ProjectRoot "data"
        if (Test-Path -LiteralPath $DataDir) {
            Assert-UnderRoot -Root $ProjectRoot -Target $DataDir | Out-Null
            $dbFiles = Get-ChildItem -LiteralPath $DataDir -File -Filter "serina.db*" -ErrorAction SilentlyContinue
            foreach ($dbFile in $dbFiles) {
                Assert-UnderRoot -Root $ProjectRoot -Target $dbFile.FullName | Out-Null
                if ($DryRun) {
                    Write-Host "[dry-run] would remove $($dbFile.FullName)"
                } else {
                    Remove-Item -LiteralPath $dbFile.FullName -Force
                    Write-Host "Removed memory DB file: $($dbFile.Name)"
                }
            }
        }
    }

    $AsrPython = Join-Path $MyNeuroRoot "env\python.exe"
    $TtsPython = Join-Path $TtsRoot "runtime\python.exe"
    $TtsConfig = Join-Path $TtsRoot "GPT_SoVITS\configs\tts_infer.yaml"
    $TtsApi = Join-Path $TtsRoot "api_v2.py"

    if ($DryRun) {
        Write-Host "[dry-run] ASR python: $AsrPython"
        Write-Host "[dry-run] TTS python: $TtsPython"
        Write-Host "[dry-run] TTS config: $TtsConfig"
        $dryRunArgs = @("src/app/main_voice.py")
        if ($AutoListen -and -not $Manual) {
            $dryRunArgs += "--auto-listen"
        } else {
            $dryRunArgs += "--manual"
        }
        if ($NoTTS) {
            $dryRunArgs += "--no-tts"
            Write-Host "[dry-run] GPT-SoVITS startup would be skipped because -NoTTS is set"
        }
        Write-Host "[dry-run] command: py -3.12 $($dryRunArgs -join ' ')"
        return
    }

    if (-not $SkipServices) {
        if (Test-HttpReady -Url $AsrStatusUrl) {
            Write-Host "ASR already running."
        } else {
            if (Test-Path -LiteralPath $AsrPython) {
                $proc = Start-Process -FilePath $AsrPython -ArgumentList @("asr_api.py") -WorkingDirectory $AsrRoot -PassThru -WindowStyle Hidden
            } else {
                $proc = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "conda activate my-neuro && cd /d `"$AsrRoot`" && python asr_api.py") -PassThru -WindowStyle Hidden
            }
            $StartedProcesses.Add($proc)
            Write-Host "Started ASR process: $($proc.Id)"
            if (-not (Wait-HttpReady -Url $AsrStatusUrl -TimeoutSec 90)) {
                throw "ASR did not become ready at $AsrStatusUrl"
            }
        }

        if ($NoTTS) {
            Write-Host "Skipping GPT-SoVITS v2 startup because -NoTTS is set."
        } else {
            if (Test-HttpReady -Url $TtsDocsUrl) {
                Write-Host "GPT-SoVITS v2 already running."
            } else {
                Resolve-RequiredPath -Path $TtsPython -Name "GPT-SoVITS runtime python" | Out-Null
                Resolve-RequiredPath -Path $TtsApi -Name "GPT-SoVITS api_v2.py" | Out-Null
                Resolve-RequiredPath -Path $TtsConfig -Name "GPT-SoVITS tts_infer.yaml" | Out-Null
                $proc = Start-Process -FilePath $TtsPython -ArgumentList @("api_v2.py", "-a", "127.0.0.1", "-p", "5000", "-c", "GPT_SoVITS/configs/tts_infer.yaml") -WorkingDirectory $TtsRoot -PassThru -WindowStyle Hidden
                $StartedProcesses.Add($proc)
                Write-Host "Started GPT-SoVITS v2 process: $($proc.Id)"
                if (-not (Wait-HttpReady -Url $TtsDocsUrl -TimeoutSec 120)) {
                    throw "GPT-SoVITS v2 did not become ready at $TtsDocsUrl"
                }
            }

            Invoke-WebRequest -Uri $TtsWeightsUrl -UseBasicParsing -TimeoutSec 30 | Out-Null
            Write-Host "Loaded SoVITS weights: role_voice_api/neuro/merge.pth"
        }
    } else {
        Write-Host "Skipping service startup and health checks."
    }

    $voiceArgs = @("src/app/main_voice.py")
    if ($AutoListen -and -not $Manual) {
        $voiceArgs += "--auto-listen"
    } else {
        $voiceArgs += "--manual"
    }
    if ($NoTTS) {
        $voiceArgs += "--no-tts"
    }
    & py -3.12 @voiceArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location -ErrorAction SilentlyContinue
    foreach ($proc in $StartedProcesses) {
        try {
            if ($proc -and -not $proc.HasExited) {
                Stop-Process -Id $proc.Id -Force
                Write-Host "Stopped child process: $($proc.Id)"
            }
        } catch {
            Write-Warning "Failed to stop child process $($proc.Id): $_"
        }
    }
}
