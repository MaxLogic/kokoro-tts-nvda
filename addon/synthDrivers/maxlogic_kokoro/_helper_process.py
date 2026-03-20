import base64
import json
import logging
import os
import sys
import time
import traceback

from _engine import KokoroEngine
from _log import configure_helper_file_logger, get_helper_log_path
from _speech_cache import SpeechCache


logging.basicConfig(level=logging.INFO, format="[maxlogic-kokoro-helper] %(message)s")
LOGGER = logging.getLogger("maxlogic_kokoro_helper")
PACKAGE_ROOT = os.path.dirname(os.path.abspath(__file__))
HELPER_LOG_PATH = configure_helper_file_logger(LOGGER)


def _send(payload):
	sys.stdout.write(json.dumps(payload) + "\n")
	sys.stdout.flush()


def _prewarm_engine(engine):
	start_time = time.perf_counter()
	try:
		engine.synthesize_to_int16("Warm up.", speed=1.0, voice=engine.current_voice, volume=0.0, language="en-us")
		LOGGER.info(
			"Helper prewarm complete. voice=%s elapsedMs=%s",
			engine.current_voice,
			round((time.perf_counter() - start_time) * 1000, 1),
		)
	except Exception as error:
		LOGGER.warning("Helper prewarm failed: %s", error)


