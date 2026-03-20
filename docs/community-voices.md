# Community Voices

The Community tab is backed by a curated local mirror of community Kokoro voices that are converted into `.bin` files before NVDA consumes them.

Selected upstream repos:

- `Sethblocks/KokoroVoices`
  - https://huggingface.co/Sethblocks/KokoroVoices
  - included voices: `af_mika`, `af_mrs_claus`, `am_andy`, `am_dylan`, `heart_young`
- `kiriyamaX/kokoro-v1_0`
  - https://huggingface.co/kiriyamaX/kokoro-v1_0
  - included voices: `af_k1`, `af_blend_29`
- `asif00/Kokoro-Conversational`
  - https://huggingface.co/asif00/Kokoro-Conversational
  - included voices: `af_bella_nicole`, `af_nicole_sky`, `af_sarah_nicole`, `af_sky_adam`, `af_sky_emma`, `af_sky_emma_isabella`

Why this mirror exists:

- many community voices are published as `.pt` PyTorch tensors
- the add-on runtime intentionally consumes `.bin`, `.json`, or `.npy`, not `.pt`
- the mirror step converts curated `.pt` voices into `.bin` so the add-on stays lightweight and consistent

Mirror workflow:

- source definitions live in `addon/synthDrivers/maxlogic_kokoro/community_sources.json`
- run `python .\tools\sync-community-mirror.py --clean` from the repo root
- converted files are written under `%APPDATA%\nvda\maxlogicKokoroTTS\community-mirror\voices`
- the script regenerates `addon/synthDrivers/maxlogic_kokoro/community_catalog.json`

Notes:

- the sync tool skips duplicate converted payloads by SHA-256 so the Community tab does not show the same voice twice under different names
- community voices are treated as experimental and should remain separate from the official catalog
