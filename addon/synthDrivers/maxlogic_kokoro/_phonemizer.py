import os
import subprocess


DEFAULT_REFERENCE_ROOT = os.path.join(
	os.environ.get("APPDATA", ""),
	"nvda",
	"addons",
	"kokoroTTS",
	"synthDrivers",
	"kokoro",
)


class EspeakPhonemizer(object):
	def __init__(self, package_root):
		self.package_root = package_root
		self.espeak_root = self._resolve_espeak_root()
		self.exe_path = os.path.join(self.espeak_root, "espeak-ng.exe")
		self.data_path = os.path.join(self.espeak_root, "espeak-ng-data")

	def _resolve_espeak_root(self):
		override_root = os.environ.get("MAXLOGIC_KOKORO_ASSET_ROOT")
		candidates = [
			os.path.join(self.package_root, "espeak"),
		]
		if override_root:
			candidates.append(os.path.join(override_root, "espeak"))
		candidates.append(os.path.join(DEFAULT_REFERENCE_ROOT, "espeak"))
		for candidate in candidates:
			exe_path = os.path.join(candidate, "espeak-ng.exe")
			data_path = os.path.join(candidate, "espeak-ng-data")
			if os.path.isfile(exe_path) and os.path.isdir(data_path):
				return candidate
		raise RuntimeError(
			"eSpeak-NG assets were not found. Copy them into addon/synthDrivers/maxlogic_kokoro/espeak "
			"or set MAXLOGIC_KOKORO_ASSET_ROOT."
		)

	def phonemize(self, text, language="en-us"):
		if not text.strip():
			return ""
		result = subprocess.run(
			[
				self.exe_path,
				"--ipa",
				"-q",
				"--path",
				self.data_path,
				"-v",
				language,
				text,
			],
			capture_output=True,
			check=True,
			creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
		)
		return result.stdout.decode("utf-8", errors="replace").strip()