def main():
	LOGGER.info("Helper starting. pid=%s packageRoot=%s logPath=%s", os.getpid(), PACKAGE_ROOT, HELPER_LOG_PATH)
	speech_cache = None
	try:
		engine = KokoroEngine(PACKAGE_ROOT)
		try:
			speech_cache = SpeechCache(LOGGER)
		except Exception as cache_error:
			speech_cache = None
			LOGGER.warning("Helper speech cache disabled: %s", cache_error)
		_prewarm_engine(engine)
		LOGGER.info(
			"Helper ready. providers=%s currentVoice=%s voiceCount=%s sampleRate=%s cacheDb=%s",
			engine.session.get_providers(),
			engine.current_voice,
			len(engine.list_voices()),
			engine.sample_rate,
			speech_cache.db_path if speech_cache is not None else "disabled",
		)
		_send(
			{
				"ok": True,
				"type": "ready",
				"voices": engine.list_voices(),
				"current_voice": engine.current_voice,
				"providers": engine.session.get_providers(),
				"sample_rate": engine.sample_rate,
			}
		)
	except Exception as error:
		_send(
			{
				"ok": False,
				"type": "ready",
				"error": str(error),
				"traceback": traceback.format_exc(),
			}
		)
		return 1

	try:
		for line in sys.stdin:
			line = line.strip()
			if not line:
				continue
			try:
				request = json.loads(line)
				request_id = request.get("id")
				op = request.get("op")
				if op == "shutdown":
					LOGGER.info("Helper shutdown requested.")
					_send({"ok": True, "id": request_id})
					return 0
				if op == "set_voice":
					LOGGER.info("Helper set_voice request. voice=%s", request["voice"])
					engine.set_voice(request["voice"])
					_send({"ok": True, "id": request_id, "current_voice": engine.current_voice})
					continue
				if op == "reload_voices":
					preferred_voice = request.get("preferred_voice")
					current_voice = engine.reload_voices(preferred_voice=preferred_voice)
					LOGGER.info(
						"Helper reload_voices request complete. preferredVoice=%s currentVoice=%s voiceCount=%s",
						preferred_voice,
						current_voice,
						len(engine.list_voices()),
					)
					_send(
						{
							"ok": True,
							"id": request_id,
							"current_voice": current_voice,
							"voices": engine.list_voices(),
							"providers": engine.session.get_providers(),
							"sample_rate": engine.sample_rate,
						}
					)
					continue
				if op == "synthesize":
					start_time = time.perf_counter()
					text = request["text"]
					voice = request.get("voice") or engine.current_voice
					language = request.get("language", "en-us")
					speed = request.get("speed", 0.85)
					volume = request.get("volume", 1.0)
					audio_bytes = None
					if speech_cache is not None:
						try:
							audio_bytes = speech_cache.get_audio(voice, speed, volume, language, text)
						except Exception as cache_error:
							LOGGER.warning("Helper speech cache read failed: %s", cache_error)
							audio_bytes = None
					if audio_bytes is not None:
						LOGGER.info(
							"Helper cache hit. chars=%s voice=%s lang=%s speed=%s volume=%s bytes=%s",
							len(text),
							voice,
							language,
							speed,
							volume,
							len(audio_bytes),
						)
					else:
						audio = engine.synthesize_to_int16(
							text,
							speed=speed,
							voice=voice,
							volume=volume,
							language=language,
						)
						audio_bytes = audio.tobytes()
						if speech_cache is not None:
							try:
								speech_cache.put_audio(voice, speed, volume, language, text, audio_bytes)
							except Exception as cache_error:
								LOGGER.warning("Helper speech cache write failed: %s", cache_error)
					elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
					LOGGER.info(
						"Helper synthesize request complete. chars=%s voice=%s lang=%s speed=%s volume=%s samples=%s elapsedMs=%s",
						len(text),
						voice,
						language,
						speed,
						volume,
						len(audio_bytes) // 2,
						elapsed_ms,
					)
					_send(
						{
							"ok": True,
							"id": request_id,
							"audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
						}
					)
					continue
				if op == "synthesize_stream":
					stream_start = time.perf_counter()
					text = request["text"]
					voice = request.get("voice") or engine.current_voice
					language = request.get("language", "en-us")
					speed = request.get("speed", 0.85)
					volume = request.get("volume", 1.0)
					max_tokens = request.get("max_tokens")
					target_tokens = request.get("target_tokens")
					first_chunk_tokens = request.get("first_chunk_tokens")
					chunk_count = 0
					for chunk_count, (chunk_text, audio) in enumerate(
						engine.stream_synthesize_to_int16(
							text,
							speed=speed,
							voice=voice,
							volume=volume,
							language=language,
							max_tokens=max_tokens,
							target_tokens=target_tokens,
							first_chunk_tokens=first_chunk_tokens,
						),
						start=1,
					):
						_send(
							{
								"ok": True,
								"id": request_id,
								"type": "audio_chunk",
								"chunk_index": chunk_count,
								"text": chunk_text,
								"audio_b64": base64.b64encode(audio.tobytes()).decode("ascii"),
							}
						)
					elapsed_ms = round((time.perf_counter() - stream_start) * 1000, 1)
					LOGGER.info(
						"Helper streamed synthesize complete. chars=%s voice=%s lang=%s speed=%s volume=%s chunkCount=%s elapsedMs=%s",
						len(text),
						voice,
						language,
						speed,
						volume,
						chunk_count,
						elapsed_ms,
					)
					_send({"ok": True, "id": request_id, "type": "done", "chunk_count": chunk_count})
					continue
				if op == "synthesize_preview":
					start_time = time.perf_counter()
					text = request["text"]
					voice_path = request["voice_path"]
					language = request.get("language", "en-us")
					speed = request.get("speed", 0.85)
					volume = request.get("volume", 1.0)
					audio = engine.synthesize_preview_to_int16(
						text,
						voice_path=voice_path,
						speed=speed,
						volume=volume,
						language=language,
					)
					elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
					LOGGER.info(
						"Helper synthesize_preview request complete. chars=%s voicePath=%s lang=%s speed=%s volume=%s samples=%s elapsedMs=%s",
						len(text),
						voice_path,
						language,
						speed,
						volume,
						len(audio),
						elapsed_ms,
					)
					_send(
						{
							"ok": True,
							"id": request_id,
							"audio_b64": base64.b64encode(audio.tobytes()).decode("ascii"),
						}
					)
					continue
				_send({"ok": False, "id": request_id, "error": "Unknown operation: %s" % op})
			except Exception as error:
				LOGGER.exception("Helper request failed.", exc_info=True)
				_send(
					{
						"ok": False,
						"id": request.get("id") if "request" in locals() else None,
						"error": str(error),
						"traceback": traceback.format_exc(),
					}
				)
		return 0
	finally:
		if speech_cache is not None:
			speech_cache.close()


if __name__ == "__main__":
	raise SystemExit(main())
