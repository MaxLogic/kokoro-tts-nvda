import logging
import os


ADDON_ID = "maxlogicKokoroTTS"


def get_log_dir():
	base_dir = os.path.join(os.environ.get("APPDATA", ""), "nvda", ADDON_ID, "logs")
	os.makedirs(base_dir, exist_ok=True)
	return base_dir


def get_helper_log_path():
	return os.path.join(get_log_dir(), "helper.log")


def configure_helper_file_logger(logger):
	log_path = get_helper_log_path()
	formatter = logging.Formatter(
		"%(asctime)s [%(levelname)s] %(process)d %(name)s: %(message)s"
	)
	already_present = False
	for handler in logger.handlers:
		if isinstance(handler, logging.FileHandler) and os.path.abspath(handler.baseFilename) == os.path.abspath(log_path):
			already_present = True
			break
	if not already_present:
		file_handler = logging.FileHandler(log_path, encoding="utf-8")
		file_handler.setFormatter(formatter)
		logger.addHandler(file_handler)
	return log_path
