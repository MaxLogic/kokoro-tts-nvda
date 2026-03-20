import base64
import json
import logging
import os
import sys
import time
import traceback

from _engine import KokoroEngine
from _hot_text_cache import HotTextCache
from _log import configure_helper_file_logger, get_helper_log_path
from _speech_cache import SpeechCache


logging.basicConfig(level=logging.INFO, format="[maxlogic-kokoro-helper] %(message)s")
LOGGER = logging.getLogger("maxlogic_kokoro_helper")
PACKAGE_ROOT = os.path.dirname(os.path.abspath(__file__))
HELPER_LOG_PATH = configure_helper_file_logger(LOGGER)
HELPER_MODE = os.environ.get("MAXLOGIC_KOKORO_HELPER_MODE", "synth").strip().lower() or "synth"


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


def _prewarm_voice(engine, voice_name):
	start_time = time.perf_counter()
	try:
		engine.synthesize_to_int16("Voice warm up.", speed=1.0, voice=voice_name, volume=0.0, language="en-us")
		LOGGER.info(
			"Helper voice prewarm complete. voice=%s elapsedMs=%s",
			voice_name,
			round((time.perf_counter() - start_time) * 1000, 1),
		)
	except Exception as error:
		LOGGER.warning("Helper voice prewarm failed for %s: %s", voice_name, error)


