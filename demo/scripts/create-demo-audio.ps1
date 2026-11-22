$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$root = Split-Path -Parent $PSScriptRoot
$script = Get-Content -LiteralPath (Join-Path $root 'scenario-source.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$output = Join-Path $root '.audio-build'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
foreach ($segment in $script.segments) {
    $person = $script.people | Where-Object { $_.id -eq $segment.speaker }
    $synth.SelectVoice($person.voice)
    $synth.Rate = $person.rate
    $synth.SetOutputToWaveFile((Join-Path $output ($segment.id + '.wav')))
    $synth.Speak($segment.text)
    $synth.SetOutputToNull()
}
$synth.Dispose()
python (Join-Path $PSScriptRoot 'prepare_scenario.py')
