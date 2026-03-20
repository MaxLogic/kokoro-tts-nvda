# Tasks
Next task ID: T-010

## Summary
Open tasks: 5 (In Progress: 0, Next Today: 2, Next This Week: 3, Next Later: 0, Blocked: 0)
Done tasks: 4

## In Progress

## Next – Today

### T-001 [CLI] Add user voice storage and merged voice discovery
Outcome:
- downloaded/user-managed Kokoro voices are loaded from `%APPDATA%\nvda\maxlogicKokoroTTS\voices` before bundled or reference voices
- synth discovery no longer depends on bundled voices being present when user voices exist
- the synth exposes a reload path so updated voice files can be picked up without a full reinstall
Proof:
- Run: `python -m py_compile addon\synthDrivers\maxlogic_kokoro\__init__.py addon\synthDrivers\maxlogic_kokoro\_engine.py`
  Expect: exit=0
- Run: `Get-ChildItem "$env:APPDATA\nvda\maxlogicKokoroTTS\voices"`
  Expect: command succeeds even when the directory is newly created
- Run: `Copy-Item ".\tests\data\voices\af_test.npy" "$env:APPDATA\nvda\maxlogicKokoroTTS\voices\af_test.npy"`
  Expect: command succeeds and the file exists in the user voice store
- Run: `Get-Content "C:\Users\pawel\AppData\Local\Temp\nvda.log" -Tail 120`
  Expect: after selecting the synth, log shows MaxLogic Kokoro initialized with merged discovery and identifies the user voice store before bundled/reference fallback
Touches: addon/synthDrivers/maxlogic_kokoro/__init__.py, addon/synthDrivers/maxlogic_kokoro/_engine.py, addon/synthDrivers/maxlogic_kokoro/_log.py
Verify: cli-proof, manual
Notes: This is the base task for any download/install flow because downloaded voices must live outside the add-on directory.

### T-002 [CLI] Add local voice install and remove workflow
Outcome:
- a local-install path accepts a supported voice package or raw voice file and installs it into the user voice store
- installed user voices can be removed safely without touching bundled/reference voices
- the install/remove flow defines the shared validation contract for voice metadata, duplicate handling, overwrite policy, and post-install refresh behavior
- install/remove operations refresh the synth voice list or clearly request a restart when refresh is not possible
Proof:
- Run: `python -m py_compile addon\synthDrivers\maxlogic_kokoro\*.py addon\globalPlugins\maxlogic_kokoro_manager\*.py`
  Expect: exit=0
- Run: `powershell -ExecutionPolicy Bypass -Command "Test-Path '$env:APPDATA\nvda\maxlogicKokoroTTS\voices'"`
  Expect: output is `True`
- Run: `Get-ChildItem "$env:APPDATA\nvda\maxlogicKokoroTTS\voices"`
  Expect: after local install, only the expected user-managed voice files exist in the store
- Run: `Get-ChildItem "$env:APPDATA\nvda\maxlogicKokoroTTS\voices"`
  Expect: after removing the installed voice, bundled/reference voice files are untouched and the removed user-managed voice is gone
- Run: `Get-Content "C:\Users\pawel\AppData\Local\Temp\nvda.log" -Tail 150`
  Expect: after install/remove actions, log shows the shared installer path, duplicate/overwrite decision, and a successful refresh or an explicit restart requirement
Touches: addon/synthDrivers/maxlogic_kokoro/__init__.py, addon/synthDrivers/maxlogic_kokoro/_engine.py, addon/globalPlugins/
Deps: T-001
Verify: cli-proof, manual
Notes: Keep the initial local install format simple; archive support can wrap one or more `.npy` voices plus metadata.

## Next – This Week

### T-009 [CLI] Validate runtime compatibility for broader v1.1-zh adoption
Outcome:
- the project has a documented yes/no compatibility result for using v1.1-zh voices with the current runtime and helper path
- if broader v1.1-zh support needs a separate model asset or model-selection path, that requirement is captured explicitly with the affected runtime surfaces
- the decision for exposing or deferring the `zf_*` voice set is recorded with evidence from preview/install/runtime tests
Proof:
- Run: `python -m py_compile addon\synthDrivers\maxlogic_kokoro\_engine.py addon\synthDrivers\maxlogic_kokoro\_helper_process.py addon\synthDrivers\maxlogic_kokoro\_helper_client.py`
  Expect: exit=0
- Run: `Get-Content "C:\Users\pawel\AppData\Roaming\nvda\maxlogicKokoroTTS\logs\helper.log" -Tail 150`
  Expect: log contains explicit validation attempts for representative v1.1-zh voices and shows whether synthesis succeeded or failed with the current runtime
- Run: `Get-Content CHANGELOG.md`
  Expect: after the work lands, changelog or linked notes record whether wider v1.1-zh rollout is enabled or deferred
Touches: addon/synthDrivers/maxlogic_kokoro/_engine.py, addon/synthDrivers/maxlogic_kokoro/_helper_process.py, addon/synthDrivers/maxlogic_kokoro/_helper_client.py, CHANGELOG.md
Deps: T-008
Verify: cli-proof, manual
Notes: This task is the gate for exposing the full Chinese `zf_*` set and any future multi-model runtime path.