def main():
	LOGGER.info("Helper starting. pid=%s packageRoot=%s logPath=%s mode=%s", os.getpid(), PACKAGE_ROOT, HELPER_LOG_PATH, HELPER_MODE)
	speech_cache = None
	engine = None
	try:
		if HELPER_MODE != "cache":
			engine = KokoroEngine(PACKAGE_ROOT)
		try:
			speech_cache = SpeechCache(LOGGER)
		except Exception as cache_error:
			speech_cache = None
			LOGGER.warning("Helper speech cache disabled: %s", cache_error)
		hot_text_cache = HotTextCache()
		if engine is not None and os.environ.get("MAXLOGIC_KOKORO_SKIP_PREWARM") != "1":
			_prewarm_engine(engine)
		elif engine is not None:
			LOGGER.info("Helper startup prewarm skipped by request.")
		else:
			LOGGER.info("Helper engine startup skipped for cache-only mode.")
		LOGGER.info(
			"Helper ready. providers=%s currentVoice=%s voiceCount=%s sampleRate=%s cacheDb=%s hotCacheTtl=%s hotCacheMaxBytes=%s mode=%s",
			engine.session.get_providers() if engine is not None else [],
			engine.current_voice if engine is not None else None,
			len(engine.list_voices()) if engine is not None else 0,
			engine.sample_rate if engine is not None else 24000,
			speech_cache.db_path if speech_cache is not None else "disabled",
			hot_text_cache.ttl_seconds,
			hot_text_cache.max_bytes,
			HELPER_MODE,
		)
		_send(
			{
				"ok": True,
				"type": "ready",
				"voices": engine.list_voices() if engine is not None else [],
				"current_voice": engine.current_voice if engine is not None else None,
				"providers": engine.session.get_providers() if engine is not None else [],
				"sample_rate": engine.sample_rate if engine is not None else 24000,
				"mode": HELPER_MODE,
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
					if engine is None:
						raise RuntimeError("Voice operations are unavailable in cache-only helper mode")
					LOGGER.info("Helper set_voice request. voice=%s", request["voice"])
					engine.set_voice(request["voice"])
					_prewarm_voice(engine, engine.current_voice)
					_send({"ok": True, "id": request_id, "current_voice": engine.current_voice})
					continue
				if op == "reload_voices":
					if engine is None:
						raise RuntimeError("Voice operations are unavailable in cache-only helper mode")
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
				if op == "get_cache_stats":
					persistent_stats = None
					if speech_cache is not None:
						try:
							persistent_stats = speech_cache.get_stats()
						except Exception as cache_error:
							LOGGER.warning("Helper speech cache stats failed: %s", cache_error)
					_send(
						{
							"ok": True,
							"id": request_id,
							"persistent": persistent_stats,
							"hot": hot_text_cache.get_stats(),
						}
					)
					continue
				if op == "clear_cache":
					if speech_cache is not None:
						try:
							speech_cache.clear()
						except Exception as cache_error:
							LOGGER.warning("Helper speech cache clear failed: %s", cache_error)
					hot_text_cache.clear()
					persistent_stats = None
					if speech_cache is not None:
						try:
							persistent_stats = speech_cache.get_stats()
						except Exception as cache_error:
							LOGGER.warning("Helper speech cache stats after clear failed: %s", cache_error)
					_send(
						{
							"ok": True,
							"id": request_id,
							"persistent": persistent_stats,
							"hot": hot_text_cache.get_stats(),
						}
					)
					continue
				if op == "compact_cache":
					compacted = False
					if speech_cache is not None:
						try:
							speech_cache.compact()
							compacted = True
						except Exception as cache_error:
							LOGGER.warning("Helper speech cache compact failed: %s", cache_error)
					persistent_stats = None
					if speech_cache is not None:
						try:
							persistent_stats = speech_cache.get_stats()
						except Exception as cache_error:
							LOGGER.warning("Helper speech cache stats after compact failed: %s", cache_error)
					_send(
						{
							"ok": True,
							"id": request_id,
							"compacted": compacted,
							"persistent": persistent_stats,
							"hot": hot_text_cache.get_stats(),
						}
					)
					continue
				if op == "synthesize":
					if engine is None:
						raise RuntimeError("Synthesis is unavailable in cache-only helper mode")
					start_time = time.perf_counter()
					text = request["text"]
					voice = request.get("voice") or engine.current_voice
					language = request.get("language", "en-us")
					speed = request.get("speed", 0.85)
					volume = request.get("volume", 1.0)
					generation = request.get("generation")
					audio_bytes = None
					hot_cache_hit = False
					if speech_cache is not None:
						try:
							audio_bytes = speech_cache.get_audio(voice, speed, volume, language, text)
						except Exception as cache_error:
							LOGGER.warning("Helper speech cache read failed: %s", cache_error)
							audio_bytes = None
					if audio_bytes is None:
						audio_bytes = hot_text_cache.get_audio(voice, speed, volume, language, text)
						hot_cache_hit = audio_bytes is not None
					if audio_bytes is not None:
						if hot_cache_hit:
							LOGGER.info(
								"Helper hot cache hit. chars=%s voice=%s lang=%s speed=%s volume=%s bytes=%s generation=%s",
								len(text),
								voice,
								language,
								speed,
								volume,
								len(audio_bytes),
								generation,
							)
						else:
							LOGGER.info(
								"Helper cache hit. chars=%s voice=%s lang=%s speed=%s volume=%s bytes=%s generation=%s",
								len(text),
								voice,
								language,
								speed,
								volume,
								len(audio_bytes),
								generation,
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
						hot_text_cache.put_audio(voice, speed, volume, language, text, audio_bytes)
					elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
					LOGGER.info(
						"Helper synthesize request complete. chars=%s voice=%s lang=%s speed=%s volume=%s samples=%s elapsedMs=%s generation=%s",
						len(text),
						voice,
						language,
						speed,
						volume,
						len(audio_bytes) // 2,
						elapsed_ms,
						generation,
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
					if engine is None:
						raise RuntimeError("Streaming synthesis is unavailable in cache-only helper mode")
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
					if engine is None:
						raise RuntimeError("Preview synthesis is unavailable in cache-only helper mode")
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
				context_request = request if "request" in locals() and isinstance(request, dict) else {}
				LOGGER.exception(
					"Helper request failed. op=%s voice=%s voicePath=%s lang=%s chars=%s",
					context_request.get("op"),
					context_request.get("voice"),
					context_request.get("voice_path"),
					context_request.get("language"),
					len(context_request.get("text", "")),
					exc_info=True,
				)
				_send(
					{
						"ok": False,
						"id": context_request.get("id"),
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
