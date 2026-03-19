# MaxLogic Kokoro TTS for NVDA

This repository contains the first-party MaxLogic Kokoro TTS add-on source for NVDA.

## Goals

- Use a distinct add-on identity so it can coexist with the existing `kokoroTTS` add-on.
- Keep the implementation maintainable and NVDA-native.
- Prefer CUDA automatically when the bundled ONNX Runtime supports it.
- Fall back cleanly to DirectML or CPU when CUDA is unavailable.

## Current add-on identity

- Add-on id: `maxlogicKokoroTTS`
- Synth driver name: `maxlogic_kokoro`
- Visible name: `MaxLogic Kokoro TTS`

## Development asset strategy

The source tree keeps heavy runtime assets out of Git by default.

During development, the driver resolves assets in this order:

1. Local files under `addon/synthDrivers/maxlogic_kokoro`
2. `MAXLOGIC_KOKORO_ASSET_ROOT` if set
3. The installed reference add-on at `%APPDATA%\nvda\addons\kokoroTTS\synthDrivers\kokoro`

This means the repo can be developed against the installed reference add-on without copying large binaries immediately.

## Bootstrapping a standalone local copy

Run:

```powershell
.\tools\bootstrap-reference-assets.ps1
```

To also copy the reference add-on's bundled dependencies:

```powershell
.\tools\bootstrap-reference-assets.ps1 -IncludeDeps
```

Note: the reference add-on's bundled ONNX Runtime is CPU-only. CUDA support in this project depends on bundling a GPU-capable ONNX Runtime in `addon/synthDrivers/maxlogic_kokoro/deps`.

## 64-bit GPU helper

Current NVDA deployments here are using 32-bit Python, while current `onnxruntime-gpu` and `onnxruntime-directml` wheels are x64-only.

That means GPU inference must run out-of-process in a 64-bit helper.

Create a helper environment with:

```powershell
.\tools\bootstrap-helper-env.ps1 -Provider cuda
```

Alternative:

```powershell
.\tools\bootstrap-helper-env.ps1 -Provider dml
.\tools\bootstrap-helper-env.ps1 -Provider cpu
```

By default the synth will use `.\.helper-venv\Scripts\python.exe` when present.

You can override it with:

```powershell
$env:MAXLOGIC_KOKORO_HELPER_PYTHON = "C:\path\to\python.exe"
```

The helper uses the same add-on assets and reports its active execution providers back to the synth driver.

## Provider selection

Set `MAXLOGIC_KOKORO_PROVIDER` to one of:

- `auto`
- `cuda`
- `dml`
- `cpu`

Optional:

- `MAXLOGIC_KOKORO_DEVICE_ID` for CUDA device selection
- `MAXLOGIC_KOKORO_ASSET_ROOT` to override where model assets are loaded from
- `MAXLOGIC_KOKORO_HELPER_PYTHON` to point the synth at a 64-bit helper Python

## Layout

- `addon/synthDrivers/maxlogic_kokoro/__init__.py`: NVDA synth driver entry point
- `addon/synthDrivers/maxlogic_kokoro/_engine.py`: Kokoro inference engine
- `addon/synthDrivers/maxlogic_kokoro/_phonemizer.py`: eSpeak-backed phonemizer wrapper
- `tools/bootstrap-reference-assets.ps1`: local asset bootstrap helper
