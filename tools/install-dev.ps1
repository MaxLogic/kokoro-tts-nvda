param(
    [string]$TargetRoot = "$env:APPDATA\nvda\addons\maxlogicKokoroTTS",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceAddonRoot = Join-Path $repoRoot "addon"
$sourceSynthDrivers = Join-Path $sourceAddonRoot "synthDrivers"
$sourceDoc = Join-Path $sourceAddonRoot "doc"
$sourceInstallTasks = Join-Path $sourceAddonRoot "installTasks.py"
$sourceHelperVenv = Join-Path $repoRoot ".helper-venv"

if (Test-Path $TargetRoot) {
    if (-not $Force) {
        throw "Target already exists: $TargetRoot . Re-run with -Force to replace it."
    }
    Remove-Item $TargetRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $TargetRoot | Out-Null

$manifest = @"
name = maxlogicKokoroTTS
summary = "MaxLogic Kokoro TTS"
description = """A conflict-free Kokoro TTS synthesizer for NVDA maintained by MaxLogic."""
author = "MaxLogic"
url = None
version = 0.1.0
docFileName = readme.html
minimumNVDAVersion = 2024.1
lastTestedNVDAVersion = 2025.1
updateChannel = None
"@

Set-Content -Path (Join-Path $TargetRoot "manifest.ini") -Value $manifest -Encoding UTF8
Copy-Item $sourceInstallTasks (Join-Path $TargetRoot "installTasks.py") -Force

New-Item -ItemType Junction -Path (Join-Path $TargetRoot "synthDrivers") -Target $sourceSynthDrivers | Out-Null
New-Item -ItemType Junction -Path (Join-Path $TargetRoot "doc") -Target $sourceDoc | Out-Null

if (Test-Path $sourceHelperVenv) {
    New-Item -ItemType Junction -Path (Join-Path $TargetRoot ".helper-venv") -Target $sourceHelperVenv | Out-Null
}

Write-Host "Development install created at $TargetRoot"
Write-Host "synthDrivers -> $sourceSynthDrivers"
Write-Host "doc -> $sourceDoc"
if (Test-Path $sourceHelperVenv) {
    Write-Host ".helper-venv -> $sourceHelperVenv"
}
