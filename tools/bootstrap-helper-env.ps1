param(
    [ValidateSet("cuda", "dml", "cpu")]
    [string]$Provider = "cuda",
    [string]$PythonVersion = "3.11",
    [string]$VenvPath = ".helper-venv"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvRoot = Join-Path $repoRoot $VenvPath

Write-Host "Creating helper venv at $venvRoot using py -$PythonVersion"
& py "-$PythonVersion" -m venv $venvRoot

$venvPython = Join-Path $venvRoot "Scripts\python.exe"

& $venvPython -m pip install --upgrade pip setuptools wheel

switch ($Provider) {
    "cuda" {
        $package = "onnxruntime-gpu[cuda,cudnn]"
    }
    "dml" {
        $package = "onnxruntime-directml"
    }
    "cpu" {
        $package = "onnxruntime"
    }
}

Write-Host "Installing helper runtime packages for provider '$Provider'"
& $venvPython -m pip install numpy $package

Write-Host ""
Write-Host "Helper environment ready."
Write-Host "Python: $venvPython"
Write-Host "Set MAXLOGIC_KOKORO_HELPER_PYTHON to override discovery if needed."
