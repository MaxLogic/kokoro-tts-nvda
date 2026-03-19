import os
import queue
import sys
import threading

import addonHandler
import config
import nvwave
import synthDriverHandler
from logHandler import log
from speech.commands import BreakCommand, IndexCommand, LangChangeCommand, RateCommand, VolumeCommand
from synthDriverHandler import VoiceInfo, synthDoneSpeaking, synthIndexReached


PACKAGE_ROOT = os.path.dirname(os.path.abspath(__file__))
REFERENCE_ROOT = os.path.join(
	os.environ.get("APPDATA", ""),
	"nvda",
	"addons",
	"kokoroTTS",
	"synthDrivers",
	"kokoro",
)

for deps_root in (
	os.path.join(PACKAGE_ROOT, "deps"),
	os.path.join(os.environ.get("MAXLOGIC_KOKORO_ASSET_ROOT", ""), "deps") if os.environ.get("MAXLOGIC_KOKORO_ASSET_ROOT") else None,
	os.path.join(REFERENCE_ROOT, "deps"),
):
	if deps_root and os.path.isdir(deps_root) and deps_root not in sys.path:
		sys.path.insert(0, deps_root)

_ENGINE_IMPORT_ERROR = None
try:
	from ._engine import KokoroEngine
except Exception as error:
	KokoroEngine = None
	_ENGINE_IMPORT_ERROR = error

try:
	from ._helper_client import HelperEngineClient
except Exception:
	HelperEngineClient = None


addonHandler.initTranslation()


