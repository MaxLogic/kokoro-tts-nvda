# MaxLogic Kokoro TTS

MaxLogic Kokoro TTS is a separate Kokoro-based synthesizer for NVDA.

This add-on intentionally uses a different internal identity from the existing `kokoroTTS` add-on so both can coexist.

## Runtime notes

- The synth prefers CUDA when the bundled ONNX Runtime exposes `CUDAExecutionProvider`.
- If CUDA is not available, it falls back to `DmlExecutionProvider`, then CPU.
- Heavy assets can be bundled locally, or during development they can be read from an installed reference add-on.
- On 32-bit NVDA, GPU inference must run through the optional 64-bit helper environment.
