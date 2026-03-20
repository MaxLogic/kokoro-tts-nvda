# -*- coding: UTF-8 -*-


def _(arg):
	return arg


addon_info = {
	"addon_name": "maxlogicKokoroTTS",
	"addon_summary": _("MaxLogic Kokoro TTS"),
	"addon_description": _("""A conflict-free Kokoro TTS synthesizer for NVDA maintained by MaxLogic."""),
	"addon_version": "0.1.0",
	"addon_author": "MaxLogic",
	"addon_url": "https://github.com/MaxLogic/kokoro-tts-nvda",
	"addon_sourceURL": "https://github.com/MaxLogic/kokoro-tts-nvda",
	"addon_docFileName": "readme.html",
	"addon_minimumNVDAVersion": "2024.1",
	"addon_lastTestedNVDAVersion": "2025.1",
	"addon_updateChannel": None,
	"addon_license": "MIT",
	"addon_licenseURL": "https://github.com/MaxLogic/kokoro-tts-nvda/blob/main/LICENSE",
}

pythonSources = [
	"addon/installTasks.py",
	"addon/globalPlugins/*/*.py",
	"addon/synthDrivers/*/*.py",
]

i18nSources = pythonSources + ["buildVars.py"]

excludedFiles = []

baseLanguage = "en"

markdownExtensions = []
