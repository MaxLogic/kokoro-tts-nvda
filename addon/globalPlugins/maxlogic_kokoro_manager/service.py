# coding: utf-8

import json
import os
import sys
import threading

import addonHandler
import config
import nvwave
import synthDriverHandler
from logHandler import log
import wx


addonHandler.initTranslation()

_GLOBAL_PLUGIN_ROOT = os.path.abspath(os.path.dirname(__file__))
_SYNTH_ROOT = os.path.abspath(os.path.join(_GLOBAL_PLUGIN_ROOT, "..", "..", "synthDrivers", "maxlogic_kokoro"))
_REFERENCE_ROOT = os.path.join(
	os.environ.get("APPDATA", ""),
	"nvda",
	"addons",
	"kokoroTTS",
	"synthDrivers",
	"kokoro",
)
for deps_root in (
	os.path.join(_SYNTH_ROOT, "deps"),
	os.path.join(_REFERENCE_ROOT, "deps"),
):
	if os.path.isdir(deps_root) and deps_root not in sys.path:
		sys.path.insert(0, deps_root)

from synthDrivers.maxlogic_kokoro._catalog import (
	download_catalog_voice,
	download_catalog_voice_to_temp,
	get_catalog_entries,
)
from synthDrivers.maxlogic_kokoro._cache_settings import (
	CACHE_MODE_CUSTOM,
	CACHE_MODE_SHORT_MEDIUM,
	CACHE_MODE_SHORT_UI,
	load_cache_settings,
	resolve_cache_policy,
	save_cache_settings,
)
from synthDrivers.maxlogic_kokoro._engine import DEFAULT_REFERENCE_ROOT, KokoroEngine
from synthDrivers.maxlogic_kokoro._helper_client import HelperEngineClient
from synthDrivers.maxlogic_kokoro._voice_store import (
	DuplicateVoiceError,
	VoiceStoreError,
	discover_voice_records,
	install_voice_files,
	list_user_voice_records,
	remove_user_voice,
)


_preview_lock = threading.Lock()
_preview_generation = 0
_preview_player = None
_preview_player_rate = None
_sample_text_cache = None


CACHE_MODE_OPTIONS = [
	(CACHE_MODE_SHORT_UI, _("Short UI speech only (Recommended)")),
	(CACHE_MODE_SHORT_MEDIUM, _("Short and medium speech")),
	(CACHE_MODE_CUSTOM, _("Custom")),
]


def list_installed_user_voices():
	return list_user_voice_records()


def _package_root():
	return _SYNTH_ROOT


def _sample_text_path():
	return os.path.join(os.path.dirname(__file__), "sample_texts.json")


def _load_sample_texts():
	global _sample_text_cache
	if _sample_text_cache is None:
		with open(_sample_text_path(), "r", encoding="utf-8") as handle:
			_sample_text_cache = json.load(handle)
	return _sample_text_cache


def get_sample_text(language):
	payload = _load_sample_texts()
	key = (language or "").strip().lower()
	if key and key in payload:
		return payload[key]
	if "-" in key:
		base_key = key.split("-", 1)[0]
		if base_key in payload:
			return payload[base_key]
	return payload["default"]


def _begin_preview():
	global _preview_generation
	with _preview_lock:
		_preview_generation += 1
		generation = _preview_generation
		if _preview_player is not None:
			_preview_player.stop()
		return generation


def _get_preview_player(sample_rate):
	global _preview_player
	global _preview_player_rate
	if _preview_player is not None and _preview_player_rate != sample_rate:
		_preview_player.close()
		_preview_player = None
		_preview_player_rate = None
	if _preview_player is None:
		output_device = None
		try:
			output_device = config.conf["audio"]["outputDevice"]
		except Exception:
			pass
		_preview_player = nvwave.WavePlayer(
			channels=1,
			samplesPerSec=sample_rate,
			bitsPerSample=16,
			outputDevice=output_device,
		)
		_preview_player_rate = sample_rate
	return _preview_player


