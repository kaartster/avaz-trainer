"""``avaz gui``: one window to pick a song, choose a key and start practicing.

Everything set here is stored in the same files the command line uses: the
song's choices in ``data/phrases/<song>/song.yaml`` and the student's own
preferences (default key, sound devices, scale) in ``data/user.yaml``. So the
window and ``avaz song`` always agree, and every classmate keeps their own key.

Slow work (vocal separation, pitch analysis) runs in a background thread so the
window stays responsive. The practice windows themselves are the usual song
mode and phrase practice windows.
"""

from __future__ import annotations

import math
import traceback
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..config import (data_dir, load_settings, load_song_config, load_user_prefs,
                      save_song_config, save_user_prefs)
from ..keys import key_choices, note_label
from ..library import Song, discover_songs, import_recording, phrase_files, prepare_song
from ..scales import load_scales

DEFAULT_DEVICE = "System default"


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class Job(QtCore.QThread):
    """Run ``fn()`` off the UI thread; ``finished_ok`` or ``failed`` reports the outcome."""
    finished_ok = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.finished_ok.emit(self.fn())
        except Exception as exc:   # shown to the user, details in the console
            traceback.print_exc()
            self.failed.emit(str(exc) or type(exc).__name__)


class Launcher(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.prefs = load_user_prefs()
        self.scales = load_scales()
        self.songs: list[Song] = []
        self.song: Song | None = None
        self.job: Job | None = None
        self.practice_window = None
        self._loading = False          # True while filling the form from a song

        self.setWindowTitle("Avaz Trainer")
        self._build_ui()
        self.refresh(select=self.prefs.get("last_song"))

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)

        devices = QtWidgets.QHBoxLayout()
        self.input_combo = self._device_combo("input", "input_device")
        self.output_combo = self._device_combo("output", "output_device")
        devices.addWidget(QtWidgets.QLabel("Microphone"))
        devices.addWidget(self.input_combo, 1)
        devices.addSpacing(16)
        devices.addWidget(QtWidgets.QLabel("Headphones or speakers"))
        devices.addWidget(self.output_combo, 1)
        outer.addLayout(devices)

        split = QtWidgets.QHBoxLayout()
        outer.addLayout(split, 1)

        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Songs"))
        self.song_list = QtWidgets.QListWidget()
        self.song_list.setMinimumWidth(260)
        self.song_list.currentRowChanged.connect(self._on_song_selected)
        left.addWidget(self.song_list, 1)
        add = QtWidgets.QPushButton("Add recording...")
        add.clicked.connect(self._add_recording)
        left.addWidget(add)
        split.addLayout(left)

        right = QtWidgets.QVBoxLayout()
        split.addLayout(right, 1)
        self.title = QtWidgets.QLabel("")
        f = QtGui.QFont()
        f.setPointSize(14)
        f.setBold(True)
        self.title.setFont(f)
        right.addWidget(self.title)

        prep = QtWidgets.QHBoxLayout()
        self.prep_label = QtWidgets.QLabel("")
        self.separate_btn = QtWidgets.QPushButton("Separate voice")
        self.separate_btn.setToolTip("Remove piano or other instruments with Demucs (a few minutes)")
        self.separate_btn.clicked.connect(self._separate)
        self.analyze_btn = QtWidgets.QPushButton("Analyze pitch")
        self.analyze_btn.clicked.connect(self._analyze)
        prep.addWidget(self.prep_label, 1)
        prep.addWidget(self.separate_btn)
        prep.addWidget(self.analyze_btn)
        right.addLayout(prep)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        right.addLayout(form)

        # Teacher tonic: number in Hz, its note name, and a measurement against
        # another recording of the same song.
        tonic_row = QtWidgets.QHBoxLayout()
        self.teacher_spin = QtWidgets.QDoubleSpinBox()
        self.teacher_spin.setRange(50.0, 800.0)
        self.teacher_spin.setDecimals(1)
        self.teacher_spin.setSuffix(" Hz")
        self.teacher_spin.valueChanged.connect(self._on_teacher_tonic)
        self.teacher_note = QtWidgets.QLabel("")
        tonic_row.addWidget(self.teacher_spin)
        tonic_row.addWidget(self.teacher_note)
        tonic_row.addStretch(1)
        form.addRow("Teacher's tonic", tonic_row)

        measure_row = QtWidgets.QHBoxLayout()
        self.reference_combo = QtWidgets.QComboBox()
        self.measure_btn = QtWidgets.QPushButton("Measure")
        self.measure_btn.setToolTip("Find the tonic by comparing with another recording of the "
                                    "same song whose tonic is already right")
        self.measure_btn.clicked.connect(self._measure_tonic)
        measure_row.addWidget(QtWidgets.QLabel("compare with"))
        measure_row.addWidget(self.reference_combo, 1)
        measure_row.addWidget(self.measure_btn)
        form.addRow("", measure_row)

        # The key I sing in.
        key_row = QtWidgets.QVBoxLayout()
        self.same_radio = QtWidgets.QRadioButton("The teacher's key")
        self.own_radio = QtWidgets.QRadioButton("My own key:")
        self.same_radio.toggled.connect(self._on_key_changed)
        # Every radio button here shares one parent widget, so each pair gets its
        # own group; otherwise picking a practice mode would clear the key choice.
        self.key_group = QtWidgets.QButtonGroup(self)
        self.key_group.addButton(self.same_radio)
        self.key_group.addButton(self.own_radio)
        own = QtWidgets.QHBoxLayout()
        self.key_combo = QtWidgets.QComboBox()
        for label, hz in key_choices(2, 5):
            self.key_combo.addItem(label, hz)
        self.key_combo.activated.connect(self._on_key_note)
        self.key_spin = QtWidgets.QDoubleSpinBox()
        self.key_spin.setRange(50.0, 1000.0)
        self.key_spin.setDecimals(1)
        self.key_spin.setSuffix(" Hz")
        self.key_spin.valueChanged.connect(self._on_key_changed)
        self.key_hint = QtWidgets.QLabel("")
        self.key_hint.setStyleSheet("color: gray")
        own.addWidget(self.own_radio)
        own.addWidget(self.key_combo)
        own.addWidget(self.key_spin)
        own.addStretch(1)
        key_row.addWidget(self.same_radio)
        key_row.addLayout(own)
        key_row.addWidget(self.key_hint)
        form.addRow("I sing in", key_row)

        self.scale_combo = QtWidgets.QComboBox()
        self.scale_combo.addItem("No guide lines", None)
        for name in self.scales:
            self.scale_combo.addItem(name.capitalize(), name)
        self.scale_combo.currentIndexChanged.connect(
            lambda: self._save_prefs(scale=self.scale_combo.currentData()))
        form.addRow("Scale", self.scale_combo)

        mode_row = QtWidgets.QHBoxLayout()
        self.song_mode = QtWidgets.QRadioButton("Whole song (pause anywhere)")
        self.phrase_mode = QtWidgets.QRadioButton("Saved phrases")
        self.song_mode.setChecked(True)
        self.mode_group = QtWidgets.QButtonGroup(self)
        self.mode_group.addButton(self.song_mode)
        self.mode_group.addButton(self.phrase_mode)
        mode_row.addWidget(self.song_mode)
        mode_row.addWidget(self.phrase_mode)
        mode_row.addStretch(1)
        form.addRow("Practice", mode_row)

        intro_row = QtWidgets.QHBoxLayout()
        self.intro_label = QtWidgets.QLabel("")
        self.intro_clear = QtWidgets.QPushButton("Play from the start")
        self.intro_clear.clicked.connect(self._clear_intro)
        intro_row.addWidget(self.intro_label)
        intro_row.addWidget(self.intro_clear)
        intro_row.addStretch(1)
        form.addRow("Intro", intro_row)

        self.progress_label = QtWidgets.QLabel("")
        form.addRow("Progress", self.progress_label)

        right.addStretch(1)
        go = QtWidgets.QHBoxLayout()
        go.addStretch(1)
        self.practice_btn = QtWidgets.QPushButton("Practice")
        self.practice_btn.setDefault(True)
        self.practice_btn.setMinimumWidth(140)
        self.practice_btn.clicked.connect(self._practice)
        go.addWidget(self.practice_btn)
        right.addLayout(go)

        self.statusBar().showMessage("")
        scale = self.prefs.get("scale", "dashti" if "dashti" in self.scales else None)
        i = self.scale_combo.findData(scale)
        self.scale_combo.setCurrentIndex(max(i, 0))

    def _device_combo(self, kind: str, pref_key: str) -> QtWidgets.QComboBox:
        from ..audio_io import device_names
        combo = QtWidgets.QComboBox()
        combo.addItem(DEFAULT_DEVICE, None)
        try:
            for name in device_names(kind):
                combo.addItem(name.strip(), name)
        except Exception as exc:
            combo.setToolTip(f"could not list devices: {exc}")
        i = combo.findData(self.prefs.get(pref_key))
        combo.setCurrentIndex(max(i, 0))
        combo.currentIndexChanged.connect(lambda: self._save_prefs(**{pref_key: combo.currentData()}))
        return combo

    # ------------------------------------------------------------------ library
    def refresh(self, select: str | None = None):
        d = data_dir()
        self.songs = discover_songs(d / "teacher", d / "phrases", d / "attempts")
        current = select or (self.song.name if self.song else None)
        self.song_list.blockSignals(True)
        self.song_list.clear()
        for song in self.songs:
            item = QtWidgets.QListWidgetItem(f"{song.name}\n{self._song_subtitle(song)}")
            self.song_list.addItem(item)
        self.song_list.blockSignals(False)
        names = [s.name for s in self.songs]
        row = names.index(current) if current in names else (0 if names else -1)
        self.song_list.setCurrentRow(row)
        self._on_song_selected(row)

    def _song_subtitle(self, song: Song) -> str:
        if not song.analyzed:
            return "    not analyzed yet"
        if song.config.get("same_key"):
            key = "teacher's key"
        else:
            hz = song.config.get("my_tonic_hz") or self._default_key()
            key = f"my key {note_label(hz, show_cents=False)}" if hz else "my key"
        p = song.progress()
        tail = f", {plural(p.attempts, 'attempt')}" if p.attempts else ""
        return f"    {key}{tail}"

    def _default_key(self) -> float | None:
        hz = self.prefs.get("my_tonic_hz") or self.settings.get("tonic", {}).get("mine_hz")
        return float(hz) if hz else None

    def _teacher_tonic_of(self, song: Song) -> float | None:
        """song.yaml first, then the tonic stored in the pitch curve file."""
        hz = song.config.get("teacher_tonic_hz")
        if hz:
            return float(hz)
        if song.analyzed:
            try:
                import json
                with open(song.curve_path, "r", encoding="utf-8") as fh:
                    # Only the header is needed, but the file is plain JSON: read it all.
                    return float(json.load(fh)["tonic_hz"])
            except (OSError, ValueError, KeyError):
                return None
        return None

    # ------------------------------------------------------------------ form
    def _on_song_selected(self, row: int):
        self.song = self.songs[row] if 0 <= row < len(self.songs) else None
        song = self.song
        enabled = song is not None
        for w in (self.practice_btn, self.teacher_spin, self.same_radio, self.own_radio,
                  self.key_combo, self.key_spin, self.measure_btn, self.reference_combo):
            w.setEnabled(enabled)
        if song is None:
            self.title.setText("Add a recording from your teacher to begin")
            self.prep_label.setText("")
            self.separate_btn.setVisible(False)
            self.analyze_btn.setVisible(False)
            return
        self._loading = True
        song.config = load_song_config(song.phrase_dir)
        self.title.setText(song.name)
        self.title.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignAbsolute)

        parts = ["voice separated" if song.vocals else "original recording",
                 "pitch analyzed" if song.analyzed else "pitch not analyzed yet"]
        self.prep_label.setText(", ".join(parts))
        self.separate_btn.setVisible(song.vocals is None)
        self.analyze_btn.setVisible(not song.analyzed)

        teacher = self._teacher_tonic_of(song)
        self.teacher_spin.setValue(teacher or 0.0)
        self.teacher_note.setText(note_label(teacher) if teacher else "unknown until analyzed")

        self.reference_combo.clear()
        for other in self.songs:
            if other is not song and other.analyzed:
                self.reference_combo.addItem(other.name, other.name)
        has_ref = self.reference_combo.count() > 0 and song.analyzed
        self.measure_btn.setEnabled(has_ref)
        self.reference_combo.setEnabled(has_ref)

        same = bool(song.config.get("same_key", False))
        mine = song.config.get("my_tonic_hz") or self._default_key() or teacher or 146.8
        self.key_spin.setValue(float(mine))
        self._sync_key_combo(float(mine))
        self.same_radio.setChecked(same)
        self.own_radio.setChecked(not same)
        self._update_key_widgets()

        phrases = phrase_files(song.phrase_dir)
        self.phrase_mode.setEnabled(bool(phrases))
        self.phrase_mode.setText(f"Saved phrases ({len(phrases)})")
        if not phrases:
            self.song_mode.setChecked(True)

        intro = float(song.config.get("intro_end_seconds") or 0.0)
        if intro > 0:
            self.intro_label.setText(f"skipped, the song starts at {int(intro // 60)}:{intro % 60:04.1f}")
        else:
            self.intro_label.setText("none cut (press Delete while practicing to cut it)")
        self.intro_clear.setVisible(intro > 0)

        p = song.progress()
        if p.attempts:
            text = (f"{plural(p.attempts, 'attempt')} on {plural(p.phrases, 'phrase')}, "
                    f"last on {p.last_day}")
            if not math.isnan(p.recent_pct):
                text += f", last 10: {p.recent_pct:.0f}% in tune"
        else:
            text = "not practiced yet"
        self.progress_label.setText(text)
        self.practice_btn.setEnabled(song.analyzed and teacher is not None)
        self._loading = False
        self._save_prefs(last_song=song.name)

    def _sync_key_combo(self, hz: float):
        best = min(range(self.key_combo.count()),
                   key=lambda i: abs(math.log2(self.key_combo.itemData(i) / hz)))
        self.key_combo.setCurrentIndex(best)

    def _update_key_widgets(self):
        own = self.own_radio.isChecked()
        self.key_combo.setEnabled(own)
        self.key_spin.setEnabled(own)
        teacher = self.teacher_spin.value()
        if not teacher:
            self.key_hint.setText("")
        elif own:
            diff = 1200 * math.log2(self.key_spin.value() / teacher)
            self.key_hint.setText(f"{note_label(self.key_spin.value())}, {diff:+.0f} cents from the "
                                  f"teacher. Your curve is shifted onto the teacher's.")
        else:
            self.key_hint.setText(f"{note_label(teacher)}. Your pitch is compared exactly as you "
                                  f"sing it, nothing is shifted.")

    def _on_key_note(self, index: int):
        self.key_spin.setValue(float(self.key_combo.itemData(index)))

    def _on_key_changed(self, *_):
        if self._loading or self.song is None:
            return
        same = self.same_radio.isChecked()
        hz = round(self.key_spin.value(), 1)
        self._sync_key_combo(hz)
        save_song_config(self.song.phrase_dir, same_key=same, my_tonic_hz=None if same else hz)
        if not same:
            self._save_prefs(my_tonic_hz=hz)    # the last key I chose becomes my default
        self._update_key_widgets()
        self._refresh_current_item()

    def _on_teacher_tonic(self, value: float):
        if self.song is not None:
            self.teacher_note.setText(note_label(value) if value else "")
        if self._loading or self.song is None or not value:
            return
        save_song_config(self.song.phrase_dir, teacher_tonic_hz=round(value, 1))
        self._update_key_widgets()

    def _clear_intro(self):
        if self.song is None:
            return
        save_song_config(self.song.phrase_dir, intro_end_seconds=0.0)
        self._on_song_selected(self.song_list.currentRow())

    def _refresh_current_item(self):
        row = self.song_list.currentRow()
        if self.song is not None and row >= 0:
            self.song.config = load_song_config(self.song.phrase_dir)
            self.song_list.item(row).setText(f"{self.song.name}\n{self._song_subtitle(self.song)}")

    def _save_prefs(self, **updates):
        if self._loading:
            return
        self.prefs.update(updates)
        save_user_prefs(updates)

    # ------------------------------------------------------------------ background jobs
    def _run(self, message: str, fn, on_done):
        if self.job is not None and self.job.isRunning():
            self.statusBar().showMessage("still busy with the previous step, please wait")
            return
        self.statusBar().showMessage(message)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.BusyCursor)
        self.job = Job(fn, self)

        def done(result):
            QtWidgets.QApplication.restoreOverrideCursor()
            on_done(result)

        def failed(msg):
            QtWidgets.QApplication.restoreOverrideCursor()
            self.statusBar().showMessage(f"failed: {msg}")
            QtWidgets.QMessageBox.warning(self, "Avaz Trainer", msg)

        self.job.finished_ok.connect(done)
        self.job.failed.connect(failed)
        self.job.start()

    def _add_recording(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Add a recording from your teacher", str(Path.home()),
            "Audio (*.m4a *.mp3 *.opus *.ogg *.wav *.flac *.aac);;All files (*)")
        if not path:
            return
        try:
            dest = import_recording(Path(path), data_dir() / "teacher")
        except (ValueError, FileExistsError) as exc:
            QtWidgets.QMessageBox.warning(self, "Avaz Trainer", str(exc))
            return
        answer = QtWidgets.QMessageBox.question(
            self, "Avaz Trainer",
            "Is there an instrument (piano, tar, setar ...) in this recording besides the voice?\n\n"
            "If yes, the voice is separated first. That takes a few minutes.")
        self.refresh(select=dest.stem)
        if answer == QtWidgets.QMessageBox.Yes:
            self._separate(then_analyze=True)
        else:
            self._analyze()

    def _separate(self, then_analyze: bool = False):
        song = self.song
        if song is None:
            return

        def work():
            try:
                from ..separate import separate_file
            except ImportError:
                raise RuntimeError("Vocal separation needs Demucs: run  pip install demucs")
            return separate_file(song.original, progress=False)

        def done(_):
            self.refresh(select=song.name)
            if then_analyze or not self.song.analyzed:
                self._analyze()
            else:
                self.statusBar().showMessage("voice separated")

        self._run(f"separating the voice of {song.name} (a few minutes) ...", work, done)

    def _analyze(self):
        song = self.song
        if song is None:
            return
        tonic = song.config.get("teacher_tonic_hz") or "auto"
        settings = self.settings

        def work():
            from ..pitch_offline import load_or_analyze
            return load_or_analyze(song.practice_path, settings, tonic, reanalyze=True,
                                   log=lambda *_: None)

        def done(curve):
            self.refresh(select=song.name)
            self.statusBar().showMessage(
                f"analyzed. The tonic guess is {note_label(curve.tonic_hz)}: check it, or use "
                f"Measure if you have this song in another key")

        self._run(f"analyzing the pitch of {song.name} (about a minute) ...", work, done)

    def _measure_tonic(self):
        song = self.song
        ref_name = self.reference_combo.currentData()
        ref = next((s for s in self.songs if s.name == ref_name), None)
        if song is None or ref is None:
            return
        ref_tonic = self._teacher_tonic_of(ref)

        def work():
            from ..compare import tonic_from_reference
            from ..pitch_offline import load_curve
            curve = load_curve(song.curve_path)
            reference = load_curve(ref.curve_path)
            if ref_tonic:
                reference = reference.with_tonic(ref_tonic)
            return tonic_from_reference(curve, reference)

        def done(hz):
            if not hz or math.isnan(hz):
                self.statusBar().showMessage("not enough singing to compare these two recordings")
                return
            self.teacher_spin.setValue(round(hz, 1))
            self.statusBar().showMessage(
                f"measured {hz:.1f} Hz, {note_label(hz)}, against {ref.name}")

        self._run(f"comparing with {ref.name} ...", work, done)

    # ------------------------------------------------------------------ practice
    def _practice(self):
        song = self.song
        if song is None:
            return
        if self.practice_window is not None:
            self.practice_window.raise_()
            self.practice_window.activateWindow()
            return
        from ..audio_io import resolve_device
        from ..practice import PracticeEngine
        settings = self.settings
        audio = settings.get("audio", {})
        sr = int(audio.get("sample_rate", 44100))
        block = int(audio.get("hop_length", 256))
        scale = self.scales.get(self.scale_combo.currentData()) if self.scale_combo.currentData() else None
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            engine = PracticeEngine(sr, block,
                                    input_device=resolve_device(self.input_combo.currentData(), "input"),
                                    output_device=resolve_device(self.output_combo.currentData(), "output"))
            if self.phrase_mode.isChecked():
                from .practice_view import PracticeView
                view = PracticeView(engine, phrase_files(song.phrase_dir)[0], settings, scale, None)
                view.setWindowTitle(f"avaz practice: {song.name}")
            else:
                from .song_view import SongView
                setup = prepare_song(song.practice_path, song.phrase_dir, settings, sr,
                                     log=lambda *_: None)
                view = SongView(engine, song.practice_path, setup.audio, setup.curve,
                                song.phrase_dir, settings, scale, setup.my_tonic,
                                same_key=setup.same_key, start_seconds=setup.start_seconds)
        except Exception as exc:
            QtWidgets.QApplication.restoreOverrideCursor()
            traceback.print_exc()
            QtWidgets.QMessageBox.warning(self, "Avaz Trainer", f"could not start practice: {exc}")
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        view.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        view.destroyed.connect(self._practice_closed)
        view.resize(1200, 700)
        view.show()
        engine.start()
        self.practice_window = view

    def _practice_closed(self, *_):
        self.practice_window = None
        self.refresh()


def run_launcher(screenshot: str | None = None, quit_after: float | None = None) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = Launcher()
    window.resize(1000, 620)
    window.show()
    if quit_after:
        def _finish():
            if screenshot:
                window.grab().save(screenshot)
            window.close()
        QtCore.QTimer.singleShot(int(quit_after * 1000), _finish)
    return app.exec()
