param(
    [string]$ReferenceRoot = "$env:APPDATA\nvda\addons\kokoroTTS\synthDrivers\kokoro",
    [switch]$IncludeDeps
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$targetRoot = Join-Path $repoRoot "addon\synthDrivers\maxlogic_kokoro"

if (-not (Test-Path $ReferenceRoot)) {
    throw "Reference add-on root not found: $ReferenceRoot"
}

Write-Host "Copying Kokoro assets from $ReferenceRoot"

Copy-Item (Join-Path $ReferenceRoot "config.json") (Join-Path $targetRoot "config.json") -Force
Copy-Item (Join-Path $ReferenceRoot "tokenizer.json") (Join-Path $targetRoot "tokenizer.json") -Force

foreach ($name in @("model", "voices", "espeak")) {
    $source = Join-Path $ReferenceRoot $name
    $destination = Join-Path $targetRoot $name
    if (Test-Path $source) {
        Copy-Item $source $destination -Recurse -Force
    }
}

if ($IncludeDeps) {
    $sourceDeps = Join-Path $ReferenceRoot "deps"
    $destinationDeps = Join-Path $targetRoot "deps"
    if (Test-Path $sourceDeps) {
        Copy-Item $sourceDeps $destinationDeps -Recurse -Force
    }
}

Write-Host "Bootstrap complete."
if ($IncludeDeps) {
    Write-Host "Bundled deps copied from the reference add-on. Those are typically CPU-only."
}
