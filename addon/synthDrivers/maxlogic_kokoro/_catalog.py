import hashlib
import json
import logging
import os
import tempfile
import time
import urllib.parse
import urllib.request

try:
	from ._paths import (
		get_cache_dir,
		get_community_mirror_voice_dir,
		get_packaged_community_mirror_voice_dir,
		get_temp_dir,
	)
	from ._voice_store import install_voice_files
except ImportError:
	from _paths import (
		get_cache_dir,
		get_community_mirror_voice_dir,
		get_packaged_community_mirror_voice_dir,
		get_temp_dir,
	)
	from _voice_store import install_voice_files

try:
	from logHandler import log
except ImportError:
	log = logging.getLogger(__name__)


CATALOG_SCHEMA_VERSION = 2
CATALOG_CACHE_TTL_SECONDS = 24 * 60 * 60
CATALOGS = {
	"official": {
		"bundleFile": "catalog.json",
		"cacheFile": "official-voice-catalog.json",
		"onlineIndexUrl": "https://huggingface.co/api/models/onnx-community/Kokoro-82M-v1.0-ONNX/tree/main?recursive=true&expand=true",
		"downloadUrlTemplate": "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/voices/{sourceFile}?download=true",
		"onlinePrefix": "voices/",
	},
	"official_v11zh": {
		"bundleFile": "catalog_v11zh.json",
		"cacheFile": "official-v11zh-voice-catalog.json",
		"onlineIndexUrl": "https://huggingface.co/api/models/onnx-community/Kokoro-82M-v1.1-zh-ONNX/tree/main?recursive=true&expand=true",
		"downloadUrlTemplate": "https://huggingface.co/onnx-community/Kokoro-82M-v1.1-zh-ONNX/resolve/main/voices/{sourceFile}?download=true",
		"onlinePrefix": "voices/",
	},
	"community": {
		"bundleFile": "community_catalog.json",
		"cacheFile": "community-voice-catalog.json",
		"onlineIndexUrl": None,
		"downloadUrlTemplate": None,
		"onlinePrefix": "",
	},
}


def _require_catalog(catalog_name):
	try:
		return CATALOGS[catalog_name]
	except KeyError:
		raise RuntimeError("Unknown catalog: %s" % catalog_name)


def _catalog_bundle_path(catalog_name):
	definition = _require_catalog(catalog_name)
	return os.path.join(os.path.dirname(os.path.abspath(__file__)), definition["bundleFile"])


def _catalog_cache_path(catalog_name):
	definition = _require_catalog(catalog_name)
	return os.path.join(get_cache_dir(create=True), definition["cacheFile"])


def _load_json(path):
	with open(path, "r", encoding="utf-8") as handle:
		return json.load(handle)


def load_bundled_catalog(catalog_name):
	payload = _load_json(_catalog_bundle_path(catalog_name))
	payload["catalog"] = catalog_name
	payload["source"] = "bundled"
	payload["stale"] = False
	return payload


def load_cached_catalog(catalog_name):
	cache_path = _catalog_cache_path(catalog_name)
	if not os.path.isfile(cache_path):
		return None
	payload = _load_json(cache_path)
	if payload.get("schemaVersion") != CATALOG_SCHEMA_VERSION:
		return None
	fetched_at = payload.get("fetchedAtEpoch", 0)
	payload["catalog"] = catalog_name
	payload["stale"] = (time.time() - fetched_at) > CATALOG_CACHE_TTL_SECONDS
	payload["source"] = "cache"
	return payload


def _write_catalog_cache(catalog_name, payload):
	cache_path = _catalog_cache_path(catalog_name)
	temp_dir = get_temp_dir(create=True)
	with tempfile.NamedTemporaryFile(delete=False, dir=temp_dir, suffix=".json") as tmp_handle:
		tmp_path = tmp_handle.name
	with open(tmp_path, "w", encoding="utf-8") as handle:
		json.dump(payload, handle, indent=2, sort_keys=True)
	os.replace(tmp_path, cache_path)
	return cache_path


def _fetch_online_index(catalog_name):
	definition = _require_catalog(catalog_name)
	if not definition.get("onlineIndexUrl"):
		return None
	with urllib.request.urlopen(definition["onlineIndexUrl"], timeout=20) as response:
		return json.load(response)


