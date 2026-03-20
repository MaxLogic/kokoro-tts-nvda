# Changelog

## [Unreleased]

### Added
- user-managed voice storage under `%APPDATA%\nvda\maxlogicKokoroTTS\voices` with merged discovery ahead of bundled and reference voices
- local voice install/remove support for `.bin`, `.npy`, `.json`, and `.zip` voice files
- a curated official Kokoro catalog backed by the ONNX community model index, with cached availability refresh and SHA-256 verification
- a separate bundled community catalog scaffold for future curated experimental voices
- a MaxLogic Kokoro Voice Manager menu entry and dialog with Installed, Official, and Community tabs
- a `Speech Cache` manager tab with cache size, cache-mode, maintenance, and live cache statistics controls
- official voice filtering by name, gender, and language plus bulk selection and download actions
- helper-backed sample playback for focused online voices using dedicated preview text loaded from a separate file
- a curated community source list plus a local mirror tool that converts selected `.pt` community voices into `.bin` files for the Community tab

### Changed
- the development installer now links `globalPlugins` so live NVDA installs can load the voice manager during development
- speech caching is now governed by a shared user-data policy file and helper-side cache hits are logged explicitly for repeated short utterances
- medium and long paragraph chunks now use a short-lived helper hot cache, and playback chunking uses smaller follow-up chunks to reduce stale-speech delay during paragraph navigation