def _play_preview_audio(audio_bytes, sample_rate, generation):
	with _preview_lock:
		if generation != _preview_generation:
			return False
		player = _get_preview_player(sample_rate)
		player.stop()
	player.feed(audio_bytes)
	player.idle()
	return True


def stop_preview():
	with _preview_lock:
		if _preview_player is not None:
			_preview_player.stop()


def close_preview_player():
	global _preview_player
	global _preview_player_rate
	with _preview_lock:
		if _preview_player is not None:
			_preview_player.close()
			_preview_player = None
			_preview_player_rate = None


def list_voice_inventory():
	package_root = _package_root()
	override_root = os.environ.get("MAXLOGIC_KOKORO_ASSET_ROOT")
	fallback_roots = [("package", package_root)]
	if override_root:
		fallback_roots.append(("override", override_root))
	fallback_roots.append(("reference", DEFAULT_REFERENCE_ROOT))
	records, __ = discover_voice_records(package_root, fallback_roots)
	user_records = []
	builtin_records = []
	for record in records.values():
		if record.source == "user":
			user_records.append(record)
		else:
			builtin_records.append(record)
	user_records.sort(key=lambda record: record.display_name.lower())
	builtin_records.sort(key=lambda record: record.display_name.lower())
	return {
		"user": user_records,
		"builtin": builtin_records,
	}


def _get_active_maxlogic_synth():
	try:
		synth = synthDriverHandler.getSynth()
	except Exception:
		return None
	if synth is None or getattr(synth, "name", None) != "maxlogic_kokoro":
		return None
	return synth


def _get_cache_helper_client():
	helper = HelperEngineClient(_package_root(), log, helper_mode="cache", skip_prewarm=True)
	return helper, True


def _close_cache_helper_client(helper, should_close):
	if should_close and helper is not None:
		helper.close()


def _build_cache_stats_payload(helper_response=None, error_message=None):
	settings = get_speech_cache_settings()
	if helper_response is None:
		return {
			"dbPath": "",
			"entryCount": 0,
			"sizeBytes": 0,
			"sizeMb": 0.0,
			"lastUsed": None,
			"settings": settings,
			"available": False,
			"error": error_message or "Speech cache support is unavailable.",
			"hotEntryCount": 0,
			"hotSizeBytes": 0,
			"hotSizeMb": 0.0,
			"hotTtlSeconds": 0,
		}
	persistent = helper_response.get("persistent") or {}
	hot = helper_response.get("hot") or {}
	size_bytes = int(persistent.get("sizeBytes") or 0)
	hot_size_bytes = int(hot.get("sizeBytes") or 0)
	available = bool(persistent)
	payload = {
		"dbPath": persistent.get("dbPath", ""),
		"entryCount": int(persistent.get("entryCount") or 0),
		"sizeBytes": size_bytes,
		"sizeMb": round(size_bytes / float(1024 * 1024), 2),
		"lastUsed": persistent.get("lastUsed"),
		"settings": settings,
		"available": available,
		"error": None if available else _("Persistent speech cache is unavailable."),
		"hotEntryCount": int(hot.get("entryCount") or 0),
		"hotSizeBytes": hot_size_bytes,
		"hotSizeMb": round(hot_size_bytes / float(1024 * 1024), 2),
		"hotTtlSeconds": int(hot.get("ttlSeconds") or 0),
	}
	if "sizeMb" in persistent:
		payload["sizeMb"] = persistent["sizeMb"]
	return payload


def refresh_active_synth(reason, preferred_voice=None):
	synth = _get_active_maxlogic_synth()
	if synth is None:
		return {
			"refreshed": False,
			"restartRequired": False,
			"runtimeStatus": None,
		}
	if hasattr(synth, "reloadVoiceStore"):
		synth.reloadVoiceStore(reason=reason, preferred_voice=preferred_voice)
		status = synth.getRuntimeStatus() if hasattr(synth, "getRuntimeStatus") else None
		log.info("MaxLogic Kokoro service refreshed active synth. reason=%s status=%s", reason, status)
		return {
			"refreshed": True,
			"restartRequired": False,
			"runtimeStatus": status,
		}
	log.warning("MaxLogic Kokoro service cannot refresh active synth in-place. reason=%s", reason)
	return {
		"refreshed": False,
		"restartRequired": True,
		"runtimeStatus": None,
	}


