import base64
import json
import logging
import os
import sys
import time
import traceback

from _engine import KokoroEngine
from _log import configure_helper_file_logger, get_helper_log_path


logging.basicConfig(level=logging.INFO, format="[maxlogic-kokoro-helper] %(message)s")
LOGGER = logging.getLogger("maxlogic_kokoro_helper")
PACKAGE_ROOT = os.path.dirname(os.path.abspath(__file__))
HELPER_LOG_PATH = configure_helper_file_logger(LOGGER)


def _send(payload):
	sys.stdout.write(json.dumps(payload) + "\n")
	sys.stdout.flush()


def main():
	LOGGER.info("Helper starting. pid=%s packageRoot=%s logPath=%s", os.getpid(), PACKAGE_ROOT, HELPER_LOG_PATH)
	try:
		engine = KokoroEngine(PACKAGE_ROOT)
		LOGGER.info(
			"Helper ready. providers=%s currentVoice=%s voiceCount=%s sampleRate=%s",
			engine.session.get_providers(),
			engine.current_voice,
			len(engine.list_voices()),
			engine.sample_rate,
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
			if op == "synthesize":
				start_time = time.perf_counter()
				text = request["text"]
				voice = request.get("voice") or engine.current_voice
				language = request.get("language", "en-us")
				speed = request.get("speed", 0.85)
				volume = request.get("volume", 1.0)
				audio = engine.synthesize_to_int16(
					text,
					speed=speed,
					voice=voice,
					volume=volume,
					language=language,
				)
				elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
				LOGGER.info(
					"Helper synthesize request complete. chars=%s voice=%s lang=%s speed=%s volume=%s samples=%s elapsedMs=%s",
					len(text),
					voice,
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


if __name__ == "__main__":
	raise SystemExit(main())