### T-003 [CLI] Add curated online voice catalog and verified downloader
Outcome:
- the add-on can read a MaxLogic-managed voice catalog JSON describing downloadable Kokoro voices
- catalog fetches are cached locally with defined stale/offline behavior so the UI can degrade gracefully when the network is unavailable
- downloads are written to a temporary location, verified with SHA-256, then installed through the same validation/install pipeline used by local installs
- download failures leave no partial voice files behind and produce actionable log messages
Proof:
- Run: `python -m py_compile addon\synthDrivers\maxlogic_kokoro\*.py addon\globalPlugins\maxlogic_kokoro_manager\*.py`
  Expect: exit=0
- Run: `Get-ChildItem "$env:APPDATA\nvda\maxlogicKokoroTTS\cache"`
  Expect: catalog cache files exist after a successful refresh and remain usable for offline listing
- Run: `Get-ChildItem "$env:APPDATA\nvda\maxlogicKokoroTTS\voices"`
  Expect: after a successful download, the final voice file exists only once in the user voice store
- Run: `Get-ChildItem "$env:APPDATA\nvda\maxlogicKokoroTTS\voices"`
  Expect: after a forced hash verification failure, no new final voice file exists in the user voice store
- Run: `Get-Content "C:\Users\pawel\AppData\Roaming\nvda\maxlogicKokoroTTS\logs\helper.log" -Tail 80`
  Expect: downloader/install logs show the selected voice id, verification result, and final install path
- Run: `Get-Content "C:\Users\pawel\AppData\Local\Temp\nvda.log" -Tail 150`
  Expect: NVDA log shows catalog refresh source (network or cache), download success or a clear verification failure, and no partial install left behind
Touches: addon/globalPlugins/, addon/synthDrivers/maxlogic_kokoro/_log.py, addon/synthDrivers/maxlogic_kokoro/_engine.py, docs/
Deps: T-001, T-002
Verify: cli-proof, manual
Notes: Prefer a MaxLogic-controlled catalog over scraping third-party repositories directly.

### T-004 [CLI] Add Voice Manager UI for installed and online voices
Outcome:
- users can open a MaxLogic Kokoro Voice Manager from NVDA and see installed voices separately from downloadable voices
- the manager provides download, remove, and refresh actions with accessible labels and status feedback
- the manager optionally displays provider/runtime status so users can confirm whether the synth is running on CUDA, DirectML, or CPU without blocking the first usable dialog
Proof:
- Run: `python -m py_compile addon\globalPlugins\maxlogic_kokoro_manager\*.py addon\synthDrivers\maxlogic_kokoro\*.py`
  Expect: exit=0
- Run: `Get-ChildItem "$env:APPDATA\nvda\maxlogicKokoroTTS\voices"`
  Expect: a manager-driven install or remove action produces the expected file-system change in the user voice store
- Run: `Get-Content "C:\Users\pawel\AppData\Local\Temp\nvda.log" -Tail 200`
  Expect: opening the manager and performing one action logs the selected voice and the resulting synth/provider state
- Run: `Get-Content "C:\Users\pawel\AppData\Roaming\nvda\maxlogicKokoroTTS\logs\helper.log" -Tail 120`
  Expect: helper-side logs correlate with the action taken in the manager when synthesis occurs
Touches: addon/globalPlugins/, addon/synthDrivers/maxlogic_kokoro/__init__.py, addon/synthDrivers/maxlogic_kokoro/_helper_client.py, addon/synthDrivers/maxlogic_kokoro/_log.py
Deps: T-001, T-003
Verify: manual, visual
Notes: Model the UI structure after Sonata’s voice manager, but keep the Kokoro workflow smaller and focused on voice embeddings.

## Next – Later

## Blocked

## Done

### T-006 [CLI] Add official Kokoro v1.1-zh catalog support
Outcome:
- the add-on can fetch and cache a second official catalog for `onnx-community/Kokoro-82M-v1.1-zh-ONNX` without breaking the existing v1.0 official catalog
- v1.1-zh catalog entries expose normalized metadata needed by the manager, including stable voice id, source file, language, and model family/version
- catalog refresh and cache status clearly distinguish the v1.1-zh source from the current official catalog
Proof:
- Run: `python -m py_compile addon\synthDrivers\maxlogic_kokoro\_catalog.py addon\globalPlugins\maxlogic_kokoro_manager\service.py`
  Expect: exit=0
- Run: `Get-ChildItem "$env:APPDATA\nvda\maxlogicKokoroTTS\cache"`
  Expect: after refreshing both official catalogs, separate cache files exist for v1.0 and v1.1-zh
- Run: `Get-Content "C:\Users\pawel\AppData\Local\Temp\nvda.log" -Tail 150`
  Expect: log shows a successful refresh or cache fallback for the v1.1-zh official catalog and identifies the source distinctly from the v1.0 catalog
