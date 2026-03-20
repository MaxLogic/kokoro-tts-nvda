import json
import logging
import os
import re
import unicodedata

import numpy as np
import onnxruntime as ort

try:
	from logHandler import log
except ImportError:
	log = logging.getLogger(__name__)

try:
	from ._phonemizer import EspeakPhonemizer, DEFAULT_REFERENCE_ROOT
	from ._voice_store import VoiceStoreError, discover_voice_records, ensure_user_voice_dir
except ImportError:
	from _phonemizer import EspeakPhonemizer, DEFAULT_REFERENCE_ROOT
	from _voice_store import VoiceStoreError, discover_voice_records, ensure_user_voice_dir


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
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])[\s\u2028\u2029]+")
CLAUSE_SPLIT_RE = re.compile(r"(?<=[,;:])[\s\u2028\u2029]+")


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
	max_input_tokens = 500
	target_chunk_tokens = 220
	first_chunk_tokens = 72

	def __init__(self, package_root):
		self.package_root = package_root
		self.user_voice_dir = ensure_user_voice_dir()
		self.model_path = self._require_file(os.path.join("model", "kokoro.onnx"))
		self.config_path = self._require_file("config.json")
		self.tokenizer_path = self._require_file("tokenizer.json")
		self._asset_root = os.path.dirname(self.config_path)
		self.phonemizer = EspeakPhonemizer(package_root)

		with open(self.config_path, "r", encoding="utf-8") as handle:
			self.config = json.load(handle)
		with open(self.tokenizer_path, "r", encoding="utf-8") as handle:
			self.tokenizer = json.load(handle)

		self.vocab = self.tokenizer["model"]["vocab"]
		self.provider_chain = self._build_provider_chain()
		self._preload_accelerator_dlls()
		self.session = ort.InferenceSession(
			self.model_path,
			providers=self.provider_chain,
		)
		self.voice_records = {}
		self.voice_sources = []
		self.voices = {}
		self.current_voice = None
		self.reload_voices()
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
		voice_roots = [("package", package_root)]
		override_root = os.environ.get("MAXLOGIC_KOKORO_ASSET_ROOT")
		if override_root:
			voice_roots.append(("override", override_root))
		voice_roots.append(("reference", DEFAULT_REFERENCE_ROOT))
		voice_records, __ = discover_voice_records(package_root, voice_roots)
		if not voice_records:
			missing.append("voices/*.(bin|json|npy)")
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
		fallback_roots = [(self._source_name_for_root(root), root) for root in _candidate_asset_roots(self.package_root)]
		records, __ = discover_voice_records(self.package_root, fallback_roots)
		if records:
			return next(iter(records.values())).source_root
		raise RuntimeError("Required asset directory not found: voices with .bin, .json, or .npy files")

	def _source_name_for_root(self, root):
		if os.path.abspath(root) == os.path.abspath(self.package_root):
			return "package"
		override_root = os.environ.get("MAXLOGIC_KOKORO_ASSET_ROOT")
		if override_root and os.path.abspath(root) == os.path.abspath(override_root):
			return "override"
		if os.path.abspath(root) == os.path.abspath(DEFAULT_REFERENCE_ROOT):
			return "reference"
		return "asset"

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

	def _load_voice_embedding(self, voice_name, voice_path):
		extension = os.path.splitext(voice_path)[1].lower()
		if extension == ".bin":
			embedding = np.fromfile(voice_path, dtype=np.float32)
			if embedding.size == 0 or embedding.size % 256 != 0:
				raise VoiceStoreError("Unsupported .bin voice embedding size for %s" % voice_name)
			return embedding.reshape((-1, 256))
		if extension == ".npy":
			return np.load(voice_path)
		if extension == ".json":
			with open(voice_path, "r", encoding="utf-8") as handle:
				return np.asarray(json.load(handle), dtype=np.float32)
		raise VoiceStoreError("Unsupported voice embedding format: %s" % extension)

	def _load_voices(self):
		fallback_roots = [(self._source_name_for_root(root), root) for root in _candidate_asset_roots(self.package_root)]
		voice_records, scanned_roots = discover_voice_records(self.package_root, fallback_roots)
		voices = {}
		for voice_name, record in voice_records.items():
			voices[voice_name] = self._normalize_voice_embedding(voice_name, self._load_voice_embedding(voice_name, record.file_path))
		self.voice_records = voice_records
		self.voice_sources = scanned_roots
		return voices

	def reload_voices(self, preferred_voice=None):
		previous_voice = preferred_voice or self.current_voice
		self.voices = self._load_voices()
		if not self.voices:
			self.current_voice = None
			raise RuntimeError("No Kokoro voices are available from user/package/reference sources")
		if previous_voice in self.voices:
			self.current_voice = previous_voice
		else:
			self.current_voice = sorted(self.voices.keys())[0]
		log.info(
			"MaxLogic Kokoro voice discovery reloaded. currentVoice=%s voiceCount=%s sources=%s",
			self.current_voice,
			len(self.voices),
			["%s:%s" % (source, root) for source, root in self.voice_sources],
		)
		return self.current_voice

	def get_status(self):
		return {
			"mode": "in-process",
			"providers": self.session.get_providers(),
			"voiceCount": len(self.voices),
			"currentVoice": self.current_voice,
			"pid": os.getpid(),
			"voiceSources": ["%s:%s" % (source, root) for source, root in self.voice_sources],
		}

	def _normalize_voice_embedding(self, voice_name, embedding):
		if embedding.ndim == 3 and embedding.shape[1:] == (1, 256):
			index = min(100, embedding.shape[0] - 1) if voice_name.startswith("af_") else 0
			embedding = embedding[index]
		if embedding.ndim == 2 and embedding.shape[1] == 256 and embedding.shape[0] != 1:
			index = min(100, embedding.shape[0] - 1) if voice_name.startswith("af_") else 0
			embedding = embedding[index:index + 1]
		elif embedding.ndim == 2 and embedding.shape[0] != 1:
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

	def load_preview_voice(self, voice_path):
		voice_name = os.path.splitext(os.path.basename(voice_path))[0]
		embedding = self._load_voice_embedding(voice_name, voice_path)
		return self._normalize_voice_embedding(voice_name, embedding)

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

	def segment_text(self, text, language="en-us", max_tokens=None, target_tokens=None, first_chunk_tokens=None):
		return list(
			self.iter_text_segments(
				text,
				language=language,
				max_tokens=max_tokens,
				target_tokens=target_tokens,
				first_chunk_tokens=first_chunk_tokens,
			)
		)

	def iter_text_segments(self, text, language="en-us", max_tokens=None, target_tokens=None, first_chunk_tokens=None):
		normalized = self._normalize_segment_text(text)
		if not normalized:
			return
		max_tokens = max_tokens or self.max_input_tokens
		target_tokens = min(target_tokens or self.target_chunk_tokens, max_tokens)
		first_chunk_tokens = min(first_chunk_tokens or self.first_chunk_tokens, target_tokens)
		total_tokens = self._estimate_token_count(normalized, language)
		first_chunk = None
		remainder = None
		if total_tokens > first_chunk_tokens:
			first_chunk, remainder = self._take_prefix_with_token_limit(normalized, language, first_chunk_tokens)
		if total_tokens <= max_tokens:
			if first_chunk and remainder:
				yield first_chunk
				for chunk in self.iter_text_segments(
					remainder,
					language=language,
					max_tokens=max_tokens,
					target_tokens=target_tokens,
					first_chunk_tokens=target_tokens,
				):
					yield chunk
				return
			yield normalized
			return

		if first_chunk and remainder:
			yield first_chunk
			for chunk in self.iter_text_segments(
				remainder,
				language=language,
				max_tokens=max_tokens,
				target_tokens=target_tokens,
				first_chunk_tokens=target_tokens,
			):
				yield chunk
			return

		segments = self._split_to_safe_units(normalized, language, max_tokens)
		chunks = []
		current = []
		for segment in segments:
			candidate_parts = current + [segment]
			candidate = " ".join(candidate_parts)
			token_count = self._estimate_token_count(candidate, language)
			if token_count <= target_tokens:
				current = candidate_parts
				continue
			if current:
				chunks.append(" ".join(current))
				current = [segment]
				continue
			chunks.append(segment)
			current = []
		if current:
			chunks.append(" ".join(current))
		for chunk in chunks:
			yield chunk

	def stream_synthesize_to_int16(self, text, speed=0.85, voice=None, volume=1.0, language="en-us", max_tokens=None, target_tokens=None, first_chunk_tokens=None):
		voice_name = voice or self.current_voice
		for chunk in self.iter_text_segments(
			text,
			language=language,
			max_tokens=max_tokens,
			target_tokens=target_tokens,
			first_chunk_tokens=first_chunk_tokens,
		):
			yield chunk, self.synthesize_to_int16(
				chunk,
				speed=speed,
				voice=voice_name,
				volume=volume,
				language=language,
			)

	def _split_to_safe_units(self, text, language, max_tokens):
		units = self._split_units(text, SENTENCE_SPLIT_RE)
		return self._flatten_oversized_units(units, language, max_tokens, self._split_clause_unit)

	def _split_clause_unit(self, text, language, max_tokens):
		units = self._split_units(text, CLAUSE_SPLIT_RE)
		return self._flatten_oversized_units(units, language, max_tokens, self._split_word_unit)

	def _split_word_unit(self, text, language, max_tokens):
		words = text.split()
		if len(words) <= 1:
			return [text]
		units = []
		current = []
		for word in words:
			candidate = " ".join(current + [word])
			if current and self._estimate_token_count(candidate, language) > max_tokens:
				units.append(" ".join(current))
				current = [word]
				continue
			current.append(word)
		if current:
			units.append(" ".join(current))
		return units or [text]

	def _flatten_oversized_units(self, units, language, max_tokens, split_oversized):
		safe_units = []
		for unit in units:
			token_count = self._estimate_token_count(unit, language)
			if token_count <= max_tokens:
				safe_units.append(unit)
				continue
			refined_units = split_oversized(unit, language, max_tokens)
			if len(refined_units) == 1 and refined_units[0] == unit:
				raise RuntimeError("Unable to split Kokoro input into a safe token window")
			safe_units.extend(refined_units)
		return safe_units

	def _split_units(self, text, pattern):
		units = []
		for piece in pattern.split(text):
			normalized = self._normalize_segment_text(piece)
			if normalized:
				units.append(normalized)
		return units or [text]

	def _estimate_token_count(self, text, language):
		return int(self.text_to_tokens(text, language=language).shape[1])

	def _take_prefix_with_token_limit(self, text, language, token_limit):
		if token_limit <= 0:
			return None, text
		words = text.split()
		if len(words) <= 1:
			return None, text
		prefix = []
		for index, word in enumerate(words):
			candidate = " ".join(prefix + [word])
			if prefix and self._estimate_token_count(candidate, language) > token_limit:
				return " ".join(prefix), " ".join(words[index:])
			prefix.append(word)
		return None, text

	def _normalize_segment_text(self, text):
		text = unicodedata.normalize("NFKC", text or "")
		text = WHITESPACE_RE.sub(" ", text).strip()
		return text

	def _synthesize_with_style(self, text, style, speed=0.85, language="en-us"):
		tokens = self.text_to_tokens(text, language=language)
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

	def synthesize(self, text, speed=0.85, voice=None, language="en-us"):
		voice_name = voice or self.current_voice
		if voice_name is None:
			raise RuntimeError("No Kokoro voices are available")
		return self._synthesize_with_style(text, self.voices[voice_name], speed=speed, language=language)

	def synthesize_to_int16(self, text, speed=0.85, voice=None, volume=1.0, language="en-us", generation=None):
		waveform = self.synthesize(text, speed=speed, voice=voice, language=language)
		waveform = np.clip(waveform * volume, -1.0, 1.0)
		return (waveform * 32767.0).astype(np.int16, copy=False)

	def synthesize_preview_to_int16(self, text, voice_path, speed=0.85, volume=1.0, language="en-us"):
		style = self.load_preview_voice(voice_path)
		waveform = self._synthesize_with_style(text, style, speed=speed, language=language)
		waveform = np.clip(waveform * volume, -1.0, 1.0)
		return (waveform * 32767.0).astype(np.int16, copy=False)
