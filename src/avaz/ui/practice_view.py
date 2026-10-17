"""Practice window: teacher curve, my live curve on top, cursor, keyboard control."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..feedback import HIGHER, LOWER, attempt_feedback, gentle_feedback, note_hits
from ..live import PitchStream, build_pitch_stream
from ..practice import (IDLE, PLAY, WAIT, RESPOND, DONE, SPEEDS, Attempt, OnsetDetector,
                        PracticeEngine, Session, load_phrase, octave_shift, save_attempt,
                        sibling_phrases, time_stretch)
from ..scales import Scale
from .note_display import NoteDisplay

HELP = ("Space or Enter start/stop   L loop   [ ] speed   M mode   N/P next/prev phrase   "
        "D notes/curve   O octave fold   V voice start   Esc quit")


class PracticeView(QtWidgets.QMainWindow):
    def __init__(self, engine: PracticeEngine, phrase_path: Path, settings: dict,
                 scale: Scale | None, my_tonic: float | None, mode: str = "after",
                 speed: float = 1.0, loop: bool = False, same_key: bool | None = None):
        super().__init__()
        self.engine = engine
        self.settings = settings
        self.scale = scale
        self.colors = settings.get("colors", {})
        pr = settings.get("practice", {})
        self.margin = float(pr.get("response_margin_seconds", 0.5))
        self.gap = float(pr.get("loop_gap_seconds", 0.7))
        self.fold = bool(pr.get("fold_octave", True))
        self.voice_start = bool(pr.get("start_on_voice", True))
        self.grace_samples = int(float(pr.get("onset_grace_seconds", 0.4)) * engine.sample_rate)
        self.onset: OnsetDetector | None = None
        self.mode = mode
        self.speed = float(speed)
        self.loop = loop
        self.my_tonic_override = my_tonic
        self.same_key_override = same_key
        self.same_key = False
        self.phrases = sibling_phrases(Path(phrase_path))
        self.index = self.phrases.index(Path(phrase_path)) if Path(phrase_path) in self.phrases else 0
        self.attempt: Attempt | None = None
        self.last_score = None
        self._last_hits: dict[str, tuple[int, int]] = {}   # phrase -> (hit, sung) of my last try
        self.session = Session(0, 0, mode)
        self.stretched: dict[float, np.ndarray] = {}
        self.shift = 0.0
        self.count = 0

        self._build_ui()
        self._load_phrase(self.phrases[self.index])

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # ---------------------------------------------------------------- UI setup
    def _build_ui(self):
        pg.setConfigOptions(antialias=False, background="k", foreground="w")
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        self.setCentralWidget(central)

        self.header = QtWidgets.QLabel("")
        font = QtGui.QFont()
        font.setPointSize(14)
        self.header.setFont(font)
        layout.addWidget(self.header)

        self.plot = pg.PlotWidget()
        self.plot.setLabel("left", "cents relative to tonic")
        self.plot.setLabel("bottom", "seconds")
        self.plot.setMouseEnabled(x=False, y=True)
        layout.addWidget(self.plot, stretch=1)

        display = self.settings.get("display", {})
        self.display = NoteDisplay(
            self.plot, self.scale, self.colors, None,
            notes=display.get("style", "notes") == "notes",
            tolerance=float(self.settings.get("scoring", {}).get("tolerance_cents", 25)))
        self.cursor = pg.InfiniteLine(0, angle=90, pen=pg.mkPen("#ffffff", width=1))
        self.plot.addItem(self.cursor)

        self.state_label = QtWidgets.QLabel("")
        font2 = QtGui.QFont()
        font2.setPointSize(20)
        font2.setBold(True)
        self.state_label.setFont(font2)
        self.state_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.state_label)

        self.feedback_label = QtWidgets.QLabel("After each attempt, tips appear here.")
        self.feedback_label.setWordWrap(True)
        font3 = QtGui.QFont()
        font3.setPointSize(13)
        self.feedback_label.setFont(font3)
        self.feedback_label.setStyleSheet("padding: 4px 8px")
        layout.addWidget(self.feedback_label)
        self.statusBar().showMessage(HELP)

    # ---------------------------------------------------------------- phrase
    def _load_phrase(self, path: Path):
        self._stop()
        self.phrase = load_phrase(path, self.engine.sample_rate)
        self.stretched = {}
        self.count = 0
        self.shift = 0.0
        from ..config import load_song_config, resolve_tonics
        curve = self.phrase.curve
        teacher_tonic, my_tonic, self.same_key = resolve_tonics(
            load_song_config(self.phrase.audio_path.parent), self.settings,
            curve_tonic=curve.tonic_hz if curve is not None else None,
            my_tonic=self.my_tonic_override, same_key=self.same_key_override)
        teacher_tonic = teacher_tonic or 185.0
        if curve is not None and abs(curve.tonic_hz - teacher_tonic) > 1e-6:
            self.phrase.curve = curve.with_tonic(teacher_tonic)
        self.teacher_tonic = teacher_tonic
        if self.same_key:
            my_tonic = teacher_tonic       # the teacher sang in my range: no transposing
            self.fold = False
        self.stream: PitchStream = build_pitch_stream(self.settings, float(my_tonic or teacher_tonic))
        self.display.set_name_tonic(self.stream.tonic_hz)
        self.display.set_mine([], [])
        self._redraw_teacher()
        self._update_header()

    def _redraw_teacher(self):
        c = self.phrase.curve
        if c is None:
            lo, hi = -700, 1900
        else:
            finite = c.cents[np.isfinite(c.cents)]
            if finite.size:
                lo = float(np.floor((np.percentile(finite, 1) - 300) / 100) * 100)
                hi = float(np.ceil((np.percentile(finite, 99) + 300) / 100) * 100)
            else:
                lo, hi = -700, 1900
        self.plot.setYRange(lo, hi, padding=0)
        self.plot.setXRange(0, self.phrase.duration / self.speed + (self.margin if self.mode == "after" else 0),
                            padding=0.01)
        self.display.set_range(lo, hi)
        if c is None:
            self.display.set_teacher([], [])
        else:
            self.display.set_teacher(c.times / self.speed, c.cents)

    def _play_buffer(self) -> np.ndarray:
        if self.speed not in self.stretched:
            self.stretched[self.speed] = time_stretch(self.phrase.y, self.phrase.sample_rate, self.speed)
        return self.stretched[self.speed]

    # ---------------------------------------------------------------- control
    def _start(self):
        buf = self._play_buffer()
        sr = self.engine.sample_rate
        pr = self.settings.get("practice", {})
        respond = buf.size + int(self.margin * sr)
        wait = int(float(pr.get("wait_timeout_seconds", 15)) * sr) if self.voice_start else 0
        self.session = Session(play_len=buf.size, respond_len=respond, mode=self.mode,
                               wait_len=wait)
        self.stream = build_pitch_stream(self.settings, self.stream.tonic_hz)
        self.attempt = Attempt(self.stream, time_offset=self._latency_offset())
        self.onset = OnsetDetector(self.stream.detector, self.stream.hop_length,
                                   rms_db=float(pr.get("onset_rms_db", -40)),
                                   voiced_frames=int(pr.get("onset_voiced_frames", 6)),
                                   preroll_seconds=float(pr.get("onset_preroll_seconds", 0.15)))
        self.display.set_mine([], [])
        self.shift = 0.0
        self._redraw_teacher()
        self.engine.begin(self.session, buf)
        self._update_header()

    def _latency_offset(self) -> float:
        cfg = self.settings.get("practice", {}).get("latency_compensation", "auto")
        if cfg == "auto":
            lat = getattr(self.engine, "latency", (0.0, 0.0))
            return float(lat[0] + lat[1])
        return float(cfg or 0.0)

    def _stop(self):
        self.engine.stop_session()
        self.attempt = None
        self.session = Session(0, 0, self.mode)
        self._update_header()

    def _show_feedback(self, hints):
        lines = []
        for h in hints:
            if not h.text:
                continue                    # chart marks: this window has none
            text = h.text.replace("&", "&amp;").replace("<", "&lt;")
            if h.kind == "overall":
                text = f"<b>{text}</b>"
            if h.direction in (HIGHER, LOWER):
                text = f'<span style="color:#e67e22">{text}</span>'
            lines.append(text)
        self.feedback_label.setText("<br>".join(lines))

    def _finish_attempt(self):
        if self.attempt is not None and self.attempt.blocks:
            wav = save_attempt(self.attempt, self.phrase, self.mode, self.speed,
                               self.teacher_tonic, self.shift,
                               extra={"same_key": self.same_key})
            self.count += 1
            msg = f"saved {wav.name}"
            if self.phrase.curve is not None:
                try:
                    from ..compare import score_attempt, record_score
                    tol = float(self.settings.get("scoring", {}).get("tolerance_cents", 25))
                    result = score_attempt(self.phrase.curve, self.attempt.curve(wav.name),
                                           tolerance=tol, same_key=self.same_key)
                    record_score(wav, result, "live")
                    self.last_score = result
                    fb = self.settings.get("feedback", {})
                    if fb.get("level", "gentle") != "detailed":
                        key = str(self.phrase.audio_path)
                        self._show_feedback(gentle_feedback(result, self.stream.tonic_hz, 0.0, fb,
                                                            previous=self._last_hits.get(key)))
                        self._last_hits[key] = note_hits(result, fb)
                    else:
                        msg += (f"    score: {result.pct_within:.0f}% within {tol:.0f}c, "
                                f"mean {result.mad:.0f}c")
                        self._show_feedback(attempt_feedback(result, self.stream.tonic_hz, 0.0, fb))
                except Exception as exc:          # scoring must never break practice
                    msg += f"    (score failed: {exc})"
            self.statusBar().showMessage(f"{msg}    {HELP}")
        self.session.finish()
        self.attempt = None
        if self.loop:
            QtCore.QTimer.singleShot(int(self.gap * 1000), self._loop_restart)
        self._update_header()

    def _loop_restart(self):
        if self.loop and self.session.phase == IDLE:
            self._start()

    def keyPressEvent(self, event):
        key, text = event.key(), event.text()
        if key == QtCore.Qt.Key_Escape:
            self.close()
        elif key in (QtCore.Qt.Key_Space, QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if self.session.phase == IDLE:
                self._start()
            else:
                self._stop()
        elif key == QtCore.Qt.Key_L:
            self.loop = not self.loop
            if self.loop and self.session.phase == IDLE:
                self._start()
        elif text == "[":
            self._set_speed(-1)
        elif text == "]":
            self._set_speed(+1)
        elif key == QtCore.Qt.Key_M:
            self.mode = "along" if self.mode == "after" else "after"
            self._stop()
            self._redraw_teacher()
        elif key == QtCore.Qt.Key_N:
            self._change_phrase(+1)
        elif key == QtCore.Qt.Key_P:
            self._change_phrase(-1)
        elif key == QtCore.Qt.Key_D:
            self.display.toggle()
        elif key == QtCore.Qt.Key_O:
            self.fold = not self.fold
            if not self.fold:
                self.shift = 0.0
        elif key == QtCore.Qt.Key_V:
            self.voice_start = not self.voice_start
            if self.session.phase == WAIT:
                self.engine.trigger_respond(0)
        else:
            super().keyPressEvent(event)
        self._update_header()

    def _set_speed(self, step: int):
        i = min(range(len(SPEEDS)), key=lambda k: abs(SPEEDS[k] - self.speed))
        self.speed = SPEEDS[max(0, min(len(SPEEDS) - 1, i + step))]
        if self.session.phase == IDLE:
            self._redraw_teacher()

    def _change_phrase(self, step: int):
        self.index = (self.index + step) % len(self.phrases)
        self._load_phrase(self.phrases[self.index])

    def closeEvent(self, event):
        self.timer.stop()
        try:
            self.engine.close()
        except Exception:
            pass
        super().closeEvent(event)

    # ---------------------------------------------------------------- per frame
    def _tick(self):
        phase = self.session.phase
        sr = self.engine.sample_rate
        for item in self.engine.captured.drain():
            tag, pos, block = item
            if self.attempt is None:
                continue
            if tag == WAIT:
                if pos < self.grace_samples and not (self.onset and self.onset.triggered):
                    continue      # speakers still ringing with the end of the phrase
                if self.onset is not None and not self.onset.triggered:
                    if self.onset.feed(block):
                        # Start the response window and count the pre-roll as its start,
                        # so the beginning of my first note is part of the attempt.
                        preroll = self.onset.preroll
                        if self.engine.trigger_respond(preroll.size):
                            self.attempt.add(preroll)
                elif self.onset is not None and self.onset.triggered:
                    self.attempt.add(block)      # queued just before the trigger took effect
            elif tag == self.session.recording_phase:
                self.attempt.add(block)
        if self.attempt is not None and self.attempt.points:
            t = np.array([p[0] for p in self.attempt.points])
            c = np.array([p[2] for p in self.attempt.points])
            if self.fold and self.phrase.curve is not None:
                self.shift = octave_shift(c, self.phrase.curve.cents)
            self.display.set_mine(t, c + self.shift)
        if phase in (PLAY, RESPOND):
            self.cursor.setPos(self.session.pos / sr)
        elif phase == WAIT:
            self.cursor.setPos(0)
        elif phase == DONE:
            if self.session.timed_out:
                self.attempt = None
                self.statusBar().showMessage(f"no voice detected, attempt dropped    {HELP}")
            self._finish_attempt()
        self._update_state_label()

    def _update_header(self):
        if not hasattr(self, "phrase"):
            return
        if self.same_key:
            tonic = f"tonic {self.teacher_tonic:.1f} Hz, same key"
        else:
            tonic = f"tonic: teacher {self.teacher_tonic:.1f} Hz / mine {self.stream.tonic_hz:.1f} Hz"
        self.header.setText(
            f"{self.phrase.name}   [{self.index + 1}/{len(self.phrases)}]   "
            f"mode: {self.mode}   speed: {self.speed:.1f}   loop: {'on' if self.loop else 'off'}   "
            f"voice start: {'on' if self.voice_start else 'off'}   {tonic}   "
            f"attempts this phrase: {self.count}")

    def _update_state_label(self):
        phase = self.session.phase
        if phase == IDLE:
            txt, color = "Space or Enter to start", "#aaaaaa"
        elif phase == PLAY:
            txt, color = ("LISTEN" if self.mode == "after" else "SING ALONG"), "#3498db"
        elif phase == WAIT:
            txt, color = "SING WHEN READY", "#f1c40f"
        elif phase == RESPOND:
            txt, color = "YOUR TURN", "#e74c3c"
        else:
            txt, color = "...", "#aaaaaa"
        if self.shift:
            txt += f"   (curve shifted {self.shift:+.0f} cents)"
        self.state_label.setText(txt)
        self.state_label.setStyleSheet(f"color: {color}")


def run_practice_view(engine: PracticeEngine, phrase_path: Path, settings: dict,
                      scale: Scale | None, my_tonic: float | None, mode: str, speed: float,
                      loop: bool, screenshot: str | None = None,
                      quit_after: float | None = None, autostart: bool = False,
                      same_key: bool | None = None) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    view = PracticeView(engine, phrase_path, settings, scale, my_tonic, mode, speed, loop,
                        same_key=same_key)
    view.resize(1200, 700)
    view.setWindowTitle("avaz practice")
    view.show()
    engine.start()
    if autostart:
        view._start()
    if quit_after:
        def _finish():
            if screenshot:
                view.grab().save(screenshot)
            view.close()
        QtCore.QTimer.singleShot(int(quit_after * 1000), _finish)
    return app.exec()
