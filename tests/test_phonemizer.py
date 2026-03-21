import importlib.util
import subprocess
import unittest
from unittest import mock
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[1] / "addon" / "synthDrivers" / "maxlogic_kokoro" / "_phonemizer.py"
_SPEC = importlib.util.spec_from_file_location("test_target_phonemizer", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
EspeakPhonemizer = _MODULE.EspeakPhonemizer


class EspeakPhonemizerTests(unittest.TestCase):
	def _make_phonemizer(self):
		phonemizer = object.__new__(EspeakPhonemizer)
		phonemizer.exe_path = "C:\\fake\\espeak-ng.exe"
		phonemizer.data_path = "C:\\fake\\espeak-ng-data"
		return phonemizer

	def test_phonemize_terminates_option_parsing_before_text(self):
		phonemizer = self._make_phonemizer()
		completed = subprocess.CompletedProcess(
			args=[],
			returncode=0,
			stdout="tˈɛst θɹˈiː".encode("utf-8"),
			stderr=b"",
		)
		with mock.patch.object(_MODULE.subprocess, "run", return_value=completed) as run_mock:
			result = phonemizer.phonemize("- test 3")

		self.assertEqual("tˈɛst θɹˈiː", result)
		args = run_mock.call_args.args[0]
		self.assertEqual("--", args[-2])
		self.assertEqual("- test 3", args[-1])

	def test_phonemize_raises_clear_error_when_espeak_writes_only_stderr(self):
		phonemizer = self._make_phonemizer()
		completed = subprocess.CompletedProcess(
			args=[],
			returncode=0,
			stdout=b"",
			stderr=b"unknown option --",
		)
		with mock.patch.object(_MODULE.subprocess, "run", return_value=completed):
			with self.assertRaisesRegex(RuntimeError, "unknown option --"):
				phonemizer.phonemize("- test 3")


if __name__ == "__main__":
	unittest.main()
