import base64
import json
import os
import subprocess
import threading
import time
import sys

try:
	from ._log import get_helper_log_path
except ImportError:
	sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
	from _log import get_helper_log_path


class HelperEngineClient(object):
	sample_rate = 24000

	def __init__(self, package_root, logger):
		self.package_root = package_root
		self.logger = logger
		self._request_id = 0
		self._voice = None
		self._voices = []
		self._providers = []
		self._process = None
		self._stderr_thread = None
		self._start()

	@classmethod
	def should_try(cls, package_root):
		if os.environ.get("MAXLOGIC_KOKORO_HELPER_PYTHON"):
			return True
		if os.environ.get("MAXLOGIC_KOKORO_FORCE_HELPER") == "1":
			return True
		repo_python = cls._repo_helper_python(package_root)
		return os.path.isfile(repo_python)

	@classmethod
	def _repo_root(cls, package_root):
		candidate = os.path.abspath(package_root)
		for _ in range(5):
			if os.path.isfile(os.path.join(candidate, "manifest.ini")):
				return candidate
			if os.path.isfile(os.path.join(candidate, ".helper-venv", "Scripts", "python.exe")):
				return candidate
			parent = os.path.dirname(candidate)
			if parent == candidate:
				break
			candidate = parent
		return os.path.abspath(os.path.join(package_root, "..", ".."))

	@classmethod
	def _repo_helper_python(cls, package_root):
		return os.path.join(cls._repo_root(package_root), ".helper-venv", "Scripts", "python.exe")

	@classmethod
	def _candidate_commands(cls, package_root):
		helper_script = os.path.join(package_root, "_helper_process.py")
		repo_python = cls._repo_helper_python(package_root)
		env_python = os.environ.get("MAXLOGIC_KOKORO_HELPER_PYTHON")
		candidates = []
		if env_python:
			candidates.append([env_python, helper_script])
		if os.path.isfile(repo_python):
			candidates.append([repo_python, helper_script])
		candidates.append(["py", "-3.11", helper_script])
		return candidates

	def _start(self):
		last_error = None
		for command in self._candidate_commands(self.package_root):
			try:
				self.logger.info("Starting MaxLogic Kokoro helper with command %s", command)
				self._process = subprocess.Popen(
					command,
					stdin=subprocess.PIPE,
					stdout=subprocess.PIPE,
					stderr=subprocess.PIPE,
					text=True,
					encoding="utf-8",
					errors="replace",
					bufsize=1,
					creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
				)
				self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
				self._stderr_thread.start()
				ready = self._read_message()
				if ready.get("ok"):
					self._voices = ready["voices"]
					self._voice = ready["current_voice"]
					self._providers = ready["providers"]
					self.sample_rate = ready.get("sample_rate", self.sample_rate)
					self.logger.info(
						"Using MaxLogic Kokoro helper pid=%s with providers %s, voices=%s, helperLog=%s",
						self._process.pid,
						self._providers,
						len(self._voices),
						get_helper_log_path(),
					)
					return
				last_error = RuntimeError(ready.get("error", "helper start failed"))
				self.logger.warning("MaxLogic Kokoro helper start failed for command %s: %s", command, last_error)
				self.close()
			except Exception as error:
				last_error = error
				self.logger.warning("MaxLogic Kokoro helper launch failed for command %s: %s", command, error)
				self.close()
		raise RuntimeError("Unable to start MaxLogic Kokoro helper: %s" % last_error)

	def _drain_stderr(self):
		if self._process is None or self._process.stderr is None:
			return
		for line in self._process.stderr:
			line = line.rstrip()
			if line:
				self.logger.debug("Helper: %s", line)

	def _read_message(self):
		line = self._process.stdout.readline()
		if not line:
			raise RuntimeError("Helper process exited before responding")
		return json.loads(line)

	def _request(self, payload):
		self._request_id += 1
		payload = dict(payload)
		payload["id"] = self._request_id
		start_time = time.perf_counter()
		self._process.stdin.write(json.dumps(payload) + "\n")
		self._process.stdin.flush()
		response = self._read_message()
		if not response.get("ok"):
			self.logger.warning("Helper request failed. op=%s error=%s", payload.get("op"), response.get("error"))
			raise RuntimeError(response.get("error", "Unknown helper error"))
		elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
		if payload.get("op") == "synthesize":
			audio_b64 = response.get("audio_b64", "")
			self.logger.info(
				"Helper synthesize response. chars=%s voice=%s elapsedMs=%s audioBytes~=%s",
				len(payload.get("text", "")),
				payload.get("voice") or self._voice,
				elapsed_ms,
				int((len(audio_b64) * 3) / 4),
			)
		return response

	def list_voices(self):
		return list(self._voices)

	def set_voice(self, voice_name):
		self._request({"op": "set_voice", "voice": voice_name})
		self._voice = voice_name

	@property
	def current_voice(self):
		return self._voice

	def synthesize_to_int16(self, text, speed=0.85, voice=None, volume=1.0, language="en-us"):
		response = self._request(
			{
				"op": "synthesize",
				"text": text,
				"speed": speed,
				"voice": voice,
				"volume": volume,
				"language": language,
			}
		)
		return memoryview(base64.b64decode(response["audio_b64"]))

	def close(self):
		process = self._process
		self._process = None
		if process is None:
			return
		try:
			if process.stdin and process.stdout and process.poll() is None:
				process.stdin.write(json.dumps({"id": 0, "op": "shutdown"}) + "\n")
				process.stdin.flush()
		except Exception:
			pass
		try:
			process.terminate()
		except Exception:
			pass
		self.logger.info("MaxLogic Kokoro helper closed. pid=%s", process.pid)
