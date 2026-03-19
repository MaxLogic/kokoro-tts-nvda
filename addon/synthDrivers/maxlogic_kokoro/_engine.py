import json
import logging
import os
import re

import numpy as np
import onnxruntime as ort

try:
	from logHandler import log
except ImportError:
	log = logging.getLogger(__name__)

try:
	from ._phonemizer import EspeakPhonemizer, DEFAULT_REFERENCE_ROOT
except ImportError:
	from _phonemizer import EspeakPhonemizer, DEFAULT_REFERENCE_ROOT


TOKEN_REPLACEMENTS = {
	"g": "\u0261",
	"\u02de": "\u0279",
	"\u02cc": "",
	"\u02c8": "",
	"\u02d0": ":",
	"\u025a": "\u0259",
	"\u025d": "\u025c",
	"\u027e": "t",
	"\u026b": "l",
	"\u026a\u0308": "\u026a",
	"\u0275": "o",
	"\u0250": "a",
	"\u0258": "\u0259",
	"\u025c": "e",
	"\u025e": "e",
	"\u0289": "u",
	"\u028a": "u",
	"\u028c": "a",
	"\u028d": "w",
	"\u028f": "y",
	"\u0292": "z",
	"\u0294": "",
	"\u03b8": "th",
	"\u00f0": "th",
	"\u014b": "n",
	"\u0261": "g",
	"\u0279": "r",
	"\u0283": "sh",
	"\u02a7": "ch",
	"\u02a4": "j",
}

WHITESPACE_RE = re.compile(r"\s+")


def _candidate_asset_roots(package_root):
	override_root = os.environ.get("MAXLOGIC_KOKORO_ASSET_ROOT")
	roots = [package_root]
	if override_root:
		roots.append(override_root)
	roots.append(DEFAULT_REFERENCE_ROOT)
	return roots


def _resolve_existing_path(package_root, relative_path, expect_dir=False):
	for root in _candidate_asset_roots(package_root):
		candidate = os.path.join(root, relative_path)
		if expect_dir and os.path.isdir(candidate):
			return candidate
		if not expect_dir and os.path.isfile(candidate):
			return candidate
	return None


