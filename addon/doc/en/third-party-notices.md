# Third-Party Notices

MaxLogic Kokoro TTS bundles or references third-party software and voice assets.

## Add-on code

- Component: MaxLogic Kokoro TTS add-on code
- Source: https://github.com/MaxLogic/kokoro-tts-nvda
- License: MIT

## Kokoro model

- Component: `kokoro.onnx` and related Kokoro configuration assets
- Source model page: https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX
- Upstream project page: https://huggingface.co/hexgrad/Kokoro-82M
- License shown on the upstream pages: Apache-2.0
- Notes: This package bundles the ONNX export used by the synth driver.

## eSpeak-NG runtime

- Component: bundled `espeak-ng.exe`, `libespeak-ng.dll`, and `espeak-ng-data`
- Project page: https://github.com/espeak-ng/espeak-ng
- License: see the bundled eSpeak-NG project files and notices in that runtime distribution
- Notes: The add-on invokes eSpeak-NG as an external phonemizer process.

## ONNX Runtime

- Component: bundled CPU ONNX Runtime binaries
- Project page: https://github.com/microsoft/onnxruntime
- License: see the bundled `ThirdPartyNotices.txt` and ONNX Runtime license files in `deps/onnxruntime`

## NumPy

- Component: bundled NumPy CPU binaries
- Project page: https://github.com/numpy/numpy
- License: see the bundled NumPy license files in `deps/numpy`

## Community voice mirrors

The package currently bundles a curated mirror of community Kokoro-compatible voices for offline installation and preview.

Curated upstream sources:

- `Sethblocks/KokoroVoices`
  - https://huggingface.co/Sethblocks/KokoroVoices
- `kiriyamaX/kokoro-v1_0`
  - https://huggingface.co/kiriyamaX/kokoro-v1_0
- `asif00/Kokoro-Conversational`
  - https://huggingface.co/asif00/Kokoro-Conversational

Notes:

- these voices are mirrored in converted `.bin` form for NVDA consumption
- metadata for the curated list is shipped in `community_sources.json` and `community_catalog.json`
- users should review the upstream repository pages for current terms, provenance, and any additional attribution requirements
