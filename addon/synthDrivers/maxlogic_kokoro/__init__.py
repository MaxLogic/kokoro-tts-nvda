import os
import queue
import re
import sys
import threading
import time
import traceback

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

try:
	from ._speech_cache import SpeechCache
except Exception as error:
	SpeechCache = None
	log.warning("MaxLogic Kokoro speech cache unavailable: %s", error)


addonHandler.initTranslation()


class SynthDriver(synthDriverHandler.SynthDriver):
	name = "maxlogic_kokoro"
	description = "MaxLogic Kokoro TTS"
	firstChunkTargetChars = 72
	firstChunkMaxChars = 120
	targetChunkChars = 200
	maxChunkChars = 280
	prefetchQueueSize = 2
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
		self._voice = None
		self._availableVoices = {}
		self._reload_voices(log_reason="init")
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
		self._speechCache = None
		if SpeechCache is not None:
			try:
				self._speechCache = SpeechCache(log)
			except Exception as error:
				log.warning("MaxLogic Kokoro speech cache disabled: %s", error)
			else:
				log.info("MaxLogic Kokoro speech cache enabled. db=%s", self._speechCache.db_path)
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
			record = getattr(self._engine, "voice_records", {}).get(voice_name)
			display_name = record.display_name if record is not None else voice_name.replace("_", " ").title()
			lang_code = "en"
			try:
				voices[voice_name] = VoiceInfo(voice_name, display_name, lang_code)
			except TypeError:
				voices[voice_name] = VoiceInfo(voice_name, display_name)
		return voices

	def _reload_voices(self, log_reason="manual", preferred_voice=None):
		reload_start = time.perf_counter()
		current_voice = self._engine.reload_voices(preferred_voice=preferred_voice or self._voice)
		self._availableVoices = self._build_available_voices()
		self._voice = current_voice
		elapsed_ms = round((time.perf_counter() - reload_start) * 1000, 1)
		status = self.getRuntimeStatus()
		log.info(
			"MaxLogic Kokoro voices reloaded. reason=%s currentVoice=%s voiceCount=%s elapsedMs=%s providers=%s",
			log_reason,
			self._voice,
			len(self._availableVoices),
			elapsed_ms,
			status.get("providers"),
		)
		return self._voice

	@property
	def availableVoices(self):
		return self._availableVoices

	def reloadVoiceStore(self, reason="manual", preferred_voice=None):
		return self._reload_voices(log_reason=reason, preferred_voice=preferred_voice)

	def getRuntimeStatus(self):
		if hasattr(self._engine, "get_status"):
			return self._engine.get_status()
		providers = []
		if hasattr(self._engine, "session"):
			providers = self._engine.session.get_providers()
		return {
			"mode": "in-process",
			"providers": providers,
			"voiceCount": len(self._availableVoices),
			"currentVoice": self._voice,
			"pid": os.getpid(),
		}

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
		if self._speechCache is not None:
			self._speechCache.close()
			self._speechCache = None
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
		speed = self._nvda_rate_to_speed(task["rate"])
		volume = max(0.0, min(1.0, task["volume"] / 100.0))
		self._ensure_player()
		chunks = self._chunk_text_for_playback(task["text"])
		if not chunks:
			return
		audio_queue = queue.Queue(maxsize=self.prefetchQueueSize)
		stop_event = threading.Event()
		producer = threading.Thread(
			target=self._produce_chunk_audio,
			args=(audio_queue, stop_event, chunks, speed, task["voice"], volume, task["language"]),
			name="MaxLogicKokoroPrefetch",
			daemon=True,
		)
		producer.start()
		chunk_count = 0
		try:
			while True:
				if generation != self._generation or self._terminated:
					stop_event.set()
					return
				try:
					item = audio_queue.get(timeout=0.05)
				except queue.Empty:
					continue
				if item is None:
					break
				if isinstance(item, dict) and "error" in item:
					raise RuntimeError(item["error"])
				chunk, audio_bytes = item
				chunk_count += 1
				self._player.feed(audio_bytes)
		finally:
			stop_event.set()
		if len(chunks) > 1:
			log.info(
				"MaxLogic Kokoro chunked speech. chunkCount=%s firstChunkChars=%s textChars=%s language=%s voice=%s speed=%s",
				chunk_count,
				len(chunks[0]),
				len(task["text"]),
				task["language"],
				task["voice"],
				speed,
			)
		self._player.idle()

	def _produce_chunk_audio(self, audio_queue, stop_event, chunks, speed, voice, volume, language):
		try:
			for item in self._synthesize_chunks_with_fallback(
				chunks,
				speed=speed,
				voice=voice,
				volume=volume,
				language=language,
				stop_event=stop_event,
			):
				if stop_event.is_set():
					return
				while not stop_event.is_set():
					try:
						audio_queue.put(item, timeout=0.05)
						break
					except queue.Full:
						continue
		except Exception:
			error_item = {"error": traceback.format_exc()}
			while not stop_event.is_set():
				try:
					audio_queue.put(error_item, timeout=0.05)
					break
				except queue.Full:
					continue
		finally:
			while not stop_event.is_set():
				try:
					audio_queue.put(None, timeout=0.05)
					break
				except queue.Full:
					continue

	def _chunk_text_for_playback(self, text):
		text = re.sub(r"\s+", " ", (text or "")).strip()
		if not text:
			return []
		chunks = []
		remaining = text
		first = True
		while remaining:
			target = self.firstChunkTargetChars if first else self.targetChunkChars
			max_chars = self.firstChunkMaxChars if first else self.maxChunkChars
			chunk, remaining = self._split_text_once(
				remaining,
				target_chars=target,
				max_chars=max_chars,
				min_chars=48 if first else 72,
			)
			chunks.append(chunk)
			first = False
		return chunks

	def _split_text_once(self, text, target_chars, max_chars, min_chars=48):
		if len(text) <= max_chars:
			return text, ""
		search_end = min(len(text), max_chars)
		boundary = self._find_preferred_boundary(text, target_chars, search_end, min_chars)
		if boundary is None:
			boundary = search_end
		chunk = text[:boundary].strip()
		remaining = text[boundary:].strip()
		if not chunk:
			chunk = text[:search_end].strip()
			remaining = text[search_end:].strip()
		return chunk, remaining

	def _find_preferred_boundary(self, text, target_chars, search_end, min_chars):
		candidates = []
		target_window_end = min(search_end, max(target_chars + 48, min_chars))
		for index in range(min_chars, search_end):
			char = text[index]
			next_char = text[index + 1] if index + 1 < len(text) else ""
			prev_char = text[index - 1] if index > 0 else ""
			boundary = None
			priority = None
			if char in ".!?" and (not next_char or next_char.isspace() or next_char in "\"')]}"):
				boundary = index + 1
				priority = 0
			elif char in ",;:" and (not next_char or next_char.isspace()):
				boundary = index + 1
				priority = 1
			elif char in "-\u2013\u2014" and prev_char.isspace() and (not next_char or next_char.isspace()):
				boundary = index + 1
				priority = 2
			elif char.isspace():
				boundary = index
				priority = 3
			if boundary is None:
				continue
			if boundary < min_chars or boundary > search_end:
				continue
			if boundary <= target_window_end:
				distance = abs(target_chars - boundary)
			else:
				distance = 1000 + (boundary - target_window_end)
			candidates.append((priority, distance, -boundary, boundary))
		if not candidates:
			return None
		candidates.sort()
		return candidates[0][3]

	def _synthesize_chunks_with_fallback(self, chunks, speed, voice, volume, language, stop_event=None):
		for chunk in chunks:
			if stop_event is not None and stop_event.is_set():
				return
			for item in self._synthesize_chunk_with_fallback(
				chunk,
				speed=speed,
				voice=voice,
				volume=volume,
				language=language,
				depth=0,
				stop_event=stop_event,
			):
				yield item

	def _synthesize_chunk_with_fallback(self, text, speed, voice, volume, language, depth, stop_event=None):
		if stop_event is not None and stop_event.is_set():
			return
		cached_audio = self._get_cached_audio(text, voice, speed, volume, language)
		if cached_audio is not None:
			yield text, cached_audio
			return
		try:
			audio = self._engine.synthesize_to_int16(
				text,
				speed=speed,
				voice=voice,
				volume=volume,
				language=language,
			)
			audio_bytes = audio.tobytes() if hasattr(audio, "tobytes") else bytes(audio)
			self._store_cached_audio(text, voice, speed, volume, language, audio_bytes)
			yield text, audio_bytes
			return
		except Exception as error:
			message = str(error)
			if depth >= 3 or len(text) < 48 or "Expand node" not in message:
				raise
			left, right = self._split_text_once(
				text,
				target_chars=max(48, len(text) // 2),
				max_chars=max(72, len(text) // 2 + 32),
				min_chars=32,
			)
			if not left or not right:
				raise
			log.warning("MaxLogic Kokoro retried oversized chunk by splitting it. chars=%s depth=%s", len(text), depth + 1)
			for chunk in (left, right):
				for item in self._synthesize_chunk_with_fallback(
					chunk,
					speed=speed,
					voice=voice,
					volume=volume,
					language=language,
					depth=depth + 1,
					stop_event=stop_event,
				):
					yield item

	def _get_cached_audio(self, text, voice, speed, volume, language):
		if self._speechCache is None:
			return None
		try:
			return self._speechCache.get_audio(voice, speed, volume, language, text)
		except Exception:
			log.debug("MaxLogic Kokoro cache read failed", exc_info=True)
			return None

	def _store_cached_audio(self, text, voice, speed, volume, language, audio_bytes):
		if self._speechCache is None:
			return
		try:
			self._speechCache.put_audio(voice, speed, volume, language, text, audio_bytes)
		except Exception:
			log.debug("MaxLogic Kokoro cache write failed", exc_info=True)

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
		return max(0.5, min(1.5, 0.5 + (rate / 100.0)))

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
