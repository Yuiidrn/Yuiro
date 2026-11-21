# Generate a fixed Mandarin test INPUT with an already installed Windows voice.
# Production TTS/provider/configuration is not changed.
$g0Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$g0Target = Join-Path $g0Root 'docs\plan\G0-live-artifacts\voice-input-fixture.wav'
Add-Type -AssemblyName System.Speech
$g0Speech = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $g0Speech.SelectVoice('Microsoft Huihui Desktop')
    $g0Format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
        16000,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    $g0Speech.SetOutputToWaveFile($g0Target, $g0Format)
    $g0Speech.Speak('你好，请只回复你好。')
    $g0Speech.SetOutputToNull()
} finally {
    $g0Speech.Dispose()
}
Write-Output 'Created fixed Mandarin input fixture with installed Huihui voice.'