def _resolve_mirror_path(download_url):
	if not download_url or not download_url.startswith("mirror://"):
		return None
	parsed = urllib.parse.urlparse(download_url)
	relative_path = (parsed.netloc + parsed.path).lstrip("/\\")
	if not relative_path:
		raise RuntimeError("Invalid mirror URL: %s" % download_url)
	file_name = os.path.basename(relative_path)
	user_path = os.path.join(get_community_mirror_voice_dir(create=True), file_name)
	if os.path.isfile(user_path):
		return user_path
	package_root = os.path.dirname(os.path.abspath(__file__))
	packaged_path = os.path.join(get_packaged_community_mirror_voice_dir(package_root), file_name)
	return packaged_path


def _merge_entry(entry, index_item, definition):
	merged = dict(entry)
	merged["catalog"] = entry.get("catalog", "official")
	download_template = definition.get("downloadUrlTemplate")
	if download_template:
		merged["downloadUrl"] = download_template.format(sourceFile=entry["sourceFile"])
	if index_item is None:
		merged["availableOnline"] = False
		return merged
	merged["availableOnline"] = True
	merged["remoteSizeBytes"] = index_item.get("size")
	merged["sizeBytes"] = index_item.get("size") or entry.get("sizeBytes")
	merged["remoteOid"] = index_item.get("oid")
	lfs = index_item.get("lfs") or {}
	if lfs.get("oid"):
		merged["sha256"] = lfs["oid"]
	elif index_item.get("oid"):
		merged["sha256"] = index_item["oid"]
	last_commit = index_item.get("lastCommit") or {}
	merged["lastUpdated"] = last_commit.get("date")
	return merged


def refresh_catalog(catalog_name="official"):
	definition = _require_catalog(catalog_name)
	bundled = load_bundled_catalog(catalog_name)
	if not definition.get("onlineIndexUrl"):
		bundled["source"] = "bundled"
		bundled["stale"] = False
		return bundled
	curated_entries = {entry["id"]: dict(entry) for entry in bundled["entries"]}
	online_index = _fetch_online_index(catalog_name)
	index_by_path = {}
	for item in online_index:
		path = item.get("path", "")
		if item.get("type") != "file":
			continue
		if not path.startswith(definition["onlinePrefix"]):
			continue
		index_by_path[path[len(definition["onlinePrefix"]):]] = item
	refreshed_entries = []
	for voice_id, entry in curated_entries.items():
		index_item = index_by_path.get(entry["sourceFile"])
		refreshed_entries.append(_merge_entry(entry, index_item, definition))
	payload = {
		"schemaVersion": CATALOG_SCHEMA_VERSION,
		"catalog": catalog_name,
		"fetchedAtEpoch": int(time.time()),
		"fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
		"indexUrl": definition["onlineIndexUrl"],
		"entries": sorted(refreshed_entries, key=lambda item: item["id"]),
	}
	cache_path = _write_catalog_cache(catalog_name, payload)
	log.info(
		"MaxLogic Kokoro %s catalog refreshed from network and cached at %s",
		catalog_name,
		cache_path,
	)
	payload["source"] = "network"
	payload["stale"] = False
	return payload


def _enrich_mirror_entries(entries):
	enriched = []
	for entry in entries:
		item = dict(entry)
		mirror_path = _resolve_mirror_path(item.get("downloadUrl"))
		if mirror_path:
			item["availableOnline"] = os.path.isfile(mirror_path)
			item["mirrorPath"] = mirror_path
			if os.path.isfile(mirror_path):
				item["remoteSizeBytes"] = os.path.getsize(mirror_path)
				item["sizeBytes"] = item.get("sizeBytes") or item["remoteSizeBytes"]
		enriched.append(item)
	return enriched


def resolve_catalog(catalog_name="official", force_refresh=False):
	definition = _require_catalog(catalog_name)
	cached = load_cached_catalog(catalog_name)
	if not force_refresh and cached is not None and not cached.get("stale"):
		if catalog_name == "community":
			cached["entries"] = _enrich_mirror_entries(cached["entries"])
		return cached
	if not definition.get("onlineIndexUrl"):
		bundled = load_bundled_catalog(catalog_name)
		bundled["stale"] = False
		if catalog_name == "community":
			bundled["entries"] = _enrich_mirror_entries(bundled["entries"])
		return bundled
	try:
		return refresh_catalog(catalog_name=catalog_name)
	except Exception as error:
		if cached is not None:
			log.warning(
				"MaxLogic Kokoro %s catalog refresh failed, using cached catalog: %s",
				catalog_name,
				error,
			)
			cached["source"] = "cache"
			if catalog_name == "community":
				cached["entries"] = _enrich_mirror_entries(cached["entries"])
			return cached
		bundled = load_bundled_catalog(catalog_name)
		bundled["stale"] = True
		bundled["fallbackReason"] = str(error)
		log.warning(
			"MaxLogic Kokoro %s catalog refresh failed, using bundled catalog: %s",
			catalog_name,
			error,
		)
		if catalog_name == "community":
			bundled["entries"] = _enrich_mirror_entries(bundled["entries"])
		return bundled