def install_local_voice(source_path, overwrite=False):
	log.info(
		"MaxLogic Kokoro installing local voice. source=%s duplicatePolicy=%s",
		source_path,
		"overwrite" if overwrite else "reject",
	)
	records = install_voice_files(
		source_path,
		source_type="local-file",
		overwrite=overwrite,
		install_note="Installed from local file",
	)
	refresh_result = refresh_active_synth(
		reason="local-install",
		preferred_voice=records[0].voice_id if len(records) == 1 else None,
	)
	return {
		"records": records,
		"refresh": refresh_result,
	}


def remove_local_voice(voice_id):
	log.info("MaxLogic Kokoro removing local voice. voice=%s", voice_id)
	removed_paths = remove_user_voice(voice_id)
	refresh_result = refresh_active_synth(reason="local-remove")
	return {
		"removedPaths": removed_paths,
		"refresh": refresh_result,
	}


def list_catalog_voices(catalog_name="official", force_refresh=False):
	return get_catalog_entries(catalog_name=catalog_name, force_refresh=force_refresh)


def install_catalog_voice(entry, overwrite=False, force_bad_sha=False, refresh=True):
	log.info(
		"MaxLogic Kokoro installing catalog voice. catalog=%s id=%s duplicatePolicy=%s refresh=%s",
		entry.get("catalog", "official"),
		entry["id"],
		"overwrite" if overwrite else "reject",
		refresh,
	)
	records = download_catalog_voice(entry, overwrite=overwrite, force_bad_sha=force_bad_sha)
	refresh_result = {
		"refreshed": False,
		"restartRequired": False,
		"runtimeStatus": None,
	}
	if refresh:
		refresh_result = refresh_active_synth(
			reason="catalog-install",
			preferred_voice=records[0].voice_id if len(records) == 1 else None,
		)
	return {
		"records": records,
		"refresh": refresh_result,
	}


def play_catalog_voice_sample(entry, on_complete=None):
	generation = _begin_preview()

	def _finish(error_message=None):
		if on_complete is not None:
			wx.CallAfter(on_complete, error_message)

	def _worker():
		temp_payload = None
		helper = None
		try:
			if not entry.get("availableOnline", True):
				raise RuntimeError("This voice is not available from the online catalog source.")
			temp_payload = download_catalog_voice_to_temp(entry)
			language = entry.get("language") or "en-us"
			sample_text = get_sample_text(language)
			sample_rate = 24000
			try:
				helper = HelperEngineClient(_package_root(), log)
			except Exception as helper_error:
				log.warning("MaxLogic Kokoro preview helper unavailable, using in-process preview: %s", helper_error)
				engine = KokoroEngine(_package_root())
				try:
					audio = engine.synthesize_preview_to_int16(
						sample_text,
						voice_path=temp_payload["path"],
						language=language,
					)
				finally:
					if hasattr(engine, "phonemizer") and hasattr(engine.phonemizer, "close"):
						engine.phonemizer.close()
				audio_bytes = audio.tobytes()
			else:
				audio_bytes = helper.synthesize_preview_to_int16(
					sample_text,
					voice_path=temp_payload["path"],
					language=language,
				).tobytes()
				sample_rate = helper.sample_rate
			played = _play_preview_audio(audio_bytes, sample_rate, generation)
			if played:
				log.info(
					"MaxLogic Kokoro preview played. catalog=%s id=%s language=%s tempPath=%s providers=%s",
					entry.get("catalog", "official"),
					entry["id"],
					language,
					temp_payload["path"],
					helper.get_status().get("providers") if helper is not None else ["CPUExecutionProvider"],
				)
			_finish(None if played else "Preview was superseded by a newer request.")
		except Exception as error:
			log.exception(
				"MaxLogic Kokoro preview failed. catalog=%s id=%s",
				entry.get("catalog", "official"),
				entry.get("id"),
				exc_info=True,
			)
			_finish(str(error))
		finally:
			if helper is not None:
				helper.close()
			if temp_payload is not None:
				if os.path.isfile(temp_payload["path"]):
					os.remove(temp_payload["path"])
				cleanup_dir = temp_payload.get("cleanupDir")
				if cleanup_dir and os.path.isdir(cleanup_dir):
					os.rmdir(cleanup_dir)

	thread = threading.Thread(
		target=_worker,
		name="MaxLogicKokoroPreview",
		daemon=True,
	)
	thread.start()


