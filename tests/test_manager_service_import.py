import importlib.util
import builtins
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = ROOT / "addon" / "globalPlugins" / "maxlogic_kokoro_manager" / "service.py"


class ManagerServiceImportTests(unittest.TestCase):
	def setUp(self):
		self._saved_modules = dict(sys.modules)
		self._saved_path = list(sys.path)
		self._saved_translation = getattr(builtins, "_", None)

	def tearDown(self):
		sys.modules.clear()
		sys.modules.update(self._saved_modules)
		sys.path[:] = self._saved_path
		if self._saved_translation is None:
			try:
				delattr(builtins, "_")
			except AttributeError:
				pass
		else:
			builtins._ = self._saved_translation

	def test_service_import_does_not_require_engine_runtime_dependencies(self):
		def init_translation():
			builtins._ = lambda text: text
			return None

		sys.modules["addonHandler"] = types.SimpleNamespace(initTranslation=init_translation)
		sys.modules["config"] = types.SimpleNamespace(conf={"audio": {}})
		sys.modules["nvwave"] = types.SimpleNamespace(WavePlayer=object)
		sys.modules["synthDriverHandler"] = types.SimpleNamespace(getSynth=lambda: None)
		sys.modules["wx"] = types.SimpleNamespace(CallAfter=lambda callback, *args: callback(*args))
		sys.modules["logHandler"] = types.SimpleNamespace(
			log=types.SimpleNamespace(
				info=lambda *args, **kwargs: None,
				warning=lambda *args, **kwargs: None,
				exception=lambda *args, **kwargs: None,
			)
		)

		sys.modules["synthDrivers"] = types.ModuleType("synthDrivers")
		sys.modules["synthDrivers.maxlogic_kokoro"] = types.ModuleType("synthDrivers.maxlogic_kokoro")
		sys.modules["synthDrivers.maxlogic_kokoro._catalog"] = types.SimpleNamespace(
			download_catalog_voice=lambda *args, **kwargs: None,
			download_catalog_voice_to_temp=lambda *args, **kwargs: None,
			get_catalog_entries=lambda *args, **kwargs: ([], {}),
		)
		sys.modules["synthDrivers.maxlogic_kokoro._cache_settings"] = types.SimpleNamespace(
			CACHE_MODE_CUSTOM="custom",
			CACHE_MODE_SHORT_MEDIUM="short_medium",
			CACHE_MODE_SHORT_UI="short_ui",
			load_cache_settings=lambda: {},
			resolve_cache_policy=lambda settings: settings,
			save_cache_settings=lambda settings: settings,
		)
		sys.modules["synthDrivers.maxlogic_kokoro._helper_client"] = types.SimpleNamespace(
			HelperEngineClient=object
		)
		sys.modules["synthDrivers.maxlogic_kokoro._phonemizer"] = types.SimpleNamespace(
			DEFAULT_REFERENCE_ROOT="reference-root"
		)
		sys.modules["synthDrivers.maxlogic_kokoro._voice_store"] = types.SimpleNamespace(
			DuplicateVoiceError=type("DuplicateVoiceError", (Exception,), {}),
			VoiceStoreError=type("VoiceStoreError", (Exception,), {}),
			discover_voice_records=lambda *args, **kwargs: ({}, []),
			install_voice_files=lambda *args, **kwargs: [],
			list_user_voice_records=lambda: [],
			remove_user_voice=lambda voice_id: [],
		)
		sys.modules["synthDrivers.maxlogic_kokoro._engine"] = types.ModuleType(
			"synthDrivers.maxlogic_kokoro._engine"
		)

		spec = importlib.util.spec_from_file_location("manager_service_under_test", SERVICE_PATH)
		module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(module)

		self.assertEqual("reference-root", module.DEFAULT_REFERENCE_ROOT)


if __name__ == "__main__":
	unittest.main()
