$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$env:PYTHONUTF8 = "1"

function Get-YamlScalarValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    $pattern = '^\s*' + [Regex]::Escape($Key) + ':\s*"?([^"#\r\n]+)"?'
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $match = [Regex]::Match($line, $pattern)
        if ($match.Success) {
            return $match.Groups[1].Value.Trim()
        }
    }
    return $null
}

function Wait-ForHttpOk {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$TimeoutSeconds = 12
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 2
            if ($response.status -eq "ok") {
                return $true
            }
        }
        catch {
            Start-Sleep -Milliseconds 300
        }
    }
    return $false
}

$voiceConfigPath = Join-Path (Get-Location) 'src\config\voice_config.yaml'
$ttsProvider = Get-YamlScalarValue -Path $voiceConfigPath -Key 'tts_provider'
$primaryRuntimeUrl = Get-YamlScalarValue -Path $voiceConfigPath -Key 'primary_tts_runtime_url'
if (-not $primaryRuntimeUrl) {
    $primaryRuntimeUrl = 'http://127.0.0.1:51771'
}
$healthUrl = $primaryRuntimeUrl.TrimEnd('/') + '/healthz'

$startedSidecar = $null
if ($ttsProvider -eq 'cosyvoice_local') {
    $isHealthy = Wait-ForHttpOk -Url $healthUrl -TimeoutSeconds 1
    if (-not $isHealthy) {
        $startedSidecar = Start-Process `
            -FilePath 'powershell.exe' `
            -ArgumentList '-ExecutionPolicy', 'Bypass', '-File', 'scripts/run_local_primary_tts.ps1' `
            -WindowStyle Hidden `
            -PassThru

        if (-not (Wait-ForHttpOk -Url $healthUrl -TimeoutSeconds 12)) {
            if ($startedSidecar -and -not $startedSidecar.HasExited) {
                Stop-Process -Id $startedSidecar.Id -Force -ErrorAction SilentlyContinue
            }
            throw "Local primary TTS sidecar failed to start at $healthUrl"
        }
    }
}

try {
    py -3.12 src/app/main_voice.py @Args
}
finally {
    if ($startedSidecar -and -not $startedSidecar.HasExited) {
        Stop-Process -Id $startedSidecar.Id -Force -ErrorAction SilentlyContinue
    }
}
