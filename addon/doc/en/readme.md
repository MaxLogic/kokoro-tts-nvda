# MaxLogic Kokoro TTS for NVDA

MaxLogic Kokoro TTS is an NVDA add-on that adds a separate Kokoro speech synthesizer under the name `MaxLogic Kokoro TTS`.

It uses its own add-on ID and synth driver name so it can coexist with the older `kokoroTTS` add-on without conflicts.

## Features

- Separate NVDA synth: `MaxLogic Kokoro TTS`
- Built-in voice manager available from the NVDA menu
- Official voice catalog with filtering by name, gender, and language
- Separate `Official v1.1-zh` voice catalog for the newer Kokoro ONNX release
- Community voice catalog for curated experimental voices
- Option to hide voices that are already available locally in the online catalogs
- Bulk download and install of selected voices
- Local voice install from `.bin`, `.json`, `.npy`, or `.zip`
- Sample playback before installing a voice
- User-downloaded voices stored outside the add-on so they survive reinstalls
- Speech Cache tab with cache settings, live stats, clear, and compact actions
- Built-in support for persistent short-speech caching and short-lived paragraph hot caching
- Smarter chunking for longer text, with preference for sentence and clause boundaries
- Improved repeated-navigation responsiveness for short prompts and paragraph hopping

## Why this add-on feels faster

MaxLogic Kokoro TTS includes several responsiveness optimizations beyond basic Kokoro integration:

- Helper-backed GPU inference when a compatible 64-bit helper environment is available
- Voice prewarming to reduce cold-start delay
- Persistent cache for repeated short utterances such as navigation prompts and command feedback
- Hot in-memory cache for longer paragraph chunks when moving back and forth through text
- Prefetching of upcoming chunks while current audio is already playing
- Safer chunk splitting for long text so large passages are less likely to fail

## What is included in this package

- Kokoro model files
- eSpeak-NG runtime required by the phonemizer
- A small built-in starter voice set
- A bundled curated community mirror used by the Community tab
- CPU runtime dependencies for immediate use after installation

This makes the release package large, but it also means the add-on works offline immediately after installation.

## GPU support

The packaged add-on is ready to use after installation with the bundled CPU runtime.

CUDA and other accelerated modes are available as advanced setups, but on many NVDA installations they require an external 64-bit helper environment. If no helper is configured, the add-on falls back to the bundled in-process runtime.

When helper mode is active, the add-on can use:

- `CUDAExecutionProvider` for NVIDIA GPU acceleration
- `DmlExecutionProvider` on supported DirectML setups
- CPU fallback when no accelerator is available

## Installing the add-on

1. Open the `.nvda-addon` package file.
2. Allow NVDA to install the add-on.
3. Restart NVDA when prompted.
4. Open NVDA Settings and select `MaxLogic Kokoro TTS` as the synthesizer.

## Managing voices

Open:

- `NVDA menu -> MaxLogic Kokoro voice manager...`

Tabs:

- `Installed`: user-installed voices and built-in/fallback voices
- `Official`: curated official Kokoro voices
- `Official v1.1-zh`: curated voices from the newer `Kokoro-82M-v1.1-zh-ONNX` release
- `Community`: curated experimental community voices
- `Speech Cache`: cache settings, persistent cache stats, and hot cache stats

Available actions:

- filter the online lists
- hide voices that are already available locally
- play a sample for the focused voice
- select visible voices
- clear visible selection
- download selected voices
- install a local voice file
- remove a user-installed voice
- change cache policy for short or medium speech
- clear or compact the cache

Current `Official v1.1-zh` rollout:

- `af_maple`
- `af_sol`
- `bf_vale`

These voices are available for preview and download now as the first supported subset of the newer v1.1-zh release.

The broader Chinese `zf_*` voice set is not exposed yet. Current validation shows that the packaged phonemizer path does not produce usable tokens for Chinese text, so wider v1.1-zh rollout is deferred until Chinese phonemizer support is added.

## Voice storage

Downloaded and user-installed voices are stored here:

- `%APPDATA%\nvda\maxlogicKokoroTTS\voices`

This keeps your voice library separate from the add-on package itself.

Speech cache and logs are also stored outside the add-on package:

- Cache settings: `%APPDATA%\nvda\maxlogicKokoroTTS\speech-cache-settings.json`
- Persistent cache database: `%APPDATA%\nvda\maxlogicKokoroTTS\cache\speech-cache.sqlite3`

## Logging

Useful logs:

- NVDA log: `C:\Users\pawel\AppData\Local\Temp\nvda.log`
- MaxLogic helper log: `%APPDATA%\nvda\maxlogicKokoroTTS\logs\helper.log`

## Speech cache

The add-on uses two cache layers:

- `Persistent cache`: SQLite-backed cache for repeated short utterances
- `Hot cache`: short-lived helper memory cache for quick paragraph repeats

The Speech Cache tab shows both layers separately so it is easier to understand what the add-on is currently using.

## License and attribution

The MaxLogic Kokoro TTS add-on code is distributed under the MIT license. The package also bundles third-party components and assets with their own licenses and attribution requirements.

Bundled components include:

- Kokoro ONNX model data based on `onnx-community/Kokoro-82M-v1.0-ONNX`
- Kokoro upstream model project from `hexgrad/Kokoro-82M`
- eSpeak-NG runtime used by the phonemizer
- ONNX Runtime CPU binaries
- NumPy CPU binaries
- Curated community voice mirrors from the upstream Hugging Face repositories listed in the bundled notices

See:

- `LICENSE`
- `doc/en/third-party-notices.html`
- `doc/en/third-party-notices.md`

## Known limitations

- Community voices are curated and mirrored; the list is intentionally smaller than the full internet.
- GPU acceleration depends on the local NVDA/Python environment and may not be available out of the box on every system.
- Non-English support depends on available Kokoro voices and phonemizer quality.
- The broader Chinese `zf_*` voices from the v1.1-zh release are currently deferred because the packaged phonemizer path does not yet tokenize Chinese text correctly.
- Very rapid movement between large paragraphs can still be limited by the time required to finish an already-running neural inference request.

## Add-on identity

- Add-on ID: `maxlogicKokoroTTS`
- Synth driver: `maxlogic_kokoro`
- Display name: `MaxLogic Kokoro TTS`