class KokoroEngine(object):
	sample_rate = 24000

	def __init__(self, package_root):
		self.package_root = package_root
		self.model_path = self._require_file(os.path.join("model", "kokoro.onnx"))
		self.voice_dir = self._require_voice_dir()
		self.config_path = self._require_file("config.json")
		self.tokenizer_path = self._require_file("tokenizer.json")
		self._asset_root = os.path.dirname(self.config_path)
		self.phonemizer = EspeakPhonemizer(package_root)

		with open(self.config_path, "r", encoding="utf-8") as handle:
			self.config = json.load(handle)
		with open(self.tokenizer_path, "r", encoding="utf-8") as handle:
			self.tokenizer = json.load(handle)

		self.vocab = self.tokenizer["model"]["vocab"]
		self.voices = self._load_voices()
		self.current_voice = sorted(self.voices.keys())[0] if self.voices else None
		self.provider_chain = self._build_provider_chain()
		self._preload_accelerator_dlls()
		self.session = ort.InferenceSession(
			self.model_path,
			providers=self.provider_chain,
		)
		log.info(
			"MaxLogic Kokoro initialized with providers %s (active %s) from %s",
			self.provider_chain,
			self.session.get_providers(),
			self._asset_root,
		)

	@classmethod
	def check_runtime_requirements(cls, package_root):
		missing = []
		if _resolve_existing_path(package_root, "config.json") is None:
			missing.append("config.json")
		if _resolve_existing_path(package_root, "tokenizer.json") is None:
			missing.append("tokenizer.json")
		if _resolve_existing_path(package_root, os.path.join("model", "kokoro.onnx")) is None:
			missing.append(os.path.join("model", "kokoro.onnx"))
		voice_dir = _resolve_existing_path(package_root, "voices", expect_dir=True)
		if voice_dir is None or not any(name.endswith(".npy") for name in os.listdir(voice_dir)):
			missing.append("voices/*.npy")
		espeak_exe = _resolve_existing_path(package_root, os.path.join("espeak", "espeak-ng.exe"))
		if espeak_exe is None:
			missing.append(os.path.join("espeak", "espeak-ng.exe"))
		return missing

	def _require_file(self, relative_path):
		path = _resolve_existing_path(self.package_root, relative_path)
		if path is None:
			raise RuntimeError("Required asset not found: %s" % relative_path)
		return path

	def _require_dir(self, relative_path):
		path = _resolve_existing_path(self.package_root, relative_path, expect_dir=True)
		if path is None:
			raise RuntimeError("Required asset directory not found: %s" % relative_path)
		return path

	def _require_voice_dir(self):
		for root in _candidate_asset_roots(self.package_root):
			candidate = os.path.join(root, "voices")
			if os.path.isdir(candidate) and any(name.endswith(".npy") for name in os.listdir(candidate)):
				return candidate
		raise RuntimeError("Required asset directory not found: voices with .npy files")

	def _build_provider_chain(self):
		available = ort.get_available_providers()
		device_id = int(os.environ.get("MAXLOGIC_KOKORO_DEVICE_ID", "0"))
		preference = os.environ.get("MAXLOGIC_KOKORO_PROVIDER", "auto").strip().lower()
		provider_map = {
			"cuda": ("CUDAExecutionProvider", {"device_id": device_id}),
			"dml": ("DmlExecutionProvider", {}),
			"cpu": "CPUExecutionProvider",
		}
		if preference == "auto":
			order = ["cuda", "dml", "cpu"]
		elif preference in provider_map:
			order = [preference]
			if preference != "cpu":
				order.append("cpu")
		else:
			log.warning("Unknown MAXLOGIC_KOKORO_PROVIDER=%s, using auto", preference)
			order = ["cuda", "dml", "cpu"]

		chain = []
		for key in order:
			value = provider_map[key]
			name = value[0] if isinstance(value, tuple) else value
			if name in available and value not in chain:
				chain.append(value)
		if "CPUExecutionProvider" not in [item[0] if isinstance(item, tuple) else item for item in chain]:
			chain.append("CPUExecutionProvider")
		return chain

	def _preload_accelerator_dlls(self):
		try:
			provider_names = [item[0] if isinstance(item, tuple) else item for item in self.provider_chain]
			if "CUDAExecutionProvider" in provider_names and hasattr(ort, "preload_dlls"):
				ort.preload_dlls()
		except Exception as error:
			log.warning("Failed to preload accelerator DLLs: %s", error)

	def _load_voices(self):
		voices = {}
		for filename in sorted(os.listdir(self.voice_dir)):
			if not filename.endswith(".npy"):
				continue
			voice_name = os.path.splitext(filename)[0]
			voice_path = os.path.join(self.voice_dir, filename)
			voices[voice_name] = self._normalize_voice_embedding(voice_name, np.load(voice_path))
		return voices

	def _normalize_voice_embedding(self, voice_name, embedding):
		if embedding.ndim == 3 and embedding.shape[1:] == (1, 256):
			index = min(100, embedding.shape[0] - 1) if voice_name.startswith("af_") else 0
			embedding = embedding[index]
		if embedding.ndim == 2 and embedding.shape[0] != 1:
			embedding = embedding[0:1]
		if embedding.ndim == 1:
			embedding = embedding.reshape(1, -1)
		if embedding.shape[1] > 256:
			embedding = embedding[:, :256]
		elif embedding.shape[1] < 256:
			padded = np.zeros((1, 256), dtype=np.float32)
			padded[:, :embedding.shape[1]] = embedding
			embedding = padded
		return embedding.astype(np.float32, copy=False)

	def list_voices(self):
		return list(self.voices.keys())

	def set_voice(self, voice_name):
		if voice_name not in self.voices:
			raise KeyError("Unknown voice: %s" % voice_name)
		self.current_voice = voice_name

	def text_to_tokens(self, text, language="en-us"):
		phonemes = self.phonemizer.phonemize(text, language=language)
		phonemes = WHITESPACE_RE.sub(" ", phonemes).strip()
		tokens = [self.vocab["$"]]
		for char in phonemes:
			if char in self.vocab:
				tokens.append(self.vocab[char])
				continue
			replacement = TOKEN_REPLACEMENTS.get(char)
			if replacement is None:
				continue
			for replacement_char in replacement:
				if replacement_char in self.vocab:
					tokens.append(self.vocab[replacement_char])
		tokens.append(self.vocab["$"])
		if len(tokens) <= 2:
			raise RuntimeError("Phonemizer produced no usable tokens for: %r" % text)
		return np.asarray(tokens, dtype=np.int64).reshape(1, -1)

	def synthesize(self, text, speed=0.85, voice=None, language="en-us"):
		voice_name = voice or self.current_voice
		if voice_name is None:
			raise RuntimeError("No Kokoro voices are available")
		tokens = self.text_to_tokens(text, language=language)
		style = self.voices[voice_name]
		outputs = self.session.run(
			None,
			{
				"tokens": tokens,
				"style": style,
				"speed": np.asarray([speed], dtype=np.float32),
			},
		)
		waveform = np.asarray(outputs[0]).squeeze()
		if waveform.size == 0:
			raise RuntimeError("Kokoro returned an empty waveform")
		return waveform.astype(np.float32, copy=False)

	def synthesize_to_int16(self, text, speed=0.85, voice=None, volume=1.0, language="en-us"):
		waveform = self.synthesize(text, speed=speed, voice=voice, language=language)
		waveform = np.clip(waveform * volume, -1.0, 1.0)
		return (waveform * 32767.0).astype(np.int16, copy=False)
