import json
import os
import re
import shutil
import tempfile
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone

try:
	from ._paths import get_temp_dir, get_user_voice_dir
except ImportError:
	from _paths import get_temp_dir, get_user_voice_dir


VOICE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SUPPORTED_VOICE_EXTENSIONS = (".bin", ".json", ".npy")
METADATA_SUFFIX = ".voice.json"
ARCHIVE_METADATA_FILES = {"metadata.json"}


class VoiceStoreError(RuntimeError):
	pass


class DuplicateVoiceError(VoiceStoreError):
	pass


@dataclass
class VoiceRecord(object):
	voice_id: str
	file_path: str
	source: str
	source_root: str
	metadata_path: str = None
	metadata: dict = None

	@property
	def display_name(self):
		if self.metadata and self.metadata.get("displayName"):
			return self.metadata["displayName"]
		return self.voice_id.replace("_", " ").title()

	@property
	def file_extension(self):
		return os.path.splitext(self.file_path)[1].lower()


def ensure_user_voice_dir():
	return get_user_voice_dir(create=True)


def get_user_voice_file_path(voice_id, extension):
	return os.path.join(get_user_voice_dir(create=True), voice_id + extension)


def get_user_metadata_path(voice_id):
	return os.path.join(get_user_voice_dir(create=True), voice_id + METADATA_SUFFIX)


def _normalize_voice_id(name):
	voice_id = os.path.splitext(os.path.basename(name))[0].strip()
	if not voice_id or not VOICE_NAME_RE.match(voice_id):
		raise VoiceStoreError("Unsupported voice name: %s" % name)
	return voice_id


def _metadata_path_for_file(file_path):
	base_name = os.path.splitext(os.path.basename(file_path))[0]
	return os.path.join(os.path.dirname(file_path), base_name + METADATA_SUFFIX)


def _load_metadata(metadata_path):
	if not metadata_path or not os.path.isfile(metadata_path):
		return None
	with open(metadata_path, "r", encoding="utf-8") as handle:
		return json.load(handle)


def _build_voice_record(file_path, source, source_root):
	voice_id = _normalize_voice_id(file_path)
	metadata_path = _metadata_path_for_file(file_path)
	return VoiceRecord(
		voice_id=voice_id,
		file_path=file_path,
		source=source,
		source_root=source_root,
		metadata_path=metadata_path if os.path.isfile(metadata_path) else None,
		metadata=_load_metadata(metadata_path),
	)


def discover_voice_records(package_root, fallback_roots):
	records = OrderedDict()
	scanned_roots = []
	root_entries = [("user", get_user_voice_dir(create=True))]
	for source_name, root in fallback_roots:
		root_entries.append((source_name, os.path.join(root, "voices")))
	for source_name, root in root_entries:
		if not root or not os.path.isdir(root):
			continue
		scanned_roots.append((source_name, root))
		for filename in sorted(os.listdir(root)):
			if filename.endswith(METADATA_SUFFIX):
				continue
			extension = os.path.splitext(filename)[1].lower()
			if extension not in SUPPORTED_VOICE_EXTENSIONS:
				continue
			file_path = os.path.join(root, filename)
			if not os.path.isfile(file_path):
				continue
			record = _build_voice_record(file_path, source_name, root)
			if record.voice_id not in records:
				records[record.voice_id] = record
	return records, scanned_roots


def list_user_voice_records():
	records, __ = discover_voice_records(None, [])
	return [record for record in records.values() if record.source == "user"]


def create_voice_metadata(voice_id, source_type, source_path, install_note=None, extra=None):
	metadata = {
		"voiceId": voice_id,
		"displayName": voice_id.replace("_", " ").title(),
		"sourceType": source_type,
		"sourcePath": source_path,
		"installedAt": datetime.now(timezone.utc).isoformat(),
	}
	if install_note:
		metadata["installNote"] = install_note
	if extra:
		metadata.update(extra)
	return metadata


def _write_metadata(metadata_path, metadata):
	with open(metadata_path, "w", encoding="utf-8") as handle:
		json.dump(metadata, handle, indent=2, sort_keys=True)


def _copy_file_atomic(source_path, target_path):
	target_dir = os.path.dirname(target_path)
	os.makedirs(target_dir, exist_ok=True)
	with tempfile.NamedTemporaryFile(delete=False, dir=get_temp_dir(create=True), suffix=os.path.splitext(target_path)[1]) as tmp_handle:
		tmp_path = tmp_handle.name
	shutil.copyfile(source_path, tmp_path)
	os.replace(tmp_path, target_path)


def _make_temp_path(suffix):
	fd, path = tempfile.mkstemp(dir=get_temp_dir(create=True), suffix=suffix)
	os.close(fd)
	return path


def _stage_temp_copy(source_path, extension):
	tmp_path = _make_temp_path(extension)
	shutil.copyfile(source_path, tmp_path)
	return tmp_path


def _is_safe_archive_member(base_dir, member_name):
	if not member_name:
		return False
	target_path = os.path.abspath(os.path.join(base_dir, member_name))
	base_dir = os.path.abspath(base_dir)
	return os.path.commonpath([base_dir, target_path]) == base_dir


def _is_archive_voice_payload(filename):
	if filename.endswith(METADATA_SUFFIX):
		return False
	if filename.lower() in ARCHIVE_METADATA_FILES:
		return False
	extension = os.path.splitext(filename)[1].lower()
	return extension in SUPPORTED_VOICE_EXTENSIONS


