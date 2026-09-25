"""Freeform practice window: play a whole recording, pause anywhere to sing.

Unlike :mod:`practice_view`, there are no pre-cut phrases. I walk through the
recording myself: Space starts it, Space again pauses it right where I want to
sing, and Space a third time saves what I sang and moves the teacher on from
that same spot. R replays the stretch I just sang instead of moving on. Every
stretch I pause on is saved as a normal phrase (WAV plus pitch curve) the first
time I finish it, so it works afterwards with ``avaz score``, ``avaz history``
and ordinary ``avaz practice``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..cents import OCTAVE, octave_shift
from ..live import PitchStream, build_pitch_stream
from ..practice import (IDLE, PLAY, RESPOND, Attempt, FreeformSession, PracticeEngine,
                        export_live_segment, load_phrase, save_attempt)
from ..scales import Scale

HELP = "Space start/pause/next   R repeat this stretch   O octave fold   Esc quit"


class SongView(QtWidgets.QMainWindow):
    def __init__(self, engine: PracticeEngine, song_path: Path, song_audio: np.ndarray,
                 teacher_curve, out_dir: Path, settings: dict, scale: Scale | None,
                 my_tonic: float, view_seconds: float = 20.0):
        super().__init__()
        self.engine = engine
        self.settings = settings
        self.scale = scale
        self.colors = settings.get("colors", {})
        self.teacher_curve = teacher_curve
        self.teacher_tonic = teacher_curve.tonic_hz if teacher_curve is not None else my_tonic
        self.my_tonic = my_tonic
        self.out_dir = Path(out_dir)
        self.view_seconds = float(view_seconds)
        self.fold = bool(settings.get("practice", {}).get("fold_octave", True))
        self.pr = settings.get("practice", {})

        self.freeform = FreeformSession(total_len=song_audio.size)
        self.engine.load(self.freeform, song_audio)
        self._prev_phase = IDLE
        self._exported_key: tuple[int, int] | None = None
        self._exported_wav: Path | None = None
        self.attempt: Attempt | None = None
        self.shift = 0.0
        self.saved_count = 0

        self._build_ui()
        self.setWindowTitle(f"avaz song: {song_path.stem}")

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _build_ui(self):
        pg.setConfigOptions(antialias=False, background="k", foreground="w")
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        self.setCentralWidget(central)

        self.header = QtWidgets.QLabel("")
        font = QtGui.QFont(); font.setPointSize(13)
        self.header.setFont(font)
        layout.addWidget(self.header)

        self.plot = pg.PlotWidget()
        self.plot.setLabel("left", "cents relative to tonic")
        self.plot.setLabel("bottom", "song time (s)")
        self.plot.setMouseEnabled(x=False, y=True)
        layout.addWidget(self.plot, stretch=1)

        c = self.teacher_curve
        lo, hi = -700.0, 1900.0
        if c is not None:
            finite = c.cents[np.isfinite(c.cents)]
            if finite.size:
                lo = float(np.floor((np.percentile(finite, 0.5) - 200) / 100) * 100)
                hi = float(np.ceil((np.percentile(finite, 99.5) + 200) / 100) * 100)
        self.plot.setYRange(lo, hi, padding=0)
        self._draw_guides(lo, hi)

        self.teacher_line = self.plot.plot(
            c.times if c is not None else [], c.cents if c is not None else [],
            pen=pg.mkPen(self.colors.get("teacher", "#1f77b4"), width=1.3), connect="finite")
        self.my_curve = self.plot.plot([], [], pen=pg.mkPen(self.colors.get("mine", "#d62728"),
                                                            width=2), connect="finite")
        self.cursor = pg.InfiniteLine(0, angle=90, pen=pg.mkPen("#ffffff", width=1))
        self.plot.addItem(self.cursor)
        self.segment_box = pg.LinearRegionItem(values=(0, 0), movable=False, brush=(255, 255, 255, 20))
        self.segment_box.setVisible(False)
        self.plot.addItem(self.segment_box)

        self.state_label = QtWidgets.QLabel("Space to begin")
        f2 = QtGui.QFont(); f2.setPointSize(20); f2.setBold(True)
        self.state_label.setFont(f2)
        self.state_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.state_label)
        self.statusBar().showMessage(HELP)

    def _draw_guides(self, lo, hi):
        if self.scale is None:
            self.plot.addItem(pg.InfiniteLine(0, angle=0,
                              pen=pg.mkPen(self.colors.get("tonic", "#2ca02c"), width=2)))
            return
        for cents, label in self.scale.positions_in_range(lo, hi):
            is_tonic = abs(cents % OCTAVE) < 1e-6
            pen = pg.mkPen(self.colors.get("tonic" if is_tonic else "guide", "#888888"),
                           width=2 if is_tonic else 1,
                           style=QtCore.Qt.SolidLine if is_tonic else QtCore.Qt.DashLine)
            self.plot.addItem(pg.InfiniteLine(cents, angle=0, pen=pen, label=label,
                              labelOpts={"position": 0.01, "color": "#aaaaaa", "movable": False}))

    # ------------------------------------------------------------------ actions
    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key_Escape:
            self.close()
        elif key == QtCore.Qt.Key_Space:
            self.engine.toggle()
        elif key == QtCore.Qt.Key_R:
            self.engine.repeat_segment()
        elif key == QtCore.Qt.Key_O:
            self.fold = not self.fold
            if not self.fold:
                self.shift = 0.0
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.timer.stop()
        try:
            self.engine.stop_session()
            self.engine.close()
        except Exception:
            pass
        super().closeEvent(event)

    # ------------------------------------------------------------------ per frame
    def _tick(self):
        sr = self.engine.sample_rate
        phase = self.freeform.phase
        entering_respond = phase == RESPOND and self._prev_phase != RESPOND
        leaving_respond = self._prev_phase == RESPOND and phase != RESPOND

        if entering_respond:
            self._begin_response()
        for tag, pos, block in self.engine.captured.drain():
            if tag == RESPOND and self.attempt is not None:
                self.attempt.add(block)
        if leaving_respond:
            self._end_response()

        if self.attempt is not None and self.attempt.points:
            t = np.array([p[0] for p in self.attempt.points])
            cts = np.array([p[2] for p in self.attempt.points])
            if self.fold and self.teacher_curve is not None:
                seg = self.teacher_curve.cents[
                    (self.teacher_curve.times >= self.freeform.segment_start / sr) &
                    (self.teacher_curve.times < self.freeform.segment_end / sr)]
                self.shift = octave_shift(cts, seg, min_points=5)
            self.my_curve.setData(t + self.freeform.segment_start / sr, cts + self.shift)

        self.cursor.setPos(self.freeform.pos / sr)
        self._update_view_range(phase, sr)
        self._update_labels(phase)
        self._prev_phase = phase

    def _begin_response(self):
        key = (self.freeform.segment_start, self.freeform.segment_end)
        pr = self.pr
        stream = build_pitch_stream(self.settings, self.my_tonic)
        lat = getattr(self.engine, "latency", (0.0, 0.0))
        offset = lat[0] + lat[1] if pr.get("latency_compensation", "auto") == "auto" else \
            float(pr.get("latency_compensation") or 0.0)
        self.attempt = Attempt(stream, time_offset=offset)
        self.my_curve.setData([], [])
        self.shift = 0.0
        if key != self._exported_key:
            start_s = self.freeform.segment_start / self.engine.sample_rate
            end_s = self.freeform.segment_end / self.engine.sample_rate
            wav = export_live_segment(self.engine.play_buffer, self.engine.sample_rate,
                                      self.teacher_curve, start_s, end_s, self.out_dir)
            self._exported_key, self._exported_wav = key, wav

    def _end_response(self):
        if self.attempt is None or not self.attempt.blocks or self._exported_wav is None:
            self.attempt = None
            return
        phrase = load_phrase(self._exported_wav, self.engine.sample_rate)
        wav = save_attempt(self.attempt, phrase, "freeform", 1.0, self.teacher_tonic, self.shift)
        self.saved_count += 1
        msg = f"saved {wav.name} ({phrase.name})"
        if phrase.curve is not None:
            try:
                from ..compare import score_curves, record_score
                tol = float(self.settings.get("scoring", {}).get("tolerance_cents", 25))
                result = score_curves(phrase.curve, self.attempt.curve(wav.name), tolerance=tol)
                record_score(wav, result, "live")
                msg += f"    score: {result.pct_within:.0f}% within {tol:.0f}c, mean {result.mad:.0f}c"
            except Exception as exc:
                msg += f"    (score failed: {exc})"
        self.statusBar().showMessage(f"{msg}    {HELP}")
        self.attempt = None

    def _update_view_range(self, phase, sr):
        pos = self.freeform.pos / sr
        if phase == RESPOND:
            a, b = self.freeform.segment_start / sr, self.freeform.segment_end / sr
            pad = max(0.3, (b - a) * 0.08)
            self.plot.setXRange(a - pad, b + pad, padding=0)
            self.segment_box.setRegion((a, b))
            self.segment_box.setVisible(True)
        else:
            self.segment_box.setVisible(False)
            if phase == PLAY:
                lead = self.view_seconds * 0.3
                self.plot.setXRange(pos - lead, pos + (self.view_seconds - lead), padding=0)

    def _update_labels(self, phase):
        total_s = self.freeform.total_len / self.engine.sample_rate
        pos_s = self.freeform.pos / self.engine.sample_rate
        self.header.setText(
            f"{pos_s:6.1f} / {total_s:6.1f} s   tonic: teacher {self.teacher_tonic:.1f} Hz / "
            f"mine {self.my_tonic:.1f} Hz   fold: {'on' if self.fold else 'off'}   "
            f"saved this session: {self.saved_count}")
        if phase == IDLE:
            txt, color = ("song finished, close whenever you like" if self.freeform.reached_end
                          else "Space to begin"), "#aaaaaa"
        elif phase == PLAY:
            txt, color = "LISTEN", "#3498db"
        else:
            txt, color = "YOUR TURN", "#e74c3c"
        if self.shift:
            txt += f"   (curve shifted {self.shift:+.0f} cents)"
        self.state_label.setText(txt)
        self.state_label.setStyleSheet(f"color: {color}")


def run_song_view(engine: PracticeEngine, song_path: Path, song_audio, teacher_curve,
                  out_dir: Path, settings: dict, scale: Scale | None, my_tonic: float,
                  script: list | None = None, screenshot: str | None = None,
                  quit_after: float | None = None) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    view = SongView(engine, song_path, song_audio, teacher_curve, out_dir, settings, scale, my_tonic)
    view.resize(1200, 700)
    view.show()
    engine.start()

    if script:
        t = 0.0
        for step in script:
            if step.startswith("wait:"):
                t += float(step.split(":", 1)[1])
                continue
            action = {"space": engine.toggle, "repeat": engine.repeat_segment}.get(step)
            if action:
                QtCore.QTimer.singleShot(int(t * 1000), action)
    if quit_after:
        def _finish():
            if screenshot:
                view.grab().save(screenshot)
            view.close()
        QtCore.QTimer.singleShot(int(quit_after * 1000), _finish)
    return app.exec()