Touches: addon/synthDrivers/maxlogic_kokoro/_catalog.py, addon/globalPlugins/maxlogic_kokoro_manager/service.py
Verify: cli-proof, manual
Notes: Source should target the ONNX community build rather than the PyTorch-only upstream tree.

### T-007 [UI] Add dedicated manager exposure for official v1.1-zh voices
Outcome:
- the voice manager exposes the v1.1-zh voice set separately from the existing official v1.0 list
- users can filter the new catalog by name, gender, and language without mixing it into the current official tab
- preview and selection status text remain accessible and understandable with the larger voice set
Proof:
- Run: `python -m py_compile addon\globalPlugins\maxlogic_kokoro_manager\voice_manager.py addon\globalPlugins\maxlogic_kokoro_manager\service.py`
  Expect: exit=0
- Run: `Get-Content "C:\Users\pawel\AppData\Local\Temp\nvda.log" -Tail 150`
  Expect: opening the voice manager and switching to the v1.1-zh view logs the selected catalog and does not raise UI/plugin import errors
Touches: addon/globalPlugins/maxlogic_kokoro_manager/voice_manager.py, addon/globalPlugins/maxlogic_kokoro_manager/service.py
Deps: T-006
Verify: manual, visual
Notes: Prefer a dedicated tab or equivalent first-class source view instead of silently merging v1.1-zh into the existing official list.

### T-008 [CLI] Roll out the low-risk v1.1-zh English subset
Outcome:
- the add-on makes the new English v1.1-zh voices `af_maple`, `af_sol`, and `bf_vale` available for preview and download
- downloaded v1.1-zh English voices install through the existing user-voice pipeline and remain clearly labeled as v1.1-zh voices
- documentation and UI text explain that this is the first supported subset of the broader v1.1-zh release
Proof:
- Run: `python -m py_compile addon\globalPlugins\maxlogic_kokoro_manager\*.py addon\synthDrivers\maxlogic_kokoro\*.py`
  Expect: exit=0
- Run: `Get-ChildItem "$env:APPDATA\nvda\maxlogicKokoroTTS\voices"`
  Expect: after installing one of the v1.1-zh English voices, the expected user-managed voice file exists in the voice store
- Run: `Get-Content "C:\Users\pawel\AppData\Roaming\nvda\maxlogicKokoroTTS\logs\helper.log" -Tail 120`
  Expect: preview or synthesis with a v1.1-zh English voice logs a successful helper request for the selected voice
Touches: addon/synthDrivers/maxlogic_kokoro/_catalog.py, addon/globalPlugins/maxlogic_kokoro_manager/, addon/doc/en/readme.md, readme.md
Deps: T-006, T-007
Verify: cli-proof, manual, visual
Notes: Keep the first rollout intentionally narrow so compatibility issues are isolated before exposing the broader v1.1-zh set.

### T-005 [UI] Add speech cache settings and maintenance controls
Outcome:
- the voice manager has a dedicated `Speech Cache` tab for cache configuration and maintenance
- users can configure cache enablement, maximum cache size in MB, and which utterance lengths are eligible for caching through a simple mode-based UI
- the tab shows current cache location, size, and entry count, and supports clear + compact actions
- cache policy persists under the add-on user-data directory and is applied by both the NVDA-side cache and the helper-side cache without reinstalling the add-on
- logs make cache activation and helper cache hits visible during proof
Proof:
- Run: `python -m py_compile addon\globalPlugins\maxlogic_kokoro_manager\*.py addon\synthDrivers\maxlogic_kokoro\*.py`
  Expect: exit=0
- Run: `Get-Content "C:\Users\pawel\AppData\Roaming\nvda\maxlogicKokoroTTS\logs\helper.log" -Tail 120`
  Expect: after repeating a short utterance, helper log shows cache startup and at least one helper cache hit
- Run: `@'`nimport os, sqlite3`npath = r"C:\Users\pawel\AppData\Roaming\nvda\maxlogicKokoroTTS\cache\speech-cache.sqlite3"`nprint(os.path.exists(path))`nconn = sqlite3.connect(path)`nprint(conn.execute("select count(*) from speech_cache").fetchone()[0])`nconn.close()`n'@ | python -`
  Expect: output shows the cache database exists and contains rows after speech is cached
- Run: `Get-Content "C:\Users\pawel\AppData\Local\Temp\nvda.log" -Tail 150`
  Expect: opening the manager and changing speech-cache settings logs cache activation and successful settings persistence
Touches: addon/globalPlugins/maxlogic_kokoro_manager/voice_manager.py, addon/globalPlugins/maxlogic_kokoro_manager/service.py, addon/synthDrivers/maxlogic_kokoro/__init__.py, addon/synthDrivers/maxlogic_kokoro/_helper_process.py, addon/synthDrivers/maxlogic_kokoro/_speech_cache.py
Verify: cli-proof, manual, visual
Notes: User-facing control should expose cache size only, not an entry-count limit. A hidden defensive row cap is intentionally omitted; eviction is size-driven.
