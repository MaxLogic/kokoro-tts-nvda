# coding: utf-8

from datetime import datetime

import gui
from logHandler import log
import wx

from . import service


GENDER_FILTERS = [
	("all", _("All genders")),
	("female", _("Female")),
	("male", _("Male")),
	("unknown", _("Unknown")),
]

def _format_catalog_hint(payload):
	source = payload.get("source", "unknown")
	stale = payload.get("stale")
	fetched_at = payload.get("fetchedAt")
	if fetched_at:
		try:
			fetched_label = datetime.strptime(fetched_at, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M UTC")
		except ValueError:
			fetched_label = fetched_at
	else:
		fetched_label = _("unknown time")
	if source == "network":
		return _("Catalog refreshed from network at {time}").format(time=fetched_label)
	if source == "cache":
		if stale:
			return _("Cached catalog from {time} (stale offline fallback)").format(time=fetched_label)
		return _("Cached catalog from {time} (fresh)").format(time=fetched_label)
	if source == "bundled":
		if stale:
			return _("Bundled catalog fallback in use")
		return _("Bundled catalog")
	return _("Catalog source: {source}").format(source=source)


def _format_voice_source(record):
	source_labels = {
		"package": _("Built-in"),
		"override": _("Override asset root"),
		"reference": _("Reference add-on"),
		"user": _("User-installed"),
	}
	source_label = source_labels.get(record.source, record.source.title())
	name = record.display_name
	metadata = record.metadata or {}
	model_version = metadata.get("modelVersion")
	if model_version:
		name = _("{name} [{model}]").format(name=name, model=model_version)
	return _("{name} ({source})").format(name=name, source=source_label)


def _format_count_hint(visible_count, total_count, selected_count):
	return _("Showing {visible} of {total} voices | Selected: {selected}").format(
		visible=visible_count,
		total=total_count,
		selected=selected_count,
	)


def _format_cache_size(size_bytes):
	if not size_bytes:
		return _("0 MB")
	return _("{size:.2f} MB").format(size=(size_bytes / float(1024 * 1024)))


class InstalledVoicesPanel(wx.Panel):
	def __init__(self, parent, on_change):
		super(InstalledVoicesPanel, self).__init__(parent)
		self._on_change = on_change
		self._user_voices = []
		self._builtin_voices = []
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(wx.StaticText(self, label=_("User-installed voices")), 0, wx.ALL, 5)
		self.voice_list = wx.ListBox(self)
		sizer.Add(self.voice_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
		self.empty_user_hint = wx.StaticText(
			self,
			label=_("No user-installed voices yet. Built-in voices remain available below."),
		)
		sizer.Add(self.empty_user_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
		sizer.Add(wx.StaticText(self, label=_("Built-in and fallback voices")), 0, wx.ALL, 5)
		self.builtin_list = wx.ListBox(self, style=wx.LB_SINGLE)
		self.builtin_list.Enable(False)
		sizer.Add(self.builtin_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
		button_row = wx.BoxSizer(wx.HORIZONTAL)
		self.install_button = wx.Button(self, label=_("Install from local file"))
		self.remove_button = wx.Button(self, label=_("Remove selected voice"))
		self.refresh_button = wx.Button(self, label=_("Refresh installed voices"))
		button_row.Add(self.install_button, 0, wx.ALL, 5)
		button_row.Add(self.remove_button, 0, wx.ALL, 5)
		button_row.Add(self.refresh_button, 0, wx.ALL, 5)
		sizer.Add(button_row, 0, wx.ALL, 0)
		self.SetSizer(sizer)
		self.Bind(wx.EVT_BUTTON, self.on_install, self.install_button)
		self.Bind(wx.EVT_BUTTON, self.on_remove, self.remove_button)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.refresh_entries(), self.refresh_button)
		self.refresh_entries()

	def refresh_entries(self):
		inventory = service.list_voice_inventory()
		self._user_voices = inventory["user"]
		self._builtin_voices = inventory["builtin"]
		self.voice_list.SetItems([_format_voice_source(record) for record in self._user_voices])
		self.builtin_list.SetItems([_format_voice_source(record) for record in self._builtin_voices])
		self.remove_button.Enable(bool(self._user_voices))
		self.empty_user_hint.Show(not self._user_voices)
		self.Layout()

	def _selected_record(self):
		index = self.voice_list.GetSelection()
		if index == wx.NOT_FOUND or index >= len(self._user_voices):
			return None
		return self._user_voices[index]

	def _run_busy(self, message, callback):
		busy = wx.BusyInfo(message, parent=self)
		try:
			return callback()
		finally:
			del busy

	def on_install(self, event):
		dialog = wx.FileDialog(
			parent=gui.mainFrame,
			message=_("Choose a Kokoro voice file"),
			wildcard="Voice files (*.bin;*.json;*.npy;*.zip)|*.bin;*.json;*.npy;*.zip",
			style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
		)
		gui.mainFrame.prePopup()
		try:
			result_code = dialog.ShowModal()
		finally:
			gui.mainFrame.postPopup()
		if result_code != wx.ID_OK:
			return
		source_path = dialog.GetPath().strip()
		if not source_path:
			return
		try:
			result = self._run_busy(
				_("Installing local voice..."),
				lambda: service.install_local_voice(source_path, overwrite=False),
			)
		except service.DuplicateVoiceError:
			overwrite = gui.messageBox(
				_("This voice is already installed. Do you want to overwrite the user-managed copy?"),
				_("Voice already installed"),
				wx.YES_NO | wx.ICON_WARNING,
			)
			if overwrite != wx.YES:
				return
			result = self._run_busy(
				_("Overwriting local voice..."),
				lambda: service.install_local_voice(source_path, overwrite=True),
			)
		except Exception as error:
			log.exception("MaxLogic Kokoro local install failed", exc_info=True)
			gui.messageBox(
				_("Voice installation failed.\nSee NVDA's log for details.\n{error}").format(error=error),
				_("Voice installation failed"),
				wx.OK | wx.ICON_ERROR,
			)
			return
		self.refresh_entries()
		self._on_change()
		refresh = result["refresh"]
		message = _("Installed voice successfully.")
		if refresh.get("restartRequired"):
			message += "\n" + _("Restart NVDA to refresh the current synth.")
		gui.messageBox(message, _("Voice installed"), wx.OK | wx.ICON_INFORMATION)

	def on_remove(self, event):
		record = self._selected_record()
		if record is None:
			return
		response = gui.messageBox(
			_("Do you want to remove this user-installed voice?\nVoice: {voice}").format(voice=record.display_name),
			_("Remove voice?"),
			wx.YES_NO | wx.ICON_WARNING,
		)
		if response != wx.YES:
			return
		try:
			result = self._run_busy(
				_("Removing local voice..."),
				lambda: service.remove_local_voice(record.voice_id),
			)
		except Exception as error:
			log.exception("MaxLogic Kokoro local remove failed", exc_info=True)
			gui.messageBox(
				_("Voice removal failed.\nSee NVDA's log for details.\n{error}").format(error=error),
				_("Voice removal failed"),
				wx.OK | wx.ICON_ERROR,
			)
			return
		self.refresh_entries()
		self._on_change()
		message = _("Removed voice successfully.")
		if result["refresh"].get("restartRequired"):
			message += "\n" + _("Restart NVDA to refresh the current synth.")
		gui.messageBox(message, _("Voice removed"), wx.OK | wx.ICON_INFORMATION)


class CatalogVoicesPanel(wx.Panel):
	def __init__(self, parent, on_change, catalog_name, title, empty_message, allow_refresh, show_hide_local_toggle=False):
		super(CatalogVoicesPanel, self).__init__(parent)
		self._on_change = on_change
		self._catalog_name = catalog_name
		self._title = title
		self._empty_message = empty_message
		self._allow_refresh = allow_refresh
		self._show_hide_local_toggle = show_hide_local_toggle
		self._entries = []
		self._visible_entries = []
		self._installed_voice_ids = set()
		self._checked_ids = set()
		self._language_options = [("", _("All languages"))]
		self._preview_in_progress = False
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(wx.StaticText(self, label=title), 0, wx.ALL, 5)

		filter_row = wx.BoxSizer(wx.HORIZONTAL)
		filter_row.Add(wx.StaticText(self, label=_("Filter")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.search_text = wx.TextCtrl(self)
		filter_row.Add(self.search_text, 1, wx.EXPAND | wx.ALL, 5)
		filter_row.Add(wx.StaticText(self, label=_("Gender")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.gender_choice = wx.Choice(self, choices=[label for __, label in GENDER_FILTERS])
		self.gender_choice.SetSelection(0)
		filter_row.Add(self.gender_choice, 0, wx.ALL, 5)
		filter_row.Add(wx.StaticText(self, label=_("Language")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.language_choice = wx.Choice(self, choices=[self._language_options[0][1]])
		self.language_choice.SetSelection(0)
		filter_row.Add(self.language_choice, 0, wx.ALL, 5)
		sizer.Add(filter_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 0)
		if self._show_hide_local_toggle:
			self.hide_installed_checkbox = wx.CheckBox(self, label=_("Hide voices already available locally"))
			sizer.Add(self.hide_installed_checkbox, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
		else:
			self.hide_installed_checkbox = None

		self.voice_list = wx.CheckListBox(self)
		sizer.Add(self.voice_list, 1, wx.EXPAND | wx.ALL, 5)
		self.result_hint = wx.StaticText(self, label="")
		sizer.Add(self.result_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
		self.empty_hint = wx.StaticText(self, label="")
		sizer.Add(self.empty_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
		self.catalog_hint = wx.StaticText(self, label="")
		sizer.Add(self.catalog_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

		button_row = wx.BoxSizer(wx.HORIZONTAL)
		self.select_button = wx.Button(self, label=_("Select visible"))
		self.clear_button = wx.Button(self, label=_("Clear visible"))
		self.preview_button = wx.Button(self, label=_("Play sample"))
		self.download_button = wx.Button(self, label=_("Download selected voices"))
		self.refresh_button = wx.Button(self, label=_("Refresh catalog"))
		button_row.Add(self.select_button, 0, wx.ALL, 5)
		button_row.Add(self.clear_button, 0, wx.ALL, 5)
		button_row.Add(self.preview_button, 0, wx.ALL, 5)
		button_row.Add(self.download_button, 0, wx.ALL, 5)
		button_row.Add(self.refresh_button, 0, wx.ALL, 5)
		sizer.Add(button_row, 0, wx.ALL, 0)
		self.SetSizer(sizer)

		self.Bind(wx.EVT_TEXT, lambda evt: self._apply_filters(), self.search_text)
		self.Bind(wx.EVT_CHOICE, lambda evt: self._apply_filters(), self.gender_choice)
		self.Bind(wx.EVT_CHOICE, lambda evt: self._apply_filters(), self.language_choice)
		if self.hide_installed_checkbox is not None:
			self.Bind(wx.EVT_CHECKBOX, lambda evt: self._apply_filters(), self.hide_installed_checkbox)
		self.Bind(wx.EVT_LISTBOX, lambda evt: self._update_action_state(), self.voice_list)
		self.Bind(wx.EVT_CHECKLISTBOX, self.on_toggle_entry, self.voice_list)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.on_select_visible(), self.select_button)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.on_clear_visible(), self.clear_button)
		self.Bind(wx.EVT_BUTTON, self.on_play_sample, self.preview_button)
		self.Bind(wx.EVT_BUTTON, self.on_download_selected, self.download_button)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.refresh_entries(force_refresh=True), self.refresh_button)
		self.refresh_entries()

	def _format_entry(self, entry):
		size_bytes = entry.get("remoteSizeBytes") or entry.get("sizeBytes") or 0
		size_mb = round(size_bytes / (1024.0 * 1024.0), 2) if size_bytes else 0
		language_label = entry.get("languageLabel") or entry.get("language") or _("Unknown language")
		gender_label = entry.get("genderLabel") or _("Unknown")
		status = _("ready") if entry.get("availableOnline", True) else _("metadata only")
		return _("{name} | {language} | {gender} | {size} MB | {status}").format(
			name=entry.get("displayName", entry["id"]),
			language=language_label,
			gender=gender_label,
			size=size_mb,
			status=status,
		)

	def _selected_gender_key(self):
		index = self.gender_choice.GetSelection()
		if index == wx.NOT_FOUND:
			return "all"
		return GENDER_FILTERS[index][0]

	def _focused_entry(self):
		index = self.voice_list.GetSelection()
		if index == wx.NOT_FOUND or index >= len(self._visible_entries):
			return None
		return self._visible_entries[index]

	def _selected_language_key(self):
		index = self.language_choice.GetSelection()
		if index == wx.NOT_FOUND or index >= len(self._language_options):
			return ""
		return self._language_options[index][0]

	def _update_language_choices(self):
		current_key = self._selected_language_key()
		options = [("", _("All languages"))]
		seen = set()
		for entry in self._entries:
			key = entry.get("language", "") or ""
			label = entry.get("languageLabel") or key or _("Unknown language")
			if key in seen:
				continue
			seen.add(key)
			options.append((key, label))
		options.sort(key=lambda item: (item[0] != "", item[1].lower()))
		self._language_options = options
		self.language_choice.SetItems([label for __, label in options])
		target_index = 0
		for index, item in enumerate(options):
			if item[0] == current_key:
				target_index = index
				break
		self.language_choice.SetSelection(target_index)

	def refresh_entries(self, force_refresh=False):
		self._entries, payload = service.list_catalog_voices(
			catalog_name=self._catalog_name,
			force_refresh=force_refresh,
		)
		inventory = service.list_voice_inventory()
		self._installed_voice_ids = {record.voice_id for record in inventory["user"]}
		self._installed_voice_ids.update(record.voice_id for record in inventory["builtin"])
		self._entries = sorted(self._entries, key=lambda entry: entry.get("displayName", entry["id"]).lower())
		self._checked_ids.intersection_update({entry["id"] for entry in self._entries})
		self._update_language_choices()
		self.catalog_hint.SetLabel(_format_catalog_hint(payload))
		if not self._allow_refresh:
			self.refresh_button.Enable(False)
			self.refresh_button.Hide()
		self._apply_filters()

	def _apply_filters(self):
		search_text = self.search_text.GetValue().strip().lower()
		gender_key = self._selected_gender_key()
		language_key = self._selected_language_key()
		hide_installed = self.hide_installed_checkbox is not None and self.hide_installed_checkbox.GetValue()
		visible_entries = []
		for entry in self._entries:
			name = entry.get("displayName", entry["id"]).lower()
			if search_text and search_text not in name and search_text not in entry["id"].lower():
				continue
			if hide_installed and entry["id"] in self._installed_voice_ids:
				continue
			if gender_key != "all" and entry.get("gender", "unknown") != gender_key:
				continue
			if language_key and entry.get("language", "") != language_key:
				continue
			visible_entries.append(entry)
		self._visible_entries = visible_entries
		self.voice_list.SetItems([self._format_entry(entry) for entry in visible_entries])
		for index, entry in enumerate(visible_entries):
			self.voice_list.Check(index, entry["id"] in self._checked_ids)
		self.result_hint.SetLabel(
			_format_count_hint(len(self._visible_entries), len(self._entries), len(self._checked_ids))
		)
		if self._entries and not self._visible_entries:
			self.empty_hint.SetLabel(_("No voices match the current filters."))
		elif not self._entries:
			self.empty_hint.SetLabel(self._empty_message)
		else:
			self.empty_hint.SetLabel("")
		self._update_action_state()
		self.Layout()

	def _update_action_state(self):
		has_visible = bool(self._visible_entries)
		focused_entry = self._focused_entry()
		self.select_button.Enable(has_visible and not self._preview_in_progress)
		self.clear_button.Enable(has_visible and not self._preview_in_progress)
		self.download_button.Enable(bool(self._checked_ids) and not self._preview_in_progress)
		self.preview_button.Enable(
			focused_entry is not None and focused_entry.get("availableOnline", True) and not self._preview_in_progress
		)

	def on_toggle_entry(self, event):
		index = event.GetInt()
		if index == wx.NOT_FOUND or index >= len(self._visible_entries):
			return
		entry = self._visible_entries[index]
		if self.voice_list.IsChecked(index):
			self._checked_ids.add(entry["id"])
		else:
			self._checked_ids.discard(entry["id"])
		self.result_hint.SetLabel(
			_format_count_hint(len(self._visible_entries), len(self._entries), len(self._checked_ids))
		)
		self._update_action_state()

	def on_select_visible(self):
		for entry in self._visible_entries:
			self._checked_ids.add(entry["id"])
		self._apply_filters()

	def on_clear_visible(self):
		for entry in self._visible_entries:
			self._checked_ids.discard(entry["id"])
		self._apply_filters()

	def _run_busy(self, message, callback):
		busy = wx.BusyInfo(message, parent=self)
		try:
			return callback()
		finally:
			del busy

	def _install_entry(self, entry, overwrite):
		return service.install_catalog_voice(entry, overwrite=overwrite, refresh=False)

	def on_play_sample(self, event):
		entry = self._focused_entry()
		if entry is None:
			gui.messageBox(
				_("Select one voice in the list to play a sample."),
				_("No voice selected"),
				wx.OK | wx.ICON_INFORMATION,
			)
			return
		if not entry.get("availableOnline", True):
			gui.messageBox(
				_("This voice is not currently available from the online catalog source."),
				_("Voice unavailable"),
				wx.OK | wx.ICON_WARNING,
			)
			return
		self._preview_in_progress = True
		self.result_hint.SetLabel(_("Preparing sample for {name}...").format(name=entry.get("displayName", entry["id"])))
		self._update_action_state()

		def _on_complete(error_message):
			self._preview_in_progress = False
			if error_message:
				self.result_hint.SetLabel(_("Sample playback failed."))
				gui.messageBox(
					_("Sample playback failed.\nSee NVDA's log for details.\n{error}").format(error=error_message),
					_("Sample playback failed"),
					wx.OK | wx.ICON_ERROR,
				)
			else:
				self.result_hint.SetLabel(
					_format_count_hint(len(self._visible_entries), len(self._entries), len(self._checked_ids))
				)
			self._update_action_state()

		service.play_catalog_voice_sample(entry, on_complete=_on_complete)

	def on_download_selected(self, event):
		selected_entries = [entry for entry in self._entries if entry["id"] in self._checked_ids]
		if not selected_entries:
			return
		unavailable = [entry for entry in selected_entries if not entry.get("availableOnline", True)]
		downloadable = [entry for entry in selected_entries if entry.get("availableOnline", True)]
		if not downloadable:
			gui.messageBox(
				_("None of the selected voices are currently available for download."),
				_("No downloadable voices"),
				wx.OK | wx.ICON_WARNING,
			)
			return
		installed = []
		overwritten = []
		duplicates = []
		failures = []

		def _initial_pass():
			for entry in downloadable:
				try:
					result = self._install_entry(entry, overwrite=False)
				except service.DuplicateVoiceError:
					duplicates.append(entry)
				except Exception as error:
					log.exception("MaxLogic Kokoro catalog download failed", exc_info=True)
					failures.append((entry, error))
				else:
					installed.extend(result["records"])

		self._run_busy(_("Downloading selected voices..."), _initial_pass)

		if duplicates:
			response = gui.messageBox(
				_("{count} selected voices are already installed. Overwrite the user-managed copies?").format(
					count=len(duplicates)
				),
				_("Overwrite installed voices?"),
				wx.YES_NO | wx.ICON_WARNING,
			)
			if response == wx.YES:
				def _overwrite_pass():
					for entry in duplicates:
						try:
							result = self._install_entry(entry, overwrite=True)
						except Exception as error:
							log.exception("MaxLogic Kokoro catalog overwrite failed", exc_info=True)
							failures.append((entry, error))
						else:
							overwritten.extend(result["records"])

				self._run_busy(_("Overwriting selected voices..."), _overwrite_pass)

		refresh = service.refresh_active_synth(
			reason="%s-batch-install" % self._catalog_name,
			preferred_voice=(installed or overwritten)[0].voice_id if (installed or overwritten) else None,
		)
		self._checked_ids.clear()
		self._on_change()

		message_lines = []
		if installed:
			message_lines.append(_("Installed {count} voices.").format(count=len(installed)))
		if overwritten:
			message_lines.append(_("Overwrote {count} voices.").format(count=len(overwritten)))
		if unavailable:
			message_lines.append(_("Skipped {count} unavailable voices.").format(count=len(unavailable)))
		if duplicates and not overwritten:
			message_lines.append(_("Skipped {count} already-installed voices.").format(count=len(duplicates)))
		if failures:
			message_lines.append(_("Failed to install {count} voices. See NVDA's log for details.").format(count=len(failures)))
		if refresh.get("restartRequired"):
			message_lines.append(_("Restart NVDA to refresh the current synth."))
		if not message_lines:
			message_lines.append(_("No voice changes were applied."))
		title = _("Voice download complete") if not failures else _("Voice download completed with issues")
		gui.messageBox("\n".join(message_lines), title, wx.OK | wx.ICON_INFORMATION)


class SpeechCachePanel(wx.Panel):
	def __init__(self, parent):
		super(SpeechCachePanel, self).__init__(parent)
		self._mode_options = list(service.CACHE_MODE_OPTIONS)
		self._custom_limits = {"min": 2, "max": 80}
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		main_sizer.Add(wx.StaticText(self, label=_("Speech cache settings")), 0, wx.ALL, 5)

		self.enable_checkbox = wx.CheckBox(self, label=_("Enable speech cache"))
		main_sizer.Add(self.enable_checkbox, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

		form = wx.FlexGridSizer(cols=2, hgap=12, vgap=10)
		form.AddGrowableCol(1, 1)
		form.Add(wx.StaticText(self, label=_("Cache mode")), 0, wx.ALIGN_CENTER_VERTICAL)
		self.mode_choice = wx.Choice(self, choices=[label for __, label in self._mode_options])
		form.Add(self.mode_choice, 0, wx.EXPAND)
		form.Add(wx.StaticText(self, label=_("Maximum cache size (MB)")), 0, wx.ALIGN_CENTER_VERTICAL)
		self.max_size_ctrl = wx.SpinCtrl(self, min=16, max=4096, initial=256)
		form.Add(self.max_size_ctrl, 0, wx.EXPAND)
		form.Add(wx.StaticText(self, label=_("Minimum utterance length (characters)")), 0, wx.ALIGN_CENTER_VERTICAL)
		self.min_chars_ctrl = wx.SpinCtrl(self, min=1, max=256, initial=2)
		form.Add(self.min_chars_ctrl, 0, wx.EXPAND)
		form.Add(wx.StaticText(self, label=_("Maximum utterance length (characters)")), 0, wx.ALIGN_CENTER_VERTICAL)
		self.max_chars_ctrl = wx.SpinCtrl(self, min=1, max=512, initial=80)
		form.Add(self.max_chars_ctrl, 0, wx.EXPAND)
		main_sizer.Add(form, 0, wx.EXPAND | wx.ALL, 5)

		self.mode_hint = wx.StaticText(self, label="")
		main_sizer.Add(self.mode_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

		stats_box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Current cache"))
		self.path_label = wx.StaticText(self, label="")
		self.persistent_size_label = wx.StaticText(self, label="")
		self.persistent_entries_label = wx.StaticText(self, label="")
		self.hot_size_label = wx.StaticText(self, label="")
		self.hot_entries_label = wx.StaticText(self, label="")
		stats_box.Add(self.path_label, 0, wx.ALL, 5)
		stats_box.Add(self.persistent_size_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
		stats_box.Add(self.persistent_entries_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
		stats_box.Add(self.hot_size_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
		stats_box.Add(self.hot_entries_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
		main_sizer.Add(stats_box, 0, wx.EXPAND | wx.ALL, 5)

		button_row = wx.BoxSizer(wx.HORIZONTAL)
		self.save_button = wx.Button(self, label=_("Save cache settings"))
		self.refresh_button = wx.Button(self, label=_("Refresh cache stats"))
		self.compact_button = wx.Button(self, label=_("Compact cache"))
		self.clear_button = wx.Button(self, label=_("Clear cache"))
		button_row.Add(self.save_button, 0, wx.ALL, 5)
		button_row.Add(self.refresh_button, 0, wx.ALL, 5)
		button_row.Add(self.compact_button, 0, wx.ALL, 5)
		button_row.Add(self.clear_button, 0, wx.ALL, 5)
		main_sizer.Add(button_row, 0, wx.ALL, 0)

		self.status_label = wx.StaticText(self, label="")
		main_sizer.Add(self.status_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
		self.SetSizer(main_sizer)

		self.Bind(wx.EVT_CHECKBOX, lambda evt: self._update_custom_state(), self.enable_checkbox)
		self.Bind(wx.EVT_CHOICE, lambda evt: self._update_custom_state(), self.mode_choice)
		self.Bind(wx.EVT_SPINCTRL, self._on_custom_limit_change, self.min_chars_ctrl)
		self.Bind(wx.EVT_SPINCTRL, self._on_custom_limit_change, self.max_chars_ctrl)
		self.Bind(wx.EVT_BUTTON, self.on_save, self.save_button)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.refresh_from_runtime(), self.refresh_button)
		self.Bind(wx.EVT_BUTTON, self.on_compact, self.compact_button)
		self.Bind(wx.EVT_BUTTON, self.on_clear, self.clear_button)
		self.refresh_from_runtime()

	def _run_busy(self, message, callback):
		busy = wx.BusyInfo(message, parent=self)
		try:
			return callback()
		finally:
			del busy

	def _selected_mode_key(self):
		index = self.mode_choice.GetSelection()
		if index == wx.NOT_FOUND:
			return self._mode_options[0][0]
		return self._mode_options[index][0]

	def _load_into_controls(self, settings, stats):
		self.enable_checkbox.SetValue(bool(settings.get("enabled", True)))
		mode_key = settings.get("mode", self._mode_options[0][0])
		mode_index = 0
		for index, item in enumerate(self._mode_options):
			if item[0] == mode_key:
				mode_index = index
				break
		self.mode_choice.SetSelection(mode_index)
		self.max_size_ctrl.SetValue(int(settings.get("maxSizeMb", 256)))
		self._custom_limits = {
			"min": int(settings.get("customMinChars", settings.get("minChars", 2))),
			"max": int(settings.get("customMaxChars", settings.get("maxChars", 80))),
		}
		self._apply_stats(stats)
		self._update_custom_state()

	def _apply_stats(self, stats):
		cache_available = stats.get("available", True)
		self.clear_button.Enable(cache_available)
		self.compact_button.Enable(cache_available)
		if not stats.get("available", True):
			self.path_label.SetLabel(_("Database: unavailable"))
			self.persistent_size_label.SetLabel(_("Persistent cache size: unavailable"))
			self.persistent_entries_label.SetLabel(_("Persistent cache entries: unavailable"))
			self.hot_size_label.SetLabel(_("Hot cache size: unavailable"))
			self.hot_entries_label.SetLabel(_("Hot cache entries: unavailable"))
			return
		self.path_label.SetLabel(_("Database: {path}").format(path=stats.get("dbPath", "")))
		self.persistent_size_label.SetLabel(
			_("Persistent cache: {size} of {limit}").format(
				size=_format_cache_size(stats.get("sizeBytes", 0)),
				limit=_("{size} MB").format(size=stats.get("settings", {}).get("maxSizeMb", 0)),
			)
		)
		self.persistent_entries_label.SetLabel(
			_("Persistent cache entries: {count}").format(count=stats.get("entryCount", 0))
		)
		self.hot_size_label.SetLabel(
			_("Hot cache: {size}").format(size=_format_cache_size(stats.get("hotSizeBytes", 0)))
		)
		self.hot_entries_label.SetLabel(
			_("Hot cache entries: {count} | TTL: {ttl}s").format(
				count=stats.get("hotEntryCount", 0),
				ttl=stats.get("hotTtlSeconds", 0),
			)
		)

	def _update_custom_state(self):
		mode_key = self._selected_mode_key()
		is_custom = mode_key == "custom"
		if is_custom:
			self.min_chars_ctrl.SetValue(self._custom_limits["min"])
			self.max_chars_ctrl.SetValue(max(self._custom_limits["min"], self._custom_limits["max"]))
		elif mode_key == "short_medium":
			self.min_chars_ctrl.SetValue(2)
			self.max_chars_ctrl.SetValue(180)
		else:
			self.min_chars_ctrl.SetValue(2)
			self.max_chars_ctrl.SetValue(80)
		self.min_chars_ctrl.Enable(is_custom)
		self.max_chars_ctrl.Enable(is_custom)
		if mode_key == "short_ui":
			self.mode_hint.SetLabel(_("Caches short repeated UI speech such as navigation prompts and command feedback."))
		elif mode_key == "short_medium":
			self.mode_hint.SetLabel(_("Extends caching to somewhat longer announcements at the cost of more disk usage."))
		else:
			self.mode_hint.SetLabel(_("Custom mode lets you decide the minimum and maximum utterance lengths that are eligible for caching."))
		self.Layout()

	def _on_custom_limit_change(self, event):
		self._custom_limits["min"] = self.min_chars_ctrl.GetValue()
		self._custom_limits["max"] = max(self._custom_limits["min"], self.max_chars_ctrl.GetValue())
		if self.max_chars_ctrl.GetValue() != self._custom_limits["max"]:
			self.max_chars_ctrl.SetValue(self._custom_limits["max"])
		event.Skip()

	def _collect_settings(self):
		return {
			"enabled": self.enable_checkbox.GetValue(),
			"mode": self._selected_mode_key(),
			"maxSizeMb": self.max_size_ctrl.GetValue(),
			"customMinChars": self._custom_limits["min"],
			"customMaxChars": self._custom_limits["max"],
		}

	def refresh_from_runtime(self):
		settings = service.get_speech_cache_settings()
		stats = service.get_speech_cache_stats()
		self._load_into_controls(settings, stats)
		if stats.get("available", True):
			self.status_label.SetLabel(
				_("Speech cache settings loaded. Persistent cache shows SQLite-backed audio; hot cache shows short-lived helper memory used for quick paragraph repeats.")
			)
		else:
			self.status_label.SetLabel(
				_("Speech cache is currently unavailable.\nReason: {error}").format(error=stats.get("error", _("unknown")))
			)

	def on_save(self, event):
		try:
			payload = self._run_busy(
				_("Saving speech cache settings..."),
				lambda: service.save_speech_cache_settings(self._collect_settings()),
			)
		except Exception as error:
			log.exception("MaxLogic Kokoro speech cache settings save failed", exc_info=True)
			gui.messageBox(
				_("Saving speech cache settings failed.\nSee NVDA's log for details.\n{error}").format(error=error),
				_("Speech cache settings failed"),
				wx.OK | wx.ICON_ERROR,
			)
			return
		self._load_into_controls(payload["settings"], payload["stats"])
		self.status_label.SetLabel(_("Speech cache settings saved."))
		gui.messageBox(
			_("Speech cache settings were saved and will apply to new utterances immediately."),
			_("Speech cache settings saved"),
			wx.OK | wx.ICON_INFORMATION,
		)

	def on_clear(self, event):
		response = gui.messageBox(
			_("Do you want to remove all cached speech audio?"),
			_("Clear speech cache?"),
			wx.YES_NO | wx.ICON_WARNING,
		)
		if response != wx.YES:
			return
		try:
			stats = self._run_busy(_("Clearing speech cache..."), service.clear_speech_cache)
		except Exception as error:
			log.exception("MaxLogic Kokoro clear speech cache failed", exc_info=True)
			gui.messageBox(
				_("Clearing the speech cache failed.\nSee NVDA's log for details.\n{error}").format(error=error),
				_("Clear speech cache failed"),
				wx.OK | wx.ICON_ERROR,
			)
			return
		self._apply_stats(stats)
		self.status_label.SetLabel(_("Speech cache cleared."))

	def on_compact(self, event):
		try:
			payload = self._run_busy(_("Compacting speech cache..."), service.compact_speech_cache)
		except Exception as error:
			log.exception("MaxLogic Kokoro compact speech cache failed", exc_info=True)
			gui.messageBox(
				_("Compacting the speech cache failed.\nSee NVDA's log for details.\n{error}").format(error=error),
				_("Compact speech cache failed"),
				wx.OK | wx.ICON_ERROR,
			)
			return
		self._apply_stats(payload["stats"])
		if payload.get("restartRequired"):
			self.status_label.SetLabel(_("Close MaxLogic Kokoro or restart NVDA before compacting the cache."))
			gui.messageBox(
				_("Speech cache compaction cannot run while MaxLogic Kokoro is the active synth.\nSwitch to another synth or restart NVDA, then try again."),
				_("Speech cache compaction unavailable"),
				wx.OK | wx.ICON_INFORMATION,
			)
			return
		self.status_label.SetLabel(_("Speech cache compacted."))


class MaxLogicVoiceManagerDialog(wx.Dialog):
	def __init__(self):
		super(MaxLogicVoiceManagerDialog, self).__init__(
			parent=gui.mainFrame,
			title=_("MaxLogic Kokoro voice manager"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self.SetSize((900, 620))
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		self.notebook = wx.Notebook(self)
		self.installed_panel = InstalledVoicesPanel(self.notebook, on_change=self.refresh_all)
		self.official_panel = CatalogVoicesPanel(
			self.notebook,
			on_change=self.refresh_all,
			catalog_name="official",
			title=_("Official Kokoro voices"),
			empty_message=_("No official voices are available in the current catalog."),
			allow_refresh=True,
			show_hide_local_toggle=True,
		)
		self.official_v11zh_panel = CatalogVoicesPanel(
			self.notebook,
			on_change=self.refresh_all,
			catalog_name="official_v11zh",
			title=_("Official Kokoro v1.1-zh voices"),
			empty_message=_("No official v1.1-zh voices are available in the current catalog."),
			allow_refresh=True,
			show_hide_local_toggle=True,
		)
		self.community_panel = CatalogVoicesPanel(
			self.notebook,
			on_change=self.refresh_all,
			catalog_name="community",
			title=_("Community and experimental voices"),
			empty_message=_("No curated community voices are listed yet."),
			allow_refresh=False,
			show_hide_local_toggle=True,
		)
		self.cache_panel = SpeechCachePanel(self.notebook)
		self.notebook.AddPage(self.installed_panel, _("Installed"))
		self.notebook.AddPage(self.official_panel, _("Official"))
		self.notebook.AddPage(self.official_v11zh_panel, _("Official v1.1-zh"))
		self.notebook.AddPage(self.community_panel, _("Community"))
		self.notebook.AddPage(self.cache_panel, _("Speech Cache"))
		self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_page_changed)
		main_sizer.Add(self.notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
		button_sizer = self.CreateButtonSizer(wx.CLOSE)
		main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 10)
		self.SetSizer(main_sizer)
		self.CentreOnScreen()
		self._log_active_page()

	def refresh_all(self):
		self.installed_panel.refresh_entries()
		self.official_panel.refresh_entries(force_refresh=False)
		self.official_v11zh_panel.refresh_entries(force_refresh=False)
		self.community_panel.refresh_entries(force_refresh=False)
		self.cache_panel.refresh_from_runtime()

	def _describe_active_page(self):
		index = self.notebook.GetSelection()
		if index == wx.NOT_FOUND:
			return None
		label = self.notebook.GetPageText(index)
		page = self.notebook.GetPage(index)
		catalog_name = getattr(page, "_catalog_name", None)
		return {
			"index": index,
			"label": label,
			"catalog": catalog_name,
		}

	def _log_active_page(self):
		payload = self._describe_active_page()
		if payload is None:
			return
		log.info(
			"MaxLogic Kokoro voice manager selected page. label=%s catalog=%s index=%s",
			payload["label"],
			payload["catalog"] or "n/a",
			payload["index"],
		)

	def on_page_changed(self, event):
		self._log_active_page()
		event.Skip()
