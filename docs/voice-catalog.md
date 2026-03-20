# Voice Catalog

The add-on ships with curated catalog files at:

- `addon/synthDrivers/maxlogic_kokoro/catalog.json` for official voices
- `addon/synthDrivers/maxlogic_kokoro/community_catalog.json` for community and experimental voices
- `addon/synthDrivers/maxlogic_kokoro/community_sources.json` for the curated upstream community source list

Each entry contains:

- `id`: stable voice identifier used in the user voice store
- `displayName`: user-facing label
- `language`: BCP-47 style language tag
- `gender` and `genderLabel`: normalized filter metadata used by the manager UI
- `languageLabel`: user-facing language name used by the manager UI
- `sourceFile`: upstream file name in the public voice source
- `downloadUrl`: direct download URL
- `sizeBytes`: expected file size from the curated catalog
- `sha256`: expected SHA-256 digest used for verification before install

Runtime behavior:

- bundled catalog entries are always available as fallback metadata
- the official catalog refresh uses Hugging Face's model tree API for `onnx-community/Kokoro-82M-v1.0-ONNX`
- refreshed catalog data is cached under `%APPDATA%\nvda\maxlogicKokoroTTS\cache\official-voice-catalog.json`
- community entries are generated from curated upstream repos, converted into `.bin`, and mirrored under `%APPDATA%\nvda\maxlogicKokoroTTS\community-mirror\voices`
- if online refresh fails, the add-on falls back to the cache and then to the bundled catalog
- the voice manager can temporarily download a selected online voice into the add-on temp directory and play a helper-backed preview without installing the voice