def get_runtime_status():
	synth = _get_active_maxlogic_synth()
	if synth is None:
		return {
			"mode": "inactive",
			"providers": [],
			"voiceCount": 0,
			"currentVoice": None,
		}
	if hasattr(synth, "getRuntimeStatus"):
		return synth.getRuntimeStatus()
	return {
		"mode": getattr(synth, "name", "unknown"),
		"providers": [],
		"voiceCount": len(getattr(synth, "availableVoices", {}) or {}),
		"currentVoice": getattr(synth, "voice", None),
	}


def get_speech_cache_settings():
	settings = load_cache_settings()
	return resolve_cache_policy(settings)


def get_speech_cache_stats():
	try:
		helper, should_close = _get_cache_helper_client()
	except Exception as error:
		log.warning("MaxLogic Kokoro helper cache stats unavailable: %s", error)
		return _build_cache_stats_payload(error_message=str(error))
	try:
		try:
			response = helper.get_cache_stats()
		except Exception as error:
			log.warning("MaxLogic Kokoro helper cache stats query failed: %s", error)
			return _build_cache_stats_payload(error_message=str(error))
		return _build_cache_stats_payload(response)
	finally:
		_close_cache_helper_client(helper, should_close)


def save_speech_cache_settings(settings):
	normalized = save_cache_settings(settings)
	policy = resolve_cache_policy(normalized)
	log.info("MaxLogic Kokoro speech cache settings saved. policy=%s", policy)
	return {
		"settings": policy,
		"stats": get_speech_cache_stats(),
	}


def clear_speech_cache():
	try:
		helper, should_close = _get_cache_helper_client()
	except Exception as error:
		log.warning("MaxLogic Kokoro helper cache clear unavailable: %s", error)
		return _build_cache_stats_payload(error_message=str(error))
	try:
		response = helper.clear_cache()
	finally:
		_close_cache_helper_client(helper, should_close)
	log.info("MaxLogic Kokoro speech cache cleared.")
	return _build_cache_stats_payload(response)


def compact_speech_cache():
	if _get_active_maxlogic_synth() is not None:
		return {
			"compacted": False,
			"restartRequired": True,
			"stats": get_speech_cache_stats(),
		}
	try:
		helper, should_close = _get_cache_helper_client()
	except Exception as error:
		log.warning("MaxLogic Kokoro helper cache compact unavailable: %s", error)
		return {
			"compacted": False,
			"restartRequired": False,
			"stats": _build_cache_stats_payload(error_message=str(error)),
		}
	try:
		response = helper.compact_cache()
	finally:
		_close_cache_helper_client(helper, should_close)
	log.info("MaxLogic Kokoro speech cache compacted.")
	return {
		"compacted": bool(response.get("compacted", True)),
		"restartRequired": False,
		"stats": _build_cache_stats_payload(response),
	}


__all__ = [
	"CACHE_MODE_OPTIONS",
	"DuplicateVoiceError",
	"VoiceStoreError",
	"clear_speech_cache",
	"compact_speech_cache",
	"get_speech_cache_settings",
	"get_speech_cache_stats",
	"install_local_voice",
	"install_catalog_voice",
	"list_catalog_voices",
	"list_installed_user_voices",
	"play_catalog_voice_sample",
	"get_runtime_status",
	"refresh_active_synth",
	"remove_local_voice",
	"save_speech_cache_settings",
	"stop_preview",
]
