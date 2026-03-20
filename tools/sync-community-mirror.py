import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import torch


REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_ROOT = REPO_ROOT / "addon" / "synthDrivers" / "maxlogic_kokoro"
if str(ADDON_ROOT) not in sys.path:
	sys.path.insert(0, str(ADDON_ROOT))

from _paths import get_community_mirror_dir, get_community_mirror_voice_dir  # noqa: E402


def _load_sources():
	path = ADDON_ROOT / "community_sources.json"
	with path.open("r", encoding="utf-8") as handle:
		return json.load(handle)


def _download_bytes(url):
	with urllib.request.urlopen(url, timeout=60) as response:
		return response.read()


def _hf_resolve_url(repo_id, upstream_path):
	quoted_path = urllib.parse.quote(upstream_path, safe="/")
	return "https://huggingface.co/{repo}/resolve/main/{path}?download=true".format(
		repo=repo_id,
		path=quoted_path,
	)


def _tensor_to_matrix(tensor, voice_id):
	if not isinstance(tensor, torch.Tensor):
		raise RuntimeError("Unsupported payload type for %s: %r" % (voice_id, type(tensor)))
	working = tensor.detach().cpu().to(dtype=torch.float32)
	if working.ndim == 3 and tuple(working.shape[1:]) == (1, 256):
		working = working.squeeze(1)
	if working.ndim != 2 or working.shape[1] != 256:
		raise RuntimeError("Unsupported tensor shape for %s: %r" % (voice_id, tuple(working.shape)))
	return working.numpy()


def _sha256_of_file(path):
	hasher = hashlib.sha256()
	with open(path, "rb") as handle:
		while True:
			chunk = handle.read(65536)
			if not chunk:
				break
			hasher.update(chunk)
	return hasher.hexdigest()


def _write_json(path, payload):
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8") as handle:
		json.dump(payload, handle, indent=2, sort_keys=True)
		handle.write("\n")


def sync_community_mirror(clean=False):
	config = _load_sources()
	mirror_root = Path(get_community_mirror_dir(create=True))
	mirror_voice_root = Path(get_community_mirror_voice_dir(create=True))
	packaged_root = ADDON_ROOT / "community_mirror"
	packaged_voice_root = packaged_root / "voices"
	if clean and mirror_voice_root.exists():
		shutil.rmtree(mirror_voice_root)
		mirror_voice_root.mkdir(parents=True, exist_ok=True)
	if clean and packaged_voice_root.exists():
		shutil.rmtree(packaged_voice_root)
	packaged_voice_root.mkdir(parents=True, exist_ok=True)

	catalog_entries = []
	mirror_manifest = {
		"schemaVersion": 1,
		"generatedAt": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
		"voices": [],
	}
	seen_hashes = {}

	for source in config["sources"]:
		repo_id = source["id"]
		for entry in source["entries"]:
			voice_id = entry["id"]
			upstream_path = entry["upstreamPath"]
			download_url = _hf_resolve_url(repo_id, upstream_path)
			print("Syncing", repo_id, upstream_path, "->", voice_id)
			payload = _download_bytes(download_url)
			tensor = torch.load(io.BytesIO(payload), map_location="cpu")
			matrix = _tensor_to_matrix(tensor, voice_id)
			target_name = voice_id + ".bin"
			target_path = mirror_voice_root / target_name
			packaged_target_path = packaged_voice_root / target_name
			with tempfile.NamedTemporaryFile(delete=False, dir=str(mirror_voice_root), suffix=".bin") as tmp_handle:
				tmp_path = Path(tmp_handle.name)
			try:
				matrix.astype(np.float32, copy=False).tofile(str(tmp_path))
				os.replace(str(tmp_path), str(target_path))
			finally:
				if tmp_path.exists():
					tmp_path.unlink()
			sha256 = _sha256_of_file(target_path)
			size_bytes = target_path.stat().st_size
			if sha256 in seen_hashes:
				print(
					"Skipping duplicate voice",
					voice_id,
					"because it matches",
					seen_hashes[sha256],
				)
				target_path.unlink(missing_ok=True)
				continue
			seen_hashes[sha256] = voice_id
			shutil.copyfile(target_path, packaged_target_path)
			catalog_entries.append(
				{
					"id": voice_id,
					"displayName": entry["displayName"],
					"language": entry["language"],
					"languageLabel": entry["languageLabel"],
					"gender": entry["gender"],
					"genderLabel": entry["genderLabel"],
					"sha256": sha256,
					"sizeBytes": size_bytes,
					"source": "community-mirror:{repo}".format(repo=repo_id),
					"sourceRepo": repo_id,
					"sourceFile": target_name,
					"upstreamPath": upstream_path,
					"upstreamUrl": download_url,
					"downloadUrl": "mirror://voices/{name}".format(name=target_name),
					"experimental": True,
				}
			)
			mirror_manifest["voices"].append(
				{
					"id": voice_id,
					"repo": repo_id,
					"upstreamPath": upstream_path,
					"mirrorPath": str(target_path),
					"sha256": sha256,
					"sizeBytes": size_bytes,
				}
			)

	catalog_entries.sort(key=lambda item: item["displayName"].lower())
	_write_json(ADDON_ROOT / "community_catalog.json", {"schemaVersion": 2, "entries": catalog_entries})
	_write_json(mirror_root / "index.json", mirror_manifest)
	_write_json(packaged_root / "index.json", mirror_manifest)
	print("Community catalog entries:", len(catalog_entries))
	print("Mirror root:", mirror_root)
	print("Catalog file:", ADDON_ROOT / "community_catalog.json")


def main():
	parser = argparse.ArgumentParser(description="Sync curated community Kokoro voices into a local .bin mirror.")
	parser.add_argument("--clean", action="store_true", help="Delete existing mirrored voice files before syncing.")
	args = parser.parse_args()
	sync_community_mirror(clean=args.clean)


if __name__ == "__main__":
	raise SystemExit(main())
