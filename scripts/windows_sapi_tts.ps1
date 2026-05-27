param(
    [ValidateSet("list-voices", "synthesize")]
    [string]$Action = "synthesize",
    [string]$OutputPath = "",
    [string]$TextBase64 = "",
    [string]$VoiceName = "",
    [int]$Rate = 0,
    [int]$Volume = 100
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

function Get-InstalledVoices {
    $voice = New-Object -ComObject SAPI.SpVoice
    $tokens = $voice.GetVoices()
    $voices = @()
    for ($i = 0; $i -lt $tokens.Count; $i++) {
        $voices += $tokens.Item($i).GetDescription()
    }
    return $voices
}

function Resolve-VoiceToken {
    param(
        [Parameter(Mandatory = $true)]
        $VoiceObject,
        [string]$RequestedVoiceName
    )

    $tokens = $VoiceObject.GetVoices()
    if ($tokens.Count -eq 0) {
        throw "No Windows SAPI voices are installed."
    }

    if ($RequestedVoiceName) {
        for ($i = 0; $i -lt $tokens.Count; $i++) {
            $token = $tokens.Item($i)
            $description = $token.GetDescription()
            if ($description -eq $RequestedVoiceName -or $description -like "*$RequestedVoiceName*") {
                return $token
            }
        }
    }

    for ($i = 0; $i -lt $tokens.Count; $i++) {
        $token = $tokens.Item($i)
        $description = $token.GetDescription()
        if ($description -like "*Huihui*" -or $description -like "*Chinese*" -or $description -like "*中文*") {
            return $token
        }
    }

    return $tokens.Item(0)
}

if ($Action -eq "list-voices") {
    $voices = Get-InstalledVoices
    @{
        voices = $voices
    } | ConvertTo-Json -Compress
    exit 0
}

if (-not $OutputPath) {
    throw "OutputPath is required for synthesize."
}
if (-not $TextBase64) {
    throw "TextBase64 is required for synthesize."
}

$text = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($TextBase64))
$resolvedOutputPath = [System.IO.Path]::GetFullPath($OutputPath)
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($resolvedOutputPath)) | Out-Null

$voice = New-Object -ComObject SAPI.SpVoice
$voice.Volume = [Math]::Max(0, [Math]::Min(100, $Volume))
$voice.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
$voiceToken = Resolve-VoiceToken -VoiceObject $voice -RequestedVoiceName $VoiceName
$voice.Voice = $voiceToken

$stream = New-Object -ComObject SAPI.SpFileStream
try {
    $stream.Open($resolvedOutputPath, 3, $false)
    $voice.AudioOutputStream = $stream
    [void]$voice.Speak($text)
}
finally {
    if ($stream) {
        $stream.Close()
    }
}

@{
    output_path = $resolvedOutputPath
    voice_name = $voiceToken.GetDescription()
} | ConvertTo-Json -Compress