class SynthDriver(synthDriverHandler.SynthDriver):
	name = "maxlogic_kokoro"
	description = "MaxLogic Kokoro TTS"
	supportedSettings = (
		synthDriverHandler.SynthDriver.VoiceSetting(),
		synthDriverHandler.SynthDriver.RateSetting(),
		synthDriverHandler.SynthDriver.VolumeSetting(),
	)
	supportedCommands = {
		BreakCommand,
		IndexCommand,
		LangChangeCommand,
		RateCommand,
		VolumeCommand,
	}
	supportedNotifications = {synthIndexReached, synthDoneSpeaking}

	@classmethod
	def check(cls):
		if HelperEngineClient is not None and HelperEngineClient.should_try(PACKAGE_ROOT):
			log.info("MaxLogic Kokoro check passed via helper availability.")
			return True
		if _ENGINE_IMPORT_ERROR is not None:
			log.warning("MaxLogic Kokoro unavailable, runtime import failed: %s", _ENGINE_IMPORT_ERROR)
			return False
		missing = KokoroEngine.check_runtime_requirements(PACKAGE_ROOT)
		if missing:
			log.warning("MaxLogic Kokoro unavailable, missing assets: %s", ", ".join(missing))
			return False
		return True

	def __init__(self):
		super(SynthDriver, self).__init__()
		self._engine = self._create_engine()
		self._rate = 50
		self._volume = 100
		self._voice = self._engine.current_voice
		self._availableVoices = self._build_available_voices()
		log.info(
			"MaxLogic Kokoro initialized. engine=%s voiceCount=%s currentVoice=%s sampleRate=%s",
			type(self._engine).__name__,
			len(self._availableVoices),
			self._voice,
			self._engine.sample_rate,
		)
		self._queue = queue.Queue()
		self._generation = 0
		self._terminated = False
		self._player = None
		self._worker = threading.Thread(target=self._speech_worker, name="MaxLogicKokoroSpeech", daemon=True)
		self._worker.start()

	def _create_engine(self):
		if HelperEngineClient is not None and HelperEngineClient.should_try(PACKAGE_ROOT):
			try:
				return HelperEngineClient(PACKAGE_ROOT, log)
			except Exception as error:
				log.warning("MaxLogic Kokoro helper unavailable, falling back to in-process engine: %s", error)
		if _ENGINE_IMPORT_ERROR is not None:
			raise _ENGINE_IMPORT_ERROR
		engine = KokoroEngine(PACKAGE_ROOT)
		log.info("Using in-process MaxLogic Kokoro engine with providers %s", engine.session.get_providers())
		return engine

	def _build_available_voices(self):
		voices = {}
		for voice_name in self._engine.list_voices():
			display_name = voice_name.replace("_", " ").title()
			lang_code = "en"
			try:
				voices[voice_name] = VoiceInfo(voice_name, display_name, lang_code)
			except TypeError:
				voices[voice_name] = VoiceInfo(voice_name, display_name)
		return voices

	@property
	def availableVoices(self):
		return self._availableVoices

	def _ensure_player(self):
		if self._player is None:
			output_device = None
			try:
				output_device = config.conf["audio"]["outputDevice"]
			except Exception:
				pass
			self._player = nvwave.WavePlayer(
				channels=1,
				samplesPerSec=self._engine.sample_rate,
				bitsPerSample=16,
				outputDevice=output_device,
			)

	def terminate(self):
		self._terminated = True
		self.cancel()
		self._queue.put(None)
		if self._worker.is_alive():
			self._worker.join(timeout=1.0)
		if self._player is not None:
			self._player.close()
			self._player = None
		if hasattr(self._engine, "close"):
			self._engine.close()
		log.info("MaxLogic Kokoro terminated.")
		super(SynthDriver, self).terminate()

	def cancel(self):
		self._generation += 1
		while True:
			try:
				self._queue.get_nowait()
			except queue.Empty:
				break
		if self._player is not None:
			self._player.stop()

	def pause(self, switch):
		if self._player is not None and hasattr(self._player, "pause"):
			self._player.pause(switch)

	def speak(self, speechSequence):
		self.cancel()
		generation = self._generation
		tasks = self._sequence_to_tasks(speechSequence)
		text_chars = sum(len(task["text"]) for task in tasks if task["type"] == "speak")
		log.info(
			"MaxLogic Kokoro queued speech. generation=%s tasks=%s textChars=%s voice=%s rate=%s volume=%s",
			generation,
			len(tasks),
			text_chars,
			self._voice,
			self._rate,
			self._volume,
		)
		self._queue.put((generation, tasks))

	def _sequence_to_tasks(self, speechSequence):
		tasks = []
		text_buffer = []
		current_rate = self._rate
		current_volume = self._volume
		current_lang = "en-us"
		for item in speechSequence:
			item_type = type(item)
			if item_type is str:
				text_buffer.append(item)
				continue
			if text_buffer:
				tasks.append(
					{
						"type": "speak",
						"text": "".join(text_buffer),
						"rate": current_rate,
						"volume": current_volume,
						"voice": self._voice,
						"language": current_lang,
					}
				)
				text_buffer = []
			if item_type is IndexCommand:
				tasks.append({"type": "index", "index": item.index})
			elif item_type is BreakCommand:
				tasks.append({"type": "break", "time": int(item.time)})
			elif item_type is RateCommand:
				current_rate = int(item.newValue)
			elif item_type is VolumeCommand:
				current_volume = int(item.newValue)
			elif item_type is LangChangeCommand:
				current_lang = "en-us" if item.isDefault else (item.lang or current_lang)
		if text_buffer:
			tasks.append(
				{
					"type": "speak",
					"text": "".join(text_buffer),
					"rate": current_rate,
					"volume": current_volume,
					"voice": self._voice,
					"language": current_lang,
				}
			)
		return tasks

	def _speech_worker(self):
		while True:
			item = self._queue.get()
			if item is None:
				return
			generation, tasks = item
			try:
				for task in tasks:
					if generation != self._generation or self._terminated:
						break
					task_type = task["type"]
					if task_type == "speak":
						self._speak_task(task, generation)
					elif task_type == "break":
						self._play_silence(task["time"], generation)
					elif task_type == "index":
						synthIndexReached.notify(synth=self, index=task["index"])
				if generation == self._generation and not self._terminated:
					synthDoneSpeaking.notify(synth=self)
			except Exception:
				log.exception("MaxLogic Kokoro speech worker failed", exc_info=True)

	def _speak_task(self, task, generation):
		audio = self._engine.synthesize_to_int16(
			task["text"],
			speed=self._nvda_rate_to_speed(task["rate"]),
			voice=task["voice"],
			volume=max(0.0, min(1.0, task["volume"] / 100.0)),
			language=task["language"],
		)
		if generation != self._generation or self._terminated:
			return
		self._ensure_player()
		self._player.feed(audio.tobytes())
		self._player.idle()

	def _play_silence(self, duration_ms, generation):
		if duration_ms <= 0:
			return
		if generation != self._generation or self._terminated:
			return
		self._ensure_player()
		frame_count = int(self._engine.sample_rate * (duration_ms / 1000.0))
		if frame_count <= 0:
			return
		self._player.feed((b"\x00\x00" * frame_count))
		self._player.idle()

	def _nvda_rate_to_speed(self, rate):
		rate = max(0, min(100, int(rate)))
		return max(0.5, min(1.5, 1.5 - (rate / 100.0)))

	def _get_rate(self):
		return self._rate

	def _set_rate(self, value):
		self._rate = max(0, min(100, int(value)))

	def _get_volume(self):
		return self._volume

	def _set_volume(self, value):
		self._volume = max(0, min(100, int(value)))

	def _get_voice(self):
		return self._voice

	def _set_voice(self, value):
		if value not in self._availableVoices:
			raise KeyError("Unknown voice: %s" % value)
		self._engine.set_voice(value)
		self._voice = value
		log.info("MaxLogic Kokoro voice changed to %s", value)