def get_catalog_entries(catalog_name="official", force_refresh=False):
	payload = resolve_catalog(catalog_name=catalog_name, force_refresh=force_refresh)
	entries = []
	for entry in payload["entries"]:
		merged = dict(entry)
		merged["catalog"] = catalog_name
		entries.append(merged)
	return entries, payload


def _download_to_temp(url, target_name):
	hasher = hashlib.sha256()
	temp_dir = get_temp_dir(create=True)
	staging_dir = tempfile.mkdtemp(dir=temp_dir)
	temp_path = os.path.join(staging_dir, os.path.basename(target_name))
	try:
		mirror_path = _resolve_mirror_path(url)
		if mirror_path:
			if not os.path.isfile(mirror_path):
				raise RuntimeError("Mirror voice file not found: %s" % mirror_path)
			with open(mirror_path, "rb") as source, open(temp_path, "wb") as target:
				while True:
					chunk = source.read(65536)
					if not chunk:
						break
					target.write(chunk)
					hasher.update(chunk)
			return temp_path, hasher.hexdigest()
		with urllib.request.urlopen(url, timeout=60) as response, open(temp_path, "wb") as target:
			while True:
				chunk = response.read(65536)
				if not chunk:
					break
				target.write(chunk)
				hasher.update(chunk)
	except Exception:
		if os.path.isfile(temp_path):
			os.remove(temp_path)
		if os.path.isdir(staging_dir):
			os.rmdir(staging_dir)
		raise
	return temp_path, hasher.hexdigest()


def download_catalog_voice_to_temp(entry, force_bad_sha=False):
	url = entry["downloadUrl"]
	log.info("MaxLogic Kokoro downloading preview voice to temp. id=%s url=%s", entry["id"], url)
	temp_path, digest = _download_to_temp(url, entry["sourceFile"])
	expected_sha = entry["sha256"]
	if force_bad_sha:
		expected_sha = "0" * 64
	if digest.lower() != expected_sha.lower():
		if os.path.isfile(temp_path):
			os.remove(temp_path)
		staging_dir = os.path.dirname(temp_path)
		if os.path.isdir(staging_dir):
			os.rmdir(staging_dir)
		raise RuntimeError("SHA-256 mismatch for %s" % entry["id"])
	return {
		"path": temp_path,
		"sha256": digest,
		"cleanupDir": os.path.dirname(temp_path),
	}


def download_catalog_voice(entry, overwrite=False, force_bad_sha=False):
	url = entry["downloadUrl"]
	log.info("MaxLogic Kokoro downloading catalog voice. id=%s url=%s", entry["id"], url)
	temp_path, digest = _download_to_temp(url, entry["sourceFile"])
	expected_sha = entry["sha256"]
	if force_bad_sha:
		expected_sha = "0" * 64
	try:
		if digest.lower() != expected_sha.lower():
			raise RuntimeError("SHA-256 mismatch for %s" % entry["id"])
		records = install_voice_files(
			temp_path,
			source_type="catalog-download",
			overwrite=overwrite,
			install_note="Installed from curated catalog",
			extra_metadata={
				"displayName": entry.get("displayName", entry["id"]),
				"catalogId": entry["id"],
				"catalogName": entry.get("catalog", "official"),
				"sourceModel": entry.get("source"),
				"modelFamily": entry.get("modelFamily"),
				"modelVersion": entry.get("modelVersion"),
				"modelId": entry.get("modelId"),
				"language": entry.get("language"),
				"languageLabel": entry.get("languageLabel"),
				"gender": entry.get("gender"),
				"genderLabel": entry.get("genderLabel"),
				"downloadUrl": url,
				"sha256": digest,
			},
		)
		log.info(
			"MaxLogic Kokoro catalog download installed. id=%s sha256=%s finalPath=%s",
			entry["id"],
			digest,
			records[0].file_path if records else None,
		)
		return records
	finally:
		if os.path.isfile(temp_path):
			os.remove(temp_path)
		staging_dir = os.path.dirname(temp_path)
		if os.path.isdir(staging_dir):
			os.rmdir(staging_dir)
