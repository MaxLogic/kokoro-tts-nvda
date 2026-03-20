# coding: utf-8

import os
import shutil
import logging

try:
	from logHandler import log
except ImportError:
	log = logging.getLogger(__name__)


ADDON_ID = "maxlogicKokoroTTS"


def _addon_root():
	return os.path.abspath(os.path.dirname(__file__))


def _user_data_root():
	return os.path.join(os.environ.get("APPDATA", ""), "nvda", ADDON_ID)


def _copy_tree_if_missing(source_root, target_root):
	if not os.path.isdir(source_root):
		return 0
	os.makedirs(target_root, exist_ok=True)
	copied = 0
	for current_root, __, files in os.walk(source_root):
		relative_root = os.path.relpath(current_root, source_root)
		destination_root = target_root if relative_root == "." else os.path.join(target_root, relative_root)
		os.makedirs(destination_root, exist_ok=True)
		for filename in files:
			source_path = os.path.join(current_root, filename)
			target_path = os.path.join(destination_root, filename)
			if os.path.exists(target_path):
				continue
			shutil.copy2(source_path, target_path)
			copied += 1
	return copied


def onInstall():
	log.info("Installing MaxLogic Kokoro TTS")
	addon_root = _addon_root()
	packaged_mirror = os.path.join(addon_root, "synthDrivers", "maxlogic_kokoro", "community_mirror")
	user_mirror = os.path.join(_user_data_root(), "community-mirror")
	copied = _copy_tree_if_missing(packaged_mirror, user_mirror)
	log.info(
		"MaxLogic Kokoro community mirror seed complete. source=%s target=%s copiedFiles=%s",
		packaged_mirror,
		user_mirror,
		copied,
	)