def _prepare_voice_sources(archive_path):
	collected = []
	with tempfile.TemporaryDirectory(dir=get_temp_dir(create=True)) as temp_dir:
		with zipfile.ZipFile(archive_path, "r") as archive:
			for member in archive.infolist():
				if not _is_safe_archive_member(temp_dir, member.filename):
					raise VoiceStoreError("Archive contains an unsafe path: %s" % member.filename)
				if member.is_dir():
					continue
				archive.extract(member, temp_dir)
		metadata_by_id = {}
		metadata_file = os.path.join(temp_dir, "metadata.json")
		if os.path.isfile(metadata_file):
			with open(metadata_file, "r", encoding="utf-8") as handle:
				metadata_payload = json.load(handle)
			metadata_by_id = metadata_payload.get("voices", {})
		for root, __, files in os.walk(temp_dir):
			for filename in sorted(files):
				if not _is_archive_voice_payload(filename):
					continue
				source_path = os.path.join(root, filename)
				extension = os.path.splitext(filename)[1].lower()
				voice_id = _normalize_voice_id(filename)
				collected.append(
					{
						"voice_id": voice_id,
						"source_path": source_path,
						"extension": extension,
						"metadata": metadata_by_id.get(voice_id, {}),
					}
				)
		if not collected:
			raise VoiceStoreError("Archive contains no supported voice files")
		results = []
		for item in collected:
			item["copied_path"] = _stage_temp_copy(item["source_path"], item["extension"])
			results.append(item)
		return results


def _coerce_install_items(source_path):
	extension = os.path.splitext(source_path)[1].lower()
	if extension in SUPPORTED_VOICE_EXTENSIONS:
		voice_id = _normalize_voice_id(source_path)
		return [
			{
				"voice_id": voice_id,
				"source_path": source_path,
				"extension": extension,
				"metadata": {},
			}
		]
	if extension == ".zip":
		return _prepare_voice_sources(source_path)
	raise VoiceStoreError("Unsupported voice file type: %s" % extension)


def install_voice_files(source_path, source_type, overwrite=False, install_note=None, extra_metadata=None):
	voice_dir = ensure_user_voice_dir()
	install_items = _coerce_install_items(source_path)
	results = []
	duplicate_policy = "overwrite" if overwrite else "reject"
	for item in install_items:
		voice_id = item["voice_id"]
		target_path = get_user_voice_file_path(voice_id, item["extension"])
		existing_paths = [
			os.path.join(voice_dir, voice_id + ext)
			for ext in SUPPORTED_VOICE_EXTENSIONS
			if os.path.isfile(os.path.join(voice_dir, voice_id + ext))
		]
		metadata_path = get_user_metadata_path(voice_id)
		if os.path.isfile(metadata_path):
			existing_paths.append(metadata_path)
		if existing_paths and not overwrite:
			raise DuplicateVoiceError("Voice already installed: %s" % voice_id)
		staged_file = _stage_temp_copy(item.get("copied_path", item["source_path"]), item["extension"])
		metadata = create_voice_metadata(
			voice_id,
			source_type=source_type,
			source_path=source_path,
			install_note=install_note,
			extra={"duplicatePolicy": duplicate_policy, **(extra_metadata or {}), **item.get("metadata", {})},
		)
		metadata["fileName"] = os.path.basename(target_path)
		metadata["storageLocation"] = "user"
		staged_metadata = _make_temp_path(".json")
		with open(staged_metadata, "w", encoding="utf-8") as handle:
			json.dump(metadata, handle, indent=2, sort_keys=True)
		backups = []
		try:
			for existing_path in existing_paths:
				if not os.path.isfile(existing_path):
					continue
				backup_path = _make_temp_path(".bak")
				os.replace(existing_path, backup_path)
				backups.append((existing_path, backup_path))
			os.replace(staged_file, target_path)
			os.replace(staged_metadata, metadata_path)
		except Exception:
			for restore_path in (target_path, metadata_path):
				if os.path.isfile(restore_path):
					os.remove(restore_path)
			for original_path, backup_path in backups:
				if os.path.isfile(backup_path):
					os.replace(backup_path, original_path)
			if os.path.isfile(staged_file):
				os.remove(staged_file)
			if os.path.isfile(staged_metadata):
				os.remove(staged_metadata)
			raise
		for __, backup_path in backups:
			if os.path.isfile(backup_path):
				os.remove(backup_path)
		results.append(
			VoiceRecord(
				voice_id=voice_id,
				file_path=target_path,
				source="user",
				source_root=voice_dir,
				metadata_path=metadata_path,
				metadata=metadata,
			)
		)
		if item.get("copied_path") and os.path.isfile(item["copied_path"]):
			os.remove(item["copied_path"])
	return results


def remove_user_voice(voice_id):
	voice_id = _normalize_voice_id(voice_id)
	removed = []
	for extension in SUPPORTED_VOICE_EXTENSIONS:
		target_path = get_user_voice_file_path(voice_id, extension)
		if os.path.isfile(target_path):
			os.remove(target_path)
			removed.append(target_path)
	metadata_path = get_user_metadata_path(voice_id)
	if os.path.isfile(metadata_path):
		os.remove(metadata_path)
		removed.append(metadata_path)
	if not removed:
		raise VoiceStoreError("User voice not found: %s" % voice_id)
	return removed
